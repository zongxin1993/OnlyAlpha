"""Finite checksummed filesystem WAL segments with explicit durability."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import only_system_utc_now

from .codec import only_decode_record_bundle, only_encode_record_bundle
from .models import (
    OnlyCanonicalMarketFactRecord,
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


class _OnlyRecoveryMetadata(TypedDict, total=False):
    instrument_id: str
    data_kind: str
    start_ns: int
    end_ns: int
    data_version: str
    bar_type: str | None
    first_sequence: int | None
    last_sequence: int | None


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
        now: Callable[[], datetime] = only_system_utc_now,
        identity_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        barrier: Callable[[str], None] | None = None,
    ) -> None:
        if capacity_bytes <= _HEADER.size:
            raise ValueError("WAL_CAPACITY_INVALID")
        self.root = root
        self.capacity_bytes = capacity_bytes
        self._now = now
        self._identity_factory = identity_factory
        self._barrier = barrier or (lambda _stage: None)
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
        prepared = self.root / f"{selected}.open.json.tmp"
        self._write_json(
            prepared,
            {"schema_version": 1, "segment_id": selected, "created_at": created_at.isoformat()},
        )
        self._barrier("W1_METADATA_PREPARED")
        with self._path(selected, "open").open("xb", buffering=0) as stream:
            os.fsync(stream.fileno())
        self._barrier("W2_WAL_CREATED")
        os.replace(prepared, self.root / f"{selected}.open.json")
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
            self._barrier("W4_FRAME_WRITTEN_BEFORE_FSYNC")
            os.fsync(stream.fileno())
        self._barrier("W5_FRAME_DURABLE")
        return ordinal

    def seal(self, *, sealed_at: datetime | None = None) -> OnlyIngestSegment:
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
        effective_sealed_at = sealed_at or self._now()
        result = self._build_segment(segment_id, bundles, self._created_at, effective_sealed_at, source)
        prepared = self.root / f"{segment_id}.segment.json.tmp"
        prepared.unlink(missing_ok=True)
        self._write_json(
            prepared,
            self._segment_metadata(result),
        )
        self._barrier("W6_SEAL_METADATA_PREPARED")
        target = self._path(segment_id, "sealed")
        os.replace(source, target)
        self._fsync_directory()
        self._barrier("W7_WAL_RENAMED_BEFORE_METADATA")
        os.replace(prepared, self.root / f"{segment_id}.segment.json")
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
        recovery: _OnlyRecoveryMetadata = {}
        if int(str(raw["canonical_count"])) > 0 and raw.get("instrument_id") is None:
            records = tuple(
                only_decode_record_bundle(payload)
                for _, payload in self._read_frames(self._path(segment_id, "sealed"), sealed=True)
            )
            recovery = self._recovery_metadata(tuple(fact for bundle in records for fact in bundle.canonical_facts))
        result = self._segment_from_metadata(raw, recovery)
        if not self.verify_sealed(result):
            raise OnlyWalCorruptionError("WAL_SEGMENT_METADATA_HASH_MISMATCH")
        return result

    @staticmethod
    def _segment_from_metadata(
        raw: Mapping[str, object], recovery: _OnlyRecoveryMetadata | None = None
    ) -> OnlyIngestSegment:
        fallback = recovery or {}
        return OnlyIngestSegment(
            segment_id=str(raw["segment_id"]),
            capture_session_id=str(raw["capture_session_id"]),
            source_id=str(raw["source_id"]),
            market=str(raw["market"]),
            stream=str(raw["stream"]),
            provider=str(raw["provider"]),
            venue=str(raw["venue"]),
            capture_mode=OnlyMarketDataProvenance(str(raw["capture_mode"])),
            provider_schema=str(raw["provider_schema"]),
            codec=str(raw["codec"]),
            schema_version=1,
            record_count=int(str(raw["record_count"])),
            raw_count=int(str(raw["raw_count"])),
            canonical_count=int(str(raw["canonical_count"])),
            content_hash=str(raw["content_hash"]),
            created_at=datetime.fromisoformat(str(raw["created_at"])),
            sealed_at=datetime.fromisoformat(str(raw["sealed_at"])),
            instrument_id=_optional_str(raw.get("instrument_id", fallback.get("instrument_id"))),
            data_kind=_optional_str(raw.get("data_kind", fallback.get("data_kind"))),
            start_ns=_optional_int(raw.get("start_ns", fallback.get("start_ns"))),
            end_ns=_optional_int(raw.get("end_ns", fallback.get("end_ns"))),
            data_version=_optional_str(raw.get("data_version", fallback.get("data_version"))),
            bar_type=_optional_str(raw.get("bar_type", fallback.get("bar_type"))),
            first_sequence=_optional_int(raw.get("first_sequence", fallback.get("first_sequence"))),
            last_sequence=_optional_int(raw.get("last_sequence", fallback.get("last_sequence"))),
        )

    def _recover_sealed_metadata(self, segment_id: str) -> None:
        sealed = self._path(segment_id, "sealed")
        open_metadata_path = self.root / f"{segment_id}.open.json"
        if self._publish_prepared_segment(segment_id, sealed):
            return
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
        segment = self._build_segment(
            segment_id,
            bundles,
            datetime.fromisoformat(str(open_metadata["created_at"])),
            datetime.fromisoformat(str(open_metadata["created_at"])),
            sealed,
        )
        prepared = self.root / f"{segment_id}.segment.json.tmp"
        if prepared.exists():
            prepared.unlink()
        self._write_json(prepared, self._segment_metadata(segment))
        os.replace(prepared, self.root / f"{segment_id}.segment.json")
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
        source = self._path(segment_id, "open")
        if self._publish_prepared_segment(segment_id, source):
            return self.load_segment(segment_id)
        self._open_id = segment_id
        self._created_at = datetime.fromisoformat(str(metadata["created_at"]))
        return self.seal(sealed_at=self._created_at)

    def abandon_empty_open(self, segment_id: str) -> Path:
        source = self._path(segment_id, "open")
        metadata = self.root / f"{segment_id}.open.json"
        prepared = self.root / f"{segment_id}.open.json.tmp"
        if not source.exists() or source.stat().st_size != 0:
            raise OnlyWalCorruptionError("WAL_OPEN_NOT_CLEAN_EMPTY")
        target = self._path(segment_id, "abandoned")
        target_metadata = self.root / f"{segment_id}.abandoned.json"
        if target.exists() or target_metadata.exists():
            raise OnlyWalError("WAL_ABANDONED_IDENTITY_CONFLICT")
        os.replace(source, target)
        if metadata.exists():
            os.replace(metadata, target_metadata)
        elif prepared.exists():
            os.replace(prepared, target_metadata)
        else:
            self._write_json(
                target_metadata,
                {"schema_version": 1, "segment_id": segment_id, "reason": "CREATION_ORPHAN"},
            )
        self._fsync_directory()
        return target

    def scan_open(self) -> tuple[str, ...]:
        return tuple(sorted(path.name.removesuffix(".open.wal") for path in self.root.glob("*.open.wal")))

    def scan_uncommitted(self) -> tuple[str, ...]:
        return tuple(sorted(path.name.removesuffix(".sealed.wal") for path in self.root.glob("*.sealed.wal")))

    def scan_gc_eligible(self) -> tuple[str, ...]:
        identities = {path.name.removesuffix(".gc.wal") for path in self.root.glob("*.gc.wal")} | {
            path.name.removesuffix(".gc.json") for path in self.root.glob("*.gc.json")
        }
        return tuple(sorted(identities))

    def resolve_creation_orphans(self) -> None:
        for prepared in sorted(self.root.glob("*.open.json.tmp")):
            segment_id = prepared.name.removesuffix(".open.json.tmp")
            open_wal = self._path(segment_id, "open")
            published = self.root / f"{segment_id}.open.json"
            if published.exists():
                prepared.unlink()
            elif not open_wal.exists():
                prepared.unlink()
            elif open_wal.stat().st_size == 0:
                self.abandon_empty_open(segment_id)
            else:
                raise OnlyWalCorruptionError(f"WAL_OPEN_METADATA_MISSING:{segment_id}")
        self._fsync_directory()

    def assert_no_metadata_orphans(self) -> None:
        for metadata in sorted(self.root.glob("*.open.json")):
            segment_id = metadata.name.removesuffix(".open.json")
            if not self._path(segment_id, "open").exists() and not self._path(segment_id, "sealed").exists():
                raise OnlyWalCorruptionError(f"WAL_STATE_CORRUPT:OPEN_METADATA_ONLY:{segment_id}")
        for metadata in sorted(self.root.glob("*.segment.json")):
            segment_id = metadata.name.removesuffix(".segment.json")
            if not self._path(segment_id, "sealed").exists():
                raise OnlyWalCorruptionError(f"WAL_STATE_CORRUPT:SEGMENT_METADATA_ONLY:{segment_id}")

    def mark_gc_eligible(self, segment_id: str) -> Path:
        source = self._path(segment_id, "sealed")
        target = self._path(segment_id, "gc")
        metadata = self.root / f"{segment_id}.segment.json"
        marker = self.root / f"{segment_id}.gc.json"
        if target.exists() and marker.exists() and not source.exists() and not metadata.exists():
            return target
        if target.exists() and not marker.exists():
            raise OnlyWalCorruptionError("WAL_GC_MARKER_MISSING")
        if not marker.exists():
            if not metadata.exists():
                raise OnlyWalCorruptionError("WAL_SEGMENT_METADATA_MISSING")
            loaded = self.load_segment(segment_id)
            self._write_json(
                marker,
                {
                    "schema_version": 1,
                    "segment_id": segment_id,
                    "content_hash": loaded.content_hash,
                },
            )
            self._fsync_directory()
        self._barrier("W9_GC_MARKED_BEFORE_WAL_MOVE")
        if source.exists():
            os.replace(source, target)
        elif not target.exists():
            raise OnlyWalCorruptionError("WAL_GC_CONTENT_MISSING")
        metadata.unlink(missing_ok=True)
        self._fsync_directory()
        if self.bytes_used < self.capacity_bytes and self._last_error == "WAL_CAPACITY_FULL":
            self._recording_state = OnlyRecordingState.HEALTHY
            self._last_error = None
        return target

    def collect_garbage(self, segment_id: str) -> None:
        content = self._path(segment_id, "gc")
        marker = self.root / f"{segment_id}.gc.json"
        if content.exists() and not marker.exists():
            raise OnlyWalCorruptionError("WAL_GC_MARKER_MISSING")
        if content.exists():
            content.unlink()
            self._fsync_directory()
        self._barrier("W10_GC_WAL_DELETED_BEFORE_METADATA")
        if marker.exists():
            marker.unlink()
            self._fsync_directory()
        (self.root / f"{segment_id}.segment.json").unlink(missing_ok=True)
        self._fsync_directory()

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

    def _publish_prepared_segment(self, segment_id: str, wal_path: Path) -> bool:
        prepared = self.root / f"{segment_id}.segment.json.tmp"
        if not prepared.exists():
            return False
        raw = json.loads(prepared.read_text())
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != 1
            or raw.get("segment_id") != segment_id
            or not wal_path.exists()
        ):
            raise OnlyWalCorruptionError("WAL_PREPARED_SEGMENT_METADATA_INVALID")
        segment = self._segment_from_metadata(raw)
        records = tuple(self._read_frames(wal_path, sealed=True))
        if (
            len(records) != segment.record_count
            or hashlib.sha256(wal_path.read_bytes()).hexdigest() != segment.content_hash
        ):
            raise OnlyWalCorruptionError("WAL_PREPARED_SEGMENT_METADATA_HASH_MISMATCH")
        sealed = self._path(segment_id, "sealed")
        if wal_path != sealed:
            os.replace(wal_path, sealed)
            self._fsync_directory()
        os.replace(prepared, self.root / f"{segment_id}.segment.json")
        (self.root / f"{segment_id}.open.json").unlink(missing_ok=True)
        self._fsync_directory()
        return True

    def _build_segment(
        self,
        segment_id: str,
        bundles: tuple[OnlyMarketDataRecordBundle, ...],
        created_at: datetime,
        sealed_at: datetime,
        wal_path: Path,
    ) -> OnlyIngestSegment:
        evidence = bundles[0].evidence
        facts = tuple(fact for bundle in bundles for fact in bundle.canonical_facts)
        recovery = self._recovery_metadata(facts)
        return OnlyIngestSegment(
            segment_id=segment_id,
            capture_session_id=evidence.capture_session_id,
            source_id=evidence.source_id,
            market=evidence.market,
            stream=evidence.stream,
            provider=evidence.provider,
            venue=evidence.venue,
            capture_mode=evidence.provenance,
            provider_schema=evidence.provider_schema,
            codec=evidence.payload_codec,
            schema_version=1,
            record_count=len(bundles),
            raw_count=len(bundles),
            canonical_count=len(facts),
            content_hash=hashlib.sha256(wal_path.read_bytes()).hexdigest(),
            created_at=created_at,
            sealed_at=sealed_at,
            **recovery,
        )

    @staticmethod
    def _recovery_metadata(facts: tuple[OnlyCanonicalMarketFactRecord, ...]) -> _OnlyRecoveryMetadata:
        if not facts:
            return {}
        identities = {
            (
                fact.source_id,
                fact.instrument_id,
                fact.data_kind,
                str(fact.canonical_payload.get("data_version", "")),
                fact.provenance,
            )
            for fact in facts
        }
        if len(identities) != 1:
            raise OnlyWalError("WAL_SEGMENT_SEMANTIC_SCOPE_CONFLICT")
        _, instrument_id, data_kind, data_version, _ = next(iter(identities))
        if not data_version:
            raise OnlyWalError("WAL_SEGMENT_DATA_VERSION_MISSING")
        event_times = tuple(int(fact.ts_event_ns) for fact in facts)
        start_ns = min(event_times)
        end_ns = max(event_times) + 1
        bar_type = None
        if data_kind == "BAR":
            values = tuple(fact.canonical_payload.get("payload") for fact in facts)
            bar_values = tuple(
                cast(Mapping[str, object], value.get("value"))
                for value in values
                if isinstance(value, Mapping) and isinstance(value.get("value"), Mapping)
            )
            if len(bar_values) != len(facts):
                raise OnlyWalError("WAL_SEGMENT_BAR_SCOPE_INVALID")
            starts = tuple(_iso_ns(value["bar_start"]) for value in bar_values)
            ends = tuple(_iso_ns(value["bar_end"]) for value in bar_values)
            bar_types = {only_canonical_fingerprint(value["bar_type"]) for value in bar_values}
            if len(bar_types) != 1:
                raise OnlyWalError("WAL_SEGMENT_BAR_TYPE_CONFLICT")
            start_ns = min(starts)
            end_ns = max(ends)
            bar_type = next(iter(bar_types))
        sequences = tuple(
            int(str(fact.canonical_payload["source_sequence"]))
            for fact in facts
            if fact.canonical_payload.get("sequence_semantics") == "CONTIGUOUS"
            and fact.canonical_payload.get("source_sequence") is not None
        )
        return {
            "instrument_id": instrument_id,
            "data_kind": data_kind,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "data_version": data_version,
            "bar_type": bar_type,
            "first_sequence": min(sequences) if sequences and data_kind == "TRADE" else None,
            "last_sequence": max(sequences) if sequences and data_kind == "TRADE" else None,
        }

    @staticmethod
    def _segment_metadata(segment: OnlyIngestSegment) -> dict[str, object]:
        return {
            "schema_version": 1,
            "segment_id": segment.segment_id,
            "capture_session_id": segment.capture_session_id,
            "source_id": segment.source_id,
            "market": segment.market,
            "stream": segment.stream,
            "provider": segment.provider,
            "venue": segment.venue,
            "capture_mode": segment.capture_mode.value,
            "provider_schema": segment.provider_schema,
            "codec": segment.codec,
            "record_count": segment.record_count,
            "raw_count": segment.raw_count,
            "canonical_count": segment.canonical_count,
            "content_hash": segment.content_hash,
            "created_at": segment.created_at.isoformat(),
            "sealed_at": segment.sealed_at.isoformat(),
            "instrument_id": segment.instrument_id,
            "data_kind": segment.data_kind,
            "start_ns": segment.start_ns,
            "end_ns": segment.end_ns,
            "data_version": segment.data_version,
            "bar_type": segment.bar_type,
            "first_sequence": segment.first_sequence,
            "last_sequence": segment.last_sequence,
        }

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


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _iso_ns(value: object) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


__all__ = [name for name in globals() if name.startswith("Only")]
