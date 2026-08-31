"""Coverage, immutable revision construction and exact historical reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation

from .models import (
    OnlyBarCoverageGap,
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyIngestSegment,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
    OnlyTradeCoverageGap,
)
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore

_REQUIRED_SEAL_CHECKS = (
    "SEGMENT_HASH_VERIFIED",
    "SCHEMA_COMPATIBLE",
    "CANONICAL_IDENTITY_UNIQUE",
    "REQUESTED_SCOPE_VERIFIED",
    "COVERAGE_COMPLETE",
    "NO_UNRESOLVED_CORRUPTION",
)


class OnlyMarketDataConflictError(RuntimeError):
    pass


class OnlyMarketDataSealError(RuntimeError):
    pass


def only_verify_canonical_uniqueness(facts: tuple[OnlyCanonicalMarketFactRecord, ...]) -> None:
    hashes: dict[str, str] = {}
    for fact in facts:
        if only_canonical_fingerprint(fact.canonical_payload) != fact.canonical_payload_hash:
            raise OnlyMarketDataConflictError(f"CANONICAL_FACT_HASH_MISMATCH:{fact.canonical_fact_id}")
        prior = hashes.setdefault(fact.canonical_fact_id, fact.canonical_payload_hash)
        if prior != fact.canonical_payload_hash:
            raise OnlyMarketDataConflictError(f"CANONICAL_FACT_CONFLICT:{fact.canonical_fact_id}")


def only_deduplicate_facts(
    facts: tuple[OnlyCanonicalMarketFactRecord, ...],
) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
    only_verify_canonical_uniqueness(facts)
    selected: dict[str, OnlyCanonicalMarketFactRecord] = {}
    for fact in sorted(facts, key=lambda item: (item.canonical_fact_id, item.raw_event_id)):
        selected.setdefault(fact.canonical_fact_id, fact)
    return tuple(sorted(selected.values(), key=lambda item: (item.ts_event_ns, item.canonical_fact_id)))


def only_build_coverage(
    scope: OnlyMarketDataScope,
    segments: tuple[OnlyIngestSegment, ...],
    facts: tuple[OnlyCanonicalMarketFactRecord, ...],
) -> OnlyCoverageManifest:
    segment_ids = {item.segment_id for item in segments}
    for segment in segments:
        if (
            segment.source_id != scope.source_id
            or segment.market != scope.market
            or segment.instrument_id != scope.instrument_id
            or segment.data_kind != scope.data_kind
            or segment.data_version != scope.data_version
            or segment.bar_type != scope.bar_type
        ):
            raise OnlyMarketDataConflictError(f"SEGMENT_SCOPE_MISMATCH:{segment.segment_id}")
    if any(item.segment_id not in segment_ids for item in facts):
        raise OnlyMarketDataConflictError("COVERAGE_FACT_OUTSIDE_SEGMENT_SET")
    in_scope = tuple(
        item
        for item in only_deduplicate_facts(facts)
        if item.source_id == scope.source_id
        and item.instrument_id == scope.instrument_id
        and item.data_kind == scope.data_kind
        and scope.start_ns <= item.ts_event_ns <= scope.end_ns
    )
    issues: list[str] = []
    proof: list[str] = [f"canonical_fact_count={len(in_scope)}"]
    if scope.data_kind == "BAR":
        minute = 60_000_000_000
        expected = tuple(range(scope.start_ns + minute, scope.end_ns + 1, minute))
        actual = tuple(item.ts_event_ns for item in in_scope)
        bars = tuple(OnlyMarketDataInboundUpdate.from_dict(item.canonical_payload).payload for item in in_scope)
        semantic_valid = all(
            isinstance(item, OnlyBarUpdate)
            and item.bar.is_closed
            and item.bar.ts_event == item.bar.bar_end
            and int((item.bar.bar_end - item.bar.bar_start).total_seconds()) == 60
            and item.bar.bar_type.specification.step == 1
            and item.bar.bar_type.specification.aggregation is OnlyBarAggregation.TIME
            and item.bar.bar_type.aggregation_source is OnlyAggregationSource.EXTERNAL
            for item in bars
        )
        status = OnlyCoverageStatus.COMPLETE if actual == expected and semantic_valid else OnlyCoverageStatus.INCOMPLETE
        proof.append(f"bar_grid_count={len(expected)}")
        proof.append(f"closed_external_1m={str(semantic_valid).lower()}")
        if actual != expected:
            issues.append("BAR_GRID_INCOMPLETE")
        if not semantic_valid:
            issues.append("BAR_SEMANTICS_INVALID")
    elif scope.data_kind == "TRADE":
        continuity_proven = bool(in_scope) and all(
            item.canonical_payload.get("sequence_semantics") == "CONTIGUOUS"
            and item.canonical_payload.get("source_sequence") is not None
            for item in in_scope
        )
        sequences = tuple(
            sorted(
                int(str(item.canonical_payload["source_sequence"]))
                for item in in_scope
                if item.canonical_payload.get("source_sequence") is not None
            )
        )
        expected = (
            ()
            if scope.first_sequence is None or scope.last_sequence is None
            else tuple(range(scope.first_sequence, scope.last_sequence + 1))
        )
        status = (
            OnlyCoverageStatus.COMPLETE
            if continuity_proven and bool(expected) and sequences == expected
            else OnlyCoverageStatus.INCOMPLETE
        )
        proof.append(f"provider_sequence_contiguous={str(continuity_proven).lower()}")
        proof.append(
            f"provider_identity_range={sequences[0] if sequences else 'none'}:{sequences[-1] if sequences else 'none'}"
        )
        if status is not OnlyCoverageStatus.COMPLETE:
            issues.append("TRADE_PROVIDER_HISTORY_INCOMPLETE")
    else:
        status = OnlyCoverageStatus.UNPROVABLE
        proof.append("coverage_capability=unsupported")
        issues.append(f"COVERAGE_UNPROVABLE:{scope.data_kind}")
    gaps: tuple[OnlyBarCoverageGap | OnlyTradeCoverageGap, ...]
    if scope.data_kind == "BAR":
        actual_set = {item.ts_event_ns for item in in_scope}
        gaps = tuple(OnlyBarCoverageGap(item - minute, item) for item in expected if item not in actual_set)
    elif scope.data_kind == "TRADE" and expected:
        actual_set = set(sequences)
        missing = tuple(item for item in expected if item not in actual_set)
        ranges: list[OnlyTradeCoverageGap] = []
        for sequence in missing:
            if ranges and ranges[-1].last_sequence + 1 == sequence:
                prior = ranges[-1]
                ranges[-1] = OnlyTradeCoverageGap(prior.first_sequence, sequence)
            else:
                ranges.append(OnlyTradeCoverageGap(sequence, sequence))
        gaps = tuple(ranges)
    else:
        gaps = ()
    refs = tuple((item.segment_id, item.content_hash) for item in segments)
    return OnlyCoverageManifest.build(
        scope,
        refs,
        coverage_status=status,
        proof=tuple(proof),
        issues=tuple(issues),
        gaps=gaps,
    )


def only_build_seal(
    revision: OnlyMarketDataRevision,
    manifest: OnlyCoverageManifest,
    *,
    sealed_at: datetime,
) -> OnlyMarketDataSeal:
    if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE or manifest.issues:
        raise OnlyMarketDataSealError("REVISION_COVERAGE_NOT_SEALABLE")
    checks = _REQUIRED_SEAL_CHECKS + (("BAR_TEMPORAL_GRID_VERIFIED",) if manifest.scope.data_kind == "BAR" else ())
    fingerprint = only_canonical_fingerprint(
        {"revision": revision.fingerprint, "manifest": manifest.fingerprint, "checks": checks}
    )
    return OnlyMarketDataSeal(f"seal:{fingerprint}", revision.revision_id, revision.fingerprint, checks, sealed_at)


class OnlyInMemoryMarketDataCatalog(OnlyMarketDataCatalog):
    """Deterministic test/reference implementation with put-once semantics."""

    def __init__(self) -> None:
        self._segments: dict[str, OnlyIngestSegment] = {}
        self._acquisitions: dict[str, OnlyMarketDataAcquisitionIntent] = {}
        self._manifests: dict[str, OnlyCoverageManifest] = {}
        self._revisions: dict[str, OnlyMarketDataRevision] = {}
        self._seals: dict[str, OnlyMarketDataSeal] = {}

    def commit_durable_segments(self, segments: tuple[OnlyIngestSegment, ...]) -> None:
        for segment in segments:
            prior = self._segments.get(segment.segment_id)
            if prior is not None and prior != segment:
                raise OnlyMarketDataConflictError("SEGMENT_ID_CONTENT_CONFLICT")
        for segment in segments:
            self._segments.setdefault(segment.segment_id, segment)

    def commit_acquisition_intent(self, intent: OnlyMarketDataAcquisitionIntent) -> None:
        prior = self._acquisitions.get(intent.acquisition_id)
        if prior is not None and prior != intent:
            raise OnlyMarketDataConflictError("ACQUISITION_INTENT_CONFLICT")
        self._acquisitions.setdefault(intent.acquisition_id, intent)

    def commit_coverage_manifest(self, manifest: OnlyCoverageManifest) -> None:
        prior = self._manifests.get(manifest.manifest_id)
        if prior is not None and prior != manifest:
            raise OnlyMarketDataConflictError("COVERAGE_MANIFEST_CONFLICT")
        if any(
            self._segments.get(segment_id) is None or self._segments[segment_id].content_hash != content_hash
            for segment_id, content_hash in manifest.segment_refs
        ):
            raise OnlyMarketDataConflictError("COVERAGE_REFERENCES_NON_DURABLE_SEGMENT")
        self._manifests.setdefault(manifest.manifest_id, manifest)

    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE:
            raise OnlyMarketDataConflictError("REVISION_REQUIRES_COMPLETE_COVERAGE")
        self.commit_coverage_manifest(manifest)
        for segment in segments:
            if self._segments.get(segment.segment_id) != segment:
                raise OnlyMarketDataConflictError("REVISION_REFERENCES_NON_DURABLE_SEGMENT")
        prior_revision = self._revisions.get(revision.revision_id)
        if prior_revision is not None and prior_revision != revision:
            raise OnlyMarketDataConflictError("REVISION_ID_CONTENT_CONFLICT")
        prior_seal = self._seals.get(revision.revision_id)
        if prior_seal is not None and prior_seal != seal:
            raise OnlyMarketDataConflictError("SEALED_REVISION_IMMUTABLE")
        self._revisions.setdefault(revision.revision_id, revision)
        self._seals.setdefault(revision.revision_id, seal)

    def is_segment_committed(self, segment_id: str, content_hash: str) -> bool:
        segment = self._segments.get(segment_id)
        return segment is not None and segment.content_hash == content_hash

    def load_durable_segments(self, segment_ids: tuple[str, ...]) -> tuple[OnlyIngestSegment, ...]:
        return tuple(self._segments[item] for item in segment_ids)

    def list_durable_segments(self, scope: OnlyMarketDataScope) -> tuple[OnlyIngestSegment, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._segments.values()
                    if item.source_id == scope.source_id
                    and item.market == scope.market
                    and item.instrument_id == scope.instrument_id
                    and item.data_kind == scope.data_kind
                    and item.data_version == scope.data_version
                    and item.start_ns is not None
                    and item.end_ns is not None
                    and item.start_ns < scope.end_ns
                    and item.end_ns > scope.start_ns
                ),
                key=lambda item: item.segment_id,
            )
        )

    def load_sealed_revision(self, revision_id: str) -> tuple[OnlyMarketDataRevision, OnlyMarketDataSeal]:
        revision = self._revisions[revision_id]
        return revision, self._seals[revision_id]

    def latest_sealed_revision(self, scope: OnlyMarketDataScope) -> OnlyMarketDataRevision:
        candidates = [
            item for item in self._revisions.values() if item.scope == scope and item.revision_id in self._seals
        ]
        if not candidates:
            raise KeyError("SEALED_REVISION_NOT_FOUND")
        return sorted(candidates, key=lambda item: item.revision_id)[-1]


class OnlyHistoricalMarketDataQueryService:
    def __init__(self, catalog: OnlyMarketDataCatalog, fact_store: OnlyMarketFactStore) -> None:
        self._catalog = catalog
        self._fact_store = fact_store

    def resolve(self, revision_id: str) -> OnlyMarketDataRevision:
        revision, seal = self._catalog.load_sealed_revision(revision_id)
        if seal.revision_fingerprint != revision.fingerprint:
            raise OnlyMarketDataSealError("REVISION_SEAL_FINGERPRINT_MISMATCH")
        return revision

    def resolve_latest(self, scope: OnlyMarketDataScope) -> OnlyMarketDataRevision:
        """Convenience projection; callers receive and must bind the exact revision."""
        return self._catalog.latest_sealed_revision(scope)

    def read_exact(self, revision_id: str, scope: OnlyMarketDataScope) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        revision = self.resolve(revision_id)
        if revision.scope != scope:
            raise ValueError("REVISION_SCOPE_MISMATCH")
        segments = self._catalog.load_durable_segments(tuple(item[0] for item in revision.segment_refs))
        if tuple((item.segment_id, item.content_hash) for item in segments) != revision.segment_refs:
            raise OnlyMarketDataSealError("REVISION_SEGMENT_METADATA_MISMATCH")
        facts = self._fact_store.read_segment_facts(segments, scope)
        only_verify_canonical_uniqueness(facts)
        return only_deduplicate_facts(facts)


class OnlyRevisionCommitService:
    def __init__(
        self,
        fact_store: OnlyMarketFactStore,
        catalog: OnlyMarketDataCatalog,
        *,
        now: Callable[[], datetime] = only_system_utc_now,
    ) -> None:
        self._facts = fact_store
        self._catalog = catalog
        self._now = now

    def commit(
        self,
        segments: OnlyIngestSegment | tuple[OnlyIngestSegment, ...],
        scope: OnlyMarketDataScope,
        records_by_segment: dict[str, tuple[OnlyMarketDataRecordBundle, ...]],
        *,
        parent_revision_id: str | None = None,
        reason: str = "INGEST",
    ) -> tuple[OnlyCoverageManifest, OnlyMarketDataRevision, OnlyMarketDataSeal]:
        manifest, revision, seal = self.commit_if_complete(
            segments,
            scope,
            records_by_segment,
            parent_revision_id=parent_revision_id,
            reason=reason,
        )
        if revision is None or seal is None:
            raise OnlyMarketDataSealError(f"REVISION_COVERAGE_NOT_SEALABLE:{manifest.coverage_status.value}")
        return manifest, revision, seal

    def commit_if_complete(
        self,
        segments: OnlyIngestSegment | tuple[OnlyIngestSegment, ...],
        scope: OnlyMarketDataScope,
        records_by_segment: dict[str, tuple[OnlyMarketDataRecordBundle, ...]],
        *,
        parent_revision_id: str | None = None,
        reason: str = "INGEST",
    ) -> tuple[OnlyCoverageManifest, OnlyMarketDataRevision | None, OnlyMarketDataSeal | None]:
        selected = (segments,) if isinstance(segments, OnlyIngestSegment) else tuple(segments)
        if not selected:
            raise ValueError("MARKET_DATA_REVISION_SEGMENTS_EMPTY")
        ordered = tuple(sorted(selected, key=lambda item: (item.segment_id, item.content_hash)))
        if len({item.segment_id for item in ordered}) != len(ordered):
            raise ValueError("MARKET_DATA_REVISION_SEGMENT_DUPLICATE")
        if set(records_by_segment) != {item.segment_id for item in ordered}:
            raise ValueError("MARKET_DATA_REVISION_RECORD_SET_MISMATCH")
        for segment in ordered:
            self._facts.verify_segment(segment, records_by_segment[segment.segment_id])
        self._catalog.commit_durable_segments(ordered)
        facts = tuple(
            fact
            for segment in ordered
            for bundle in records_by_segment[segment.segment_id]
            for fact in bundle.canonical_facts
        )
        only_verify_canonical_uniqueness(facts)
        manifest = only_build_coverage(scope, ordered, facts)
        self._catalog.commit_coverage_manifest(manifest)
        if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE:
            return manifest, None, None
        normalizers = tuple({(item.normalizer_id, item.normalizer_version) for item in facts})
        revision = OnlyMarketDataRevision.build(
            manifest, normalizers=normalizers, creation_reason=reason, parent_revision_id=parent_revision_id
        )
        seal = only_build_seal(revision, manifest, sealed_at=self._now())
        self._catalog.commit_revision(ordered, manifest, revision, seal)
        return manifest, revision, seal

    def commit_durable_facts(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        scope: OnlyMarketDataScope,
        facts: tuple[OnlyCanonicalMarketFactRecord, ...],
        *,
        parent_revision_id: str | None = None,
        reason: str,
    ) -> tuple[OnlyCoverageManifest, OnlyMarketDataRevision | None, OnlyMarketDataSeal | None]:
        ordered = tuple(sorted(segments, key=lambda item: (item.segment_id, item.content_hash)))
        if not ordered or len({item.segment_id for item in ordered}) != len(ordered):
            raise ValueError("MARKET_DATA_DURABLE_REVISION_SEGMENT_SET_INVALID")
        if any(not self._catalog.is_segment_committed(item.segment_id, item.content_hash) for item in ordered):
            raise OnlyMarketDataConflictError("REVISION_REFERENCES_NON_DURABLE_SEGMENT")
        only_verify_canonical_uniqueness(facts)
        manifest = only_build_coverage(scope, ordered, facts)
        self._catalog.commit_coverage_manifest(manifest)
        if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE:
            return manifest, None, None
        revision = OnlyMarketDataRevision.build(
            manifest,
            normalizers=tuple({(item.normalizer_id, item.normalizer_version) for item in facts}),
            creation_reason=reason,
            parent_revision_id=parent_revision_id,
        )
        seal = only_build_seal(revision, manifest, sealed_at=self._now())
        self._catalog.commit_revision(ordered, manifest, revision, seal)
        return manifest, revision, seal


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
