"""Provider-neutral immutable contracts for durable market-data evidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.domain.time import only_require_utc


class OnlyMarketDataProvenance(StrEnum):
    REALTIME_STREAM = "REALTIME_STREAM"
    REST_BACKFILL = "REST_BACKFILL"
    REPAIR = "REPAIR"
    REPLAY = "REPLAY"


class OnlyMarketDataQualityState(StrEnum):
    VALID = "VALID"
    CONFLICT = "CONFLICT"
    CORRUPT = "CORRUPT"


class OnlySegmentState(StrEnum):
    ABSENT = "ABSENT"
    OPEN = "OPEN"
    SEALED = "SEALED"
    GC_ELIGIBLE = "GC_ELIGIBLE"
    DELETED = "DELETED"


class OnlyRecordingState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class OnlyCoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNPROVABLE = "UNPROVABLE"


@dataclass(frozen=True, slots=True)
class OnlyBarCoverageGap:
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        if self.start_ns >= self.end_ns:
            raise ValueError("BAR_COVERAGE_GAP_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyTradeCoverageGap:
    first_sequence: int
    last_sequence: int

    def __post_init__(self) -> None:
        if self.first_sequence > self.last_sequence:
            raise ValueError("TRADE_COVERAGE_GAP_INVALID")


type OnlyCoverageGap = OnlyBarCoverageGap | OnlyTradeCoverageGap


@dataclass(frozen=True, slots=True)
class OnlyRawProviderEvidence:
    raw_event_id: str
    source_id: str
    capture_session_id: str
    provider: str
    venue: str
    market: str
    stream: str
    provider_event_type: str
    provider_event_id: str | None
    provider_sequence: int | None
    ts_event_ns: int | None
    ts_receive_ns: int
    payload_codec: str
    provider_schema: str
    payload: bytes
    raw_sha256: str
    provenance: OnlyMarketDataProvenance

    def __post_init__(self) -> None:
        if hashlib.sha256(self.payload).hexdigest() != self.raw_sha256:
            raise ValueError("RAW_EVIDENCE_HASH_MISMATCH")
        if not all(
            value.strip()
            for value in (
                self.raw_event_id,
                self.source_id,
                self.capture_session_id,
                self.provider,
                self.venue,
                self.market,
                self.stream,
                self.provider_event_type,
                self.payload_codec,
                self.provider_schema,
            )
        ):
            raise ValueError("RAW_EVIDENCE_IDENTITY_INVALID")

    @classmethod
    def capture(
        cls,
        *,
        source_id: str,
        capture_session_id: str,
        provider: str,
        venue: str,
        market: str,
        stream: str,
        provider_event_type: str,
        ts_receive_ns: int,
        payload: bytes,
        provenance: OnlyMarketDataProvenance,
        provider_event_id: str | None = None,
        provider_sequence: int | None = None,
        ts_event_ns: int | None = None,
        payload_codec: str = "application/json",
        provider_schema: str = "v1",
    ) -> OnlyRawProviderEvidence:
        raw_hash = hashlib.sha256(payload).hexdigest()
        identity = only_canonical_fingerprint(
            {
                "source_id": source_id,
                "capture_session_id": capture_session_id,
                "stream": stream,
                "provider_event_type": provider_event_type,
                "provider_event_id": provider_event_id,
                "provider_sequence": provider_sequence,
                "ts_event_ns": ts_event_ns,
                "ts_receive_ns": ts_receive_ns,
                "raw_sha256": raw_hash,
            }
        )
        return cls(
            f"raw-event:{identity}",
            source_id,
            capture_session_id,
            provider,
            venue,
            market,
            stream,
            provider_event_type,
            provider_event_id,
            provider_sequence,
            ts_event_ns,
            ts_receive_ns,
            payload_codec,
            provider_schema,
            payload,
            raw_hash,
            provenance,
        )


@dataclass(frozen=True, slots=True)
class OnlyCanonicalMarketFactRecord:
    canonical_fact_id: str
    raw_event_id: str
    source_id: str
    segment_id: str
    capture_session_id: str
    data_kind: str
    instrument_id: str
    ts_event_ns: int
    ts_receive_ns: int
    ts_ingest_ns: int
    canonical_payload: dict[str, object]
    canonical_payload_hash: str
    normalizer_id: str
    normalizer_version: str
    quality_state: OnlyMarketDataQualityState
    provenance: OnlyMarketDataProvenance

    def __post_init__(self) -> None:
        if only_canonical_fingerprint(self.canonical_payload) != self.canonical_payload_hash:
            raise ValueError("CANONICAL_PAYLOAD_HASH_MISMATCH")
        if not all(
            value.strip()
            for value in (
                self.canonical_fact_id,
                self.raw_event_id,
                self.source_id,
                self.segment_id,
                self.capture_session_id,
                self.data_kind,
                self.instrument_id,
                self.normalizer_id,
                self.normalizer_version,
            )
        ):
            raise ValueError("CANONICAL_FACT_IDENTITY_INVALID")

    @classmethod
    def bind(
        cls,
        update: OnlyMarketDataInboundUpdate,
        evidence: OnlyRawProviderEvidence,
        *,
        segment_id: str,
        ts_ingest_ns: int,
        normalizer_id: str,
        normalizer_version: str,
    ) -> OnlyCanonicalMarketFactRecord:
        payload = update.to_dict()
        return cls(
            str(update.update_id),
            evidence.raw_event_id,
            str(update.source_id),
            segment_id,
            evidence.capture_session_id,
            update.data_type.value,
            str(update.instrument_id),
            update.ts_event.unix_nanos,
            evidence.ts_receive_ns,
            ts_ingest_ns,
            payload,
            only_canonical_fingerprint(payload),
            normalizer_id,
            normalizer_version,
            OnlyMarketDataQualityState.VALID,
            evidence.provenance,
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketDataRecordBundle:
    evidence: OnlyRawProviderEvidence
    canonical_facts: tuple[OnlyCanonicalMarketFactRecord, ...] = ()

    def __post_init__(self) -> None:
        if any(item.raw_event_id != self.evidence.raw_event_id for item in self.canonical_facts):
            raise ValueError("CANONICAL_RAW_LINKAGE_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyIngestSegment:
    segment_id: str
    capture_session_id: str
    source_id: str
    market: str
    stream: str
    provider: str
    venue: str
    capture_mode: OnlyMarketDataProvenance
    provider_schema: str
    codec: str
    schema_version: int
    record_count: int
    raw_count: int
    canonical_count: int
    content_hash: str
    created_at: datetime
    sealed_at: datetime
    instrument_id: str | None = None
    data_kind: str | None = None
    start_ns: int | None = None
    end_ns: int | None = None
    data_version: str | None = None
    bar_type: str | None = None
    first_sequence: int | None = None
    last_sequence: int | None = None

    def __post_init__(self) -> None:
        only_require_utc(self.created_at, "segment created_at")
        only_require_utc(self.sealed_at, "segment sealed_at")
        if (
            self.sealed_at < self.created_at
            or self.schema_version != 1
            or self.record_count <= 0
            or self.raw_count != self.record_count
            or self.canonical_count < 0
            or not re.fullmatch(r"[0-9a-f]{64}", self.content_hash)
            or not all(
                value.strip()
                for value in (
                    self.segment_id,
                    self.capture_session_id,
                    self.source_id,
                    self.market,
                    self.stream,
                    self.provider,
                    self.venue,
                    self.provider_schema,
                    self.codec,
                )
            )
        ):
            raise ValueError("SEGMENT_METADATA_INVALID")
        scope_values = (self.instrument_id, self.data_kind, self.start_ns, self.end_ns, self.data_version)
        if self.canonical_count > 0 and any(value is None for value in scope_values):
            raise ValueError("SEGMENT_RECOVERY_SCOPE_MISSING")
        if any(value is not None for value in scope_values) and any(value is None for value in scope_values):
            raise ValueError("SEGMENT_RECOVERY_SCOPE_PARTIAL")
        if self.start_ns is not None and self.end_ns is not None and self.start_ns >= self.end_ns:
            raise ValueError("SEGMENT_RECOVERY_RANGE_INVALID")
        if (self.first_sequence is None) != (self.last_sequence is None):
            raise ValueError("SEGMENT_RECOVERY_SEQUENCE_PARTIAL")
        if (
            self.first_sequence is not None
            and self.last_sequence is not None
            and self.first_sequence > self.last_sequence
        ):
            raise ValueError("SEGMENT_RECOVERY_SEQUENCE_INVALID")

    def recovery_scope(self) -> OnlyMarketDataScope:
        if (
            self.instrument_id is None
            or self.data_kind is None
            or self.start_ns is None
            or self.end_ns is None
            or self.data_version is None
        ):
            raise ValueError(f"SEGMENT_RECOVERY_SCOPE_UNPROVABLE:{self.segment_id}")
        return OnlyMarketDataScope(
            self.source_id,
            self.market,
            self.instrument_id,
            self.data_kind,
            self.start_ns,
            self.end_ns,
            self.data_version,
            self.bar_type,
            self.first_sequence,
            self.last_sequence,
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketDataScope:
    source_id: str
    market: str
    instrument_id: str
    data_kind: str
    start_ns: int
    end_ns: int
    data_version: str
    bar_type: str | None = None
    first_sequence: int | None = None
    last_sequence: int | None = None

    def __post_init__(self) -> None:
        if self.start_ns >= self.end_ns:
            raise ValueError("MARKET_DATA_SCOPE_INVALID")
        if (self.first_sequence is None) != (self.last_sequence is None):
            raise ValueError("MARKET_DATA_SEQUENCE_SCOPE_INCOMPLETE")
        if (
            self.first_sequence is not None
            and self.last_sequence is not None
            and self.first_sequence > self.last_sequence
        ):
            raise ValueError("MARKET_DATA_SEQUENCE_SCOPE_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyMarketDataAcquisitionIntent:
    acquisition_id: str
    request_fingerprint: str
    source_id: str
    requested_scope: OnlyMarketDataScope
    provenance: OnlyMarketDataProvenance
    created_at: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.created_at, "acquisition created_at")
        expected = only_canonical_fingerprint(
            {
                "source_id": self.source_id,
                "requested_scope": self.requested_scope,
                "provenance": self.provenance.value,
            }
        )
        if self.request_fingerprint != expected or self.acquisition_id != f"acquisition:{expected}":
            raise ValueError("ACQUISITION_INTENT_IDENTITY_INVALID")

    @classmethod
    def build(
        cls,
        source_id: str,
        requested_scope: OnlyMarketDataScope,
        *,
        provenance: OnlyMarketDataProvenance,
        created_at: datetime,
    ) -> OnlyMarketDataAcquisitionIntent:
        fingerprint = only_canonical_fingerprint(
            {
                "source_id": source_id,
                "requested_scope": requested_scope,
                "provenance": provenance.value,
            }
        )
        return cls(f"acquisition:{fingerprint}", fingerprint, source_id, requested_scope, provenance, created_at)


@dataclass(frozen=True, slots=True)
class OnlyCoverageManifest:
    manifest_id: str
    scope: OnlyMarketDataScope
    segment_refs: tuple[tuple[str, str], ...]
    coverage_status: OnlyCoverageStatus
    proof: tuple[str, ...]
    issues: tuple[str, ...]
    gaps: tuple[OnlyCoverageGap, ...]
    fingerprint: str

    @classmethod
    def build(
        cls,
        scope: OnlyMarketDataScope,
        segment_refs: tuple[tuple[str, str], ...],
        *,
        coverage_status: OnlyCoverageStatus,
        proof: tuple[str, ...],
        issues: tuple[str, ...] = (),
        gaps: tuple[OnlyCoverageGap, ...] = (),
    ) -> OnlyCoverageManifest:
        ordered = tuple(sorted(segment_refs))
        fingerprint = only_canonical_fingerprint(
            {
                "scope": scope,
                "segments": ordered,
                "coverage_status": coverage_status.value,
                "proof": proof,
                "issues": issues,
                "gaps": gaps,
            }
        )
        return cls(f"manifest:{fingerprint}", scope, ordered, coverage_status, proof, issues, gaps, fingerprint)

    @property
    def complete(self) -> bool:
        """Compatibility projection; coverage_status remains the sole authority."""
        return self.coverage_status is OnlyCoverageStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class OnlyMarketDataRevision:
    revision_id: str
    scope: OnlyMarketDataScope
    manifest_id: str
    segment_refs: tuple[tuple[str, str], ...]
    normalizers: tuple[tuple[str, str], ...]
    parent_revision_id: str | None
    creation_reason: str
    fingerprint: str

    @classmethod
    def build(
        cls,
        manifest: OnlyCoverageManifest,
        *,
        normalizers: tuple[tuple[str, str], ...],
        creation_reason: str,
        parent_revision_id: str | None = None,
    ) -> OnlyMarketDataRevision:
        ordered_normalizers = tuple(sorted(normalizers))
        fingerprint = only_canonical_fingerprint(
            {
                "scope": manifest.scope,
                "manifest": manifest.fingerprint,
                "segments": manifest.segment_refs,
                "normalizers": ordered_normalizers,
                "parent": parent_revision_id,
                "reason": creation_reason,
            }
        )
        return cls(
            f"market-data-revision:{fingerprint}",
            manifest.scope,
            manifest.manifest_id,
            manifest.segment_refs,
            ordered_normalizers,
            parent_revision_id,
            creation_reason,
            fingerprint,
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSeal:
    seal_id: str
    revision_id: str
    revision_fingerprint: str
    checks: tuple[str, ...]
    sealed_at: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.sealed_at, "revision sealed_at")
        if not self.checks:
            raise ValueError("REVISION_SEAL_CHECKS_MISSING")


@dataclass(frozen=True, slots=True)
class OnlyMarketDataHealth:
    recording_state: OnlyRecordingState
    wal_bytes_used: int
    wal_capacity: int
    open_segments: int
    sealed_uncommitted_segments: int
    oldest_uncommitted_age: timedelta | None
    writer_queue_depth: int
    last_verified_segment: str | None
    last_committed_segment: str | None
    recovery_count: int
    last_recovery_error: str | None
    coverage_revision_lag: int | None = None
    clickhouse_write_latency_seconds: float | None = None
    postgres_commit_latency_seconds: float | None = None
    postgres_commit_errors: int = 0
