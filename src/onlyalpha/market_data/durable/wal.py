"""Finite checksummed filesystem WAL segments with explicit durability."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .codec import only_decode_record_bundle, only_encode_record_bundle
from .models import (
    OnlyIngestSegment,
    OnlyMarketDataHealth,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecordBundle,
    OnlyRecordingState,
)

_MAGIC = b"OAMD"
_VERSION = 1
_HEADER = struct.Struct(">4sBQQ32s")
_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class OnlyWalError(RuntimeError):
    pass


class OnlyWalCapacityError(OnlyWalError):
    pass


class OnlyWalCorruptionError(OnlyWalError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyWalRecoveryResult:
    segment_id: str
    valid_records: int
    quarantined_tail: Path | None


class OnlyMarketDataWal:
    """A record is accepted only after its frame and fsync complete."""

    def __init__(
        self,
        root: Path,
        *,
        capacity_bytes: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        identity_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        if capacity_bytes <= _HEADER.size:
            raise ValueError("WAL_CAPACITY_INVALID")
        self.root = root
        self.capacity_bytes = capacity_bytes
        self._now = now
        self._identity_factory = identity_factory
        root.mkdir(parents=True, exist_ok=True)
        self._open_id: str | None = None
        self._created_at: datetime | None = None
        self._recording_state = OnlyRecordingState.HEALTHY
        self._last_error: str | None = None

    @property
    def bytes_used(self) -> int:
        return sum(
            path.stat().st_size for pattern in ("*.open.wal", "*.sealed.wal") for path in self.root.glob(pattern)
        )

    @property
    def recording_state(self) -> OnlyRecordingState:
        if self._recording_state is not OnlyRecordingState.HEALTHY:
            return self._recording_state
        return OnlyRecordingState.DEGRADED if self.bytes_used >= self.capacity_bytes else OnlyRecordingState.HEALTHY

    def open_segment(self, segment_id: str | None = None) -> str:
        if self._open_id is not None:
            raise OnlyWalError("WAL_SEGMENT_ALREADY_OPEN")
        selected = segment_id or self._identity_factory()
        if any(self._path(selected, state).exists() for state in ("open", "sealed", "gc", "abandoned")) or any(
            (self.root / f"{selected}.{state}.json").exists() for state in ("open", "segment", "gc", "abandoned")
        ):
            raise OnlyWalError("WAL_SEGMENT_ID_CONFLICT")
        created_at = self._now()
        self._path(selected, "open").touch(exist_ok=False)
        self._write_json(
            self.root / f"{selected}.open.json",
            {"schema_version": 1, "segment_id": selected, "created_at": created_at.isoformat()},
        )
        self._fsync_directory()
        self._open_id = selected
        self._created_at = created_at
        return selected

    def append(self, bundle: OnlyMarketDataRecordBundle) -> int:
        if self._open_id is None:
            raise OnlyWalError("WAL_SEGMENT_NOT_OPEN")
        path = self._path(self._open_id, "open")
        ordinal = sum(1 for _ in self._read_frames(path, sealed=False))
        payload = only_encode_record_bundle(bundle)
        frame = _HEADER.pack(_MAGIC, _VERSION, len(payload), ordinal, hashlib.sha256(payload).digest()) + payload
        if self.bytes_used + len(frame) > self.capacity_bytes:
            self._recording_state = OnlyRecordingState.DEGRADED
            self._last_error = "WAL_CAPACITY_FULL"
            raise OnlyWalCapacityError("WAL_CAPACITY_FULL")
        with path.open("ab", buffering=0) as stream:
            stream.write(frame)
            os.fsync(stream.fileno())
        return ordinal

    def seal(self) -> OnlyIngestSegment:
        if self._open_id is None or self._created_at is None:
            raise OnlyWalError("WAL_SEGMENT_NOT_OPEN")
        segment_id = self._open_id
        source = self._path(segment_id, "open")
        records = tuple(self._read_frames(source, sealed=False))
        if not records:
            raise OnlyWalError("WAL_EMPTY_SEGMENT")
        bundles = tuple(only_decode_record_bundle(item) for _, item in records)
        evidence = bundles[0].evidence
        scope_identity = (
            evidence.capture_session_id,
            evidence.source_id,
            evidence.provider,
            evidence.venue,
            evidence.market,
            evidence.stream,
            evidence.provenance,
            evidence.provider_schema,
            evidence.payload_codec,
        )
        if any(
            (
                item.evidence.capture_session_id,
                item.evidence.source_id,
                item.evidence.provider,
                item.evidence.venue,
                item.evidence.market,
                item.evidence.stream,
                item.evidence.provenance,
                item.evidence.provider_schema,
                item.evidence.payload_codec,
            )
            != scope_identity
            for item in bundles
        ):
            raise OnlyWalError("WAL_SEGMENT_SCOPE_CONFLICT")
        content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        target = self._path(segment_id, "sealed")
        os.replace(source, target)
        self._fsync_directory()
        sealed_at = self._now()
        result = OnlyIngestSegment(
            segment_id,
            evidence.capture_session_id,
            evidence.source_id,
            evidence.market,
            evidence.stream,
            evidence.provider,
            evidence.venue,
            evidence.provenance,
            evidence.provider_schema,
            evidence.payload_codec,
            1,
            len(bundles),
            len(bundles),
            sum(len(item.canonical_facts) for item in bundles),
            content_hash,
            self._created_at,
            sealed_at,
        )
        self._write_json(
            self.root / f"{segment_id}.segment.json",
            {
                "schema_version": 1,
                "segment_id": result.segment_id,
                "capture_session_id": result.capture_session_id,
                "source_id": result.source_id,
                "market": result.market,
                "stream": result.stream,
                "provider": result.provider,
                "venue": result.venue,
                "capture_mode": result.capture_mode.value,
                "provider_schema": result.provider_schema,
                "codec": result.codec,
                "record_count": result.record_count,
                "raw_count": result.raw_count,
                "canonical_count": result.canonical_count,
                "content_hash": result.content_hash,
                "created_at": result.created_at.isoformat(),
                "sealed_at": result.sealed_at.isoformat(),
            },
        )
        (self.root / f"{segment_id}.open.json").unlink()
        self._fsync_directory()
        self._open_id = None
        self._created_at = None
        return result

    def load_segment(self, segment_id: str) -> OnlyIngestSegment:
        metadata_path = self.root / f"{segment_id}.segment.json"
        if not metadata_path.exists():
            self._recover_sealed_metadata(segment_id)
        raw = json.loads(metadata_path.read_text())
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise OnlyWalCorruptionError("WAL_SEGMENT_METADATA_INVALID")
        result = OnlyIngestSegment(
            str(raw["segment_id"]),
            str(raw["capture_session_id"]),
            str(raw["source_id"]),
            str(raw["market"]),
            str(raw["stream"]),
            str(raw["provider"]),
            str(raw["venue"]),
            OnlyMarketDataProvenance(str(raw["capture_mode"])),
            str(raw["provider_schema"]),
            str(raw["codec"]),
            1,
            int(str(raw["record_count"])),
            int(str(raw["raw_count"])),
            int(str(raw["canonical_count"])),
            str(raw["content_hash"]),
            datetime.fromisoformat(str(raw["created_at"])),
            datetime.fromisoformat(str(raw["sealed_at"])),
        )
        if not self.verify_sealed(result):
            raise OnlyWalCorruptionError("WAL_SEGMENT_METADATA_HASH_MISMATCH")
        return result

    def _recover_sealed_metadata(self, segment_id: str) -> None:
        sealed = self._path(segment_id, "sealed")
        open_metadata_path = self.root / f"{segment_id}.open.json"
        if not sealed.exists() or not open_metadata_path.exists():
            raise OnlyWalCorruptionError("WAL_SEGMENT_METADATA_MISSING")
        open_metadata = json.loads(open_metadata_path.read_text())
        if (
            not isinstance(open_metadata, dict)
            or open_metadata.get("schema_version") != 1
            or open_metadata.get("segment_id") != segment_id
        ):
            raise OnlyWalCorruptionError("WAL_OPEN_METADATA_INVALID")
        frames = tuple(self._read_frames(sealed, sealed=True))
        if not frames:
            raise OnlyWalCorruptionError("WAL_RECOVERED_SEGMENT_EMPTY")
        bundles = tuple(only_decode_record_bundle(payload) for _, payload in frames)
        evidence = bundles[0].evidence
        scope_identity = (
            evidence.capture_session_id,
            evidence.source_id,
            evidence.provider,
            evidence.venue,
            evidence.market,
            evidence.stream,
            evidence.provenance,
            evidence.provider_schema,
            evidence.payload_codec,
        )
        if any(
            (
                item.evidence.capture_session_id,
                item.evidence.source_id,
                item.evidence.provider,
                item.evidence.venue,
                item.evidence.market,
                item.evidence.stream,
                item.evidence.provenance,
                item.evidence.provider_schema,
                item.evidence.payload_codec,
            )
            != scope_identity
            for item in bundles
        ):
            raise OnlyWalCorruptionError("WAL_SEGMENT_SCOPE_CONFLICT")
        self._write_json(
            self.root / f"{segment_id}.segment.json",
            {
                "schema_version": 1,
                "segment_id": segment_id,
                "capture_session_id": evidence.capture_session_id,
                "source_id": evidence.source_id,
                "market": evidence.market,
                "stream": evidence.stream,
                "provider": evidence.provider,
                "venue": evidence.venue,
                "capture_mode": evidence.provenance.value,
                "provider_schema": evidence.provider_schema,
                "codec": evidence.payload_codec,
                "record_count": len(bundles),
                "raw_count": len(bundles),
                "canonical_count": sum(len(item.canonical_facts) for item in bundles),
                "content_hash": hashlib.sha256(sealed.read_bytes()).hexdigest(),
                "created_at": str(open_metadata["created_at"]),
                "sealed_at": self._now().isoformat(),
            },
        )
        open_metadata_path.unlink()
        self._fsync_directory()

    def read_sealed(self, segment_id: str) -> tuple[OnlyMarketDataRecordBundle, ...]:
        path = self._path(segment_id, "sealed")
        return tuple(only_decode_record_bundle(payload) for _, payload in self._read_frames(path, sealed=True))

    def verify_sealed(self, segment: OnlyIngestSegment) -> bool:
        path = self._path(segment.segment_id, "sealed")
        records = tuple(self._read_frames(path, sealed=True))
        return (
            len(records) == segment.record_count
            and hashlib.sha256(path.read_bytes()).hexdigest() == segment.content_hash
        )

    def recover_open(self, segment_id: str) -> OnlyWalRecoveryResult:
        path = self._path(segment_id, "open")
        valid_end = 0
        valid_records = 0
        try:
            for end, _ in self._read_frames(path, sealed=False):
                valid_end = end
                valid_records += 1
        except OnlyWalCorruptionError:
            self._recording_state = OnlyRecordingState.DEGRADED
            self._last_error = "WAL_OPEN_CORRUPTION_QUARANTINED"
            data = path.read_bytes()
            tail = data[valid_end:]
            quarantine = self.root / f"{segment_id}.corrupt-tail"
            quarantine.write_bytes(tail)
            with path.open("r+b") as stream:
                stream.truncate(valid_end)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory()
            return OnlyWalRecoveryResult(segment_id, valid_records, quarantine)
        return OnlyWalRecoveryResult(segment_id, valid_records, None)

    def seal_recovered_open(self, segment_id: str) -> OnlyIngestSegment:
        if self._open_id is not None:
            raise OnlyWalError("WAL_SEGMENT_ALREADY_OPEN")
        metadata_path = self.root / f"{segment_id}.open.json"
        if not metadata_path.exists():
            raise OnlyWalCorruptionError("WAL_OPEN_METADATA_MISSING")
        metadata = json.loads(metadata_path.read_text())
        if (
            not isinstance(metadata, dict)
            or metadata.get("schema_version") != 1
            or metadata.get("segment_id") != segment_id
        ):
            raise OnlyWalCorruptionError("WAL_OPEN_METADATA_INVALID")
        recovered = self.recover_open(segment_id)
        if recovered.valid_records == 0:
            raise OnlyWalCorruptionError("WAL_RECOVERED_SEGMENT_EMPTY")
        self._open_id = segment_id
        self._created_at = datetime.fromisoformat(str(metadata["created_at"]))
        return self.seal()

    def abandon_empty_open(self, segment_id: str) -> Path:
        source = self._path(segment_id, "open")
        metadata = self.root / f"{segment_id}.open.json"
        if not source.exists() or source.stat().st_size != 0 or not metadata.exists():
            raise OnlyWalCorruptionError("WAL_OPEN_NOT_CLEAN_EMPTY")
        target = self._path(segment_id, "abandoned")
        target_metadata = self.root / f"{segment_id}.abandoned.json"
        if target.exists() or target_metadata.exists():
            raise OnlyWalError("WAL_ABANDONED_IDENTITY_CONFLICT")
        os.replace(source, target)
        os.replace(metadata, target_metadata)
        self._fsync_directory()
        return target

    def scan_open(self) -> tuple[str, ...]:
        return tuple(sorted(path.name.removesuffix(".open.wal") for path in self.root.glob("*.open.wal")))

    def scan_uncommitted(self) -> tuple[str, ...]:
        return tuple(sorted(path.name.removesuffix(".sealed.wal") for path in self.root.glob("*.sealed.wal")))

    def mark_gc_eligible(self, segment_id: str) -> Path:
        source = self._path(segment_id, "sealed")
        target = self._path(segment_id, "gc")
        if target.exists() or (self.root / f"{segment_id}.gc.json").exists():
            raise OnlyWalError("WAL_GC_IDENTITY_CONFLICT")
        os.replace(source, target)
        metadata = self.root / f"{segment_id}.segment.json"
        if metadata.exists():
            os.replace(metadata, self.root / f"{segment_id}.gc.json")
        self._fsync_directory()
        if self.bytes_used < self.capacity_bytes and self._last_error == "WAL_CAPACITY_FULL":
            self._recording_state = OnlyRecordingState.HEALTHY
            self._last_error = None
        return target

    def health(
        self,
        *,
        writer_queue_depth: int = 0,
        last_verified_segment: str | None = None,
        last_committed_segment: str | None = None,
        recovery_count: int = 0,
        last_recovery_error: str | None = None,
    ) -> OnlyMarketDataHealth:
        sealed = self.scan_uncommitted()
        created_at: list[datetime] = []
        for segment_id in sealed:
            try:
                created_at.append(self.load_segment(segment_id).created_at)
            except (OSError, ValueError, OnlyWalError) as exc:
                self._recording_state = OnlyRecordingState.FAILED
                self._last_error = type(exc).__name__
        oldest = None if not created_at else self._now() - min(created_at)
        return OnlyMarketDataHealth(
            self.recording_state,
            self.bytes_used,
            self.capacity_bytes,
            len(self.scan_open()),
            len(sealed),
            oldest,
            writer_queue_depth,
            last_verified_segment,
            last_committed_segment,
            recovery_count,
            last_recovery_error or self._last_error,
        )

    def _read_frames(self, path: Path, *, sealed: bool) -> Iterator[tuple[int, bytes]]:
        data = path.read_bytes()
        offset = 0
        expected_ordinal = 0
        while offset < len(data):
            if len(data) - offset < _HEADER.size:
                raise OnlyWalCorruptionError(f"WAL_{'SEALED_' if sealed else ''}TORN_HEADER")
            magic, version, length, ordinal, checksum = _HEADER.unpack_from(data, offset)
            if magic != _MAGIC or version != _VERSION or ordinal != expected_ordinal:
                raise OnlyWalCorruptionError("WAL_FRAME_HEADER_INVALID")
            start = offset + _HEADER.size
            end = start + length
            if end > len(data):
                raise OnlyWalCorruptionError(f"WAL_{'SEALED_' if sealed else ''}TORN_PAYLOAD")
            payload = data[start:end]
            if hashlib.sha256(payload).digest() != checksum:
                raise OnlyWalCorruptionError("WAL_FRAME_CHECKSUM_MISMATCH")
            yield end, payload
            offset = end
            expected_ordinal += 1

    def _path(self, segment_id: str, state: str) -> Path:
        if not _SEGMENT_ID.fullmatch(segment_id):
            raise ValueError("WAL_SEGMENT_ID_INVALID")
        return self.root / f"{segment_id}.{state}.wal"

    def _fsync_directory(self) -> None:
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        with path.open("xb", buffering=0) as stream:
            stream.write(encoded)
            os.fsync(stream.fileno())


__all__ = [name for name in globals() if name.startswith("Only")]
