"""Coverage, immutable revision construction and exact historical reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyIngestSegment,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
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
        complete = actual == expected and semantic_valid
        proof.append(f"bar_grid_count={len(expected)}")
        proof.append(f"closed_external_1m={str(semantic_valid).lower()}")
        if actual != expected:
            issues.append("BAR_GRID_INCOMPLETE")
        if not semantic_valid:
            issues.append("BAR_SEMANTICS_INVALID")
    elif scope.data_kind == "TRADE":
        sequences = tuple(
            sorted(
                int(str(item.canonical_payload["source_sequence"]))
                for item in in_scope
                if "source_sequence" in item.canonical_payload
            )
        )
        expected = (
            ()
            if scope.first_sequence is None or scope.last_sequence is None
            else tuple(range(scope.first_sequence, scope.last_sequence + 1))
        )
        complete = bool(expected) and sequences == expected
        proof.append(
            f"provider_identity_range={sequences[0] if sequences else 'none'}:{sequences[-1] if sequences else 'none'}"
        )
        if not complete:
            issues.append("TRADE_PROVIDER_HISTORY_INCOMPLETE")
    else:
        complete = bool(in_scope)
        proof.append("explicit_event_coverage=true" if complete else "explicit_event_coverage=false")
        if not complete:
            issues.append("EVENT_COVERAGE_EMPTY")
    refs = tuple((item.segment_id, item.content_hash) for item in segments)
    return OnlyCoverageManifest.build(scope, refs, complete=complete, proof=tuple(proof), issues=tuple(issues))


def only_build_seal(
    revision: OnlyMarketDataRevision,
    manifest: OnlyCoverageManifest,
    *,
    sealed_at: datetime,
) -> OnlyMarketDataSeal:
    if not manifest.complete or manifest.issues:
        raise OnlyMarketDataSealError("REVISION_COVERAGE_NOT_SEALABLE")
    checks = _REQUIRED_SEAL_CHECKS + (("BAR_TEMPORAL_GRID_VERIFIED",) if manifest.scope.data_kind == "BAR" else ())
    fingerprint = only_canonical_fingerprint(
        {"revision": revision.fingerprint, "manifest": manifest.fingerprint, "checks": checks}
    )
    return OnlyMarketDataSeal(f"seal:{fingerprint}", revision.revision_id, revision.fingerprint, checks, sealed_at)


class OnlyInMemoryMarketDataCatalog(OnlyMarketDataCatalog):
    """Deterministic test/reference implementation with put-once semantics."""

    def __init__(self) -> None:
        self._segments: dict[str, str] = {}
        self._manifests: dict[str, OnlyCoverageManifest] = {}
        self._revisions: dict[str, OnlyMarketDataRevision] = {}
        self._seals: dict[str, OnlyMarketDataSeal] = {}

    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        for segment in segments:
            prior = self._segments.get(segment.segment_id)
            if prior is not None and prior != segment.content_hash:
                raise OnlyMarketDataConflictError("SEGMENT_ID_CONTENT_CONFLICT")
        prior_revision = self._revisions.get(revision.revision_id)
        if prior_revision is not None and prior_revision != revision:
            raise OnlyMarketDataConflictError("REVISION_ID_CONTENT_CONFLICT")
        prior_seal = self._seals.get(revision.revision_id)
        if prior_seal is not None and prior_seal != seal:
            raise OnlyMarketDataConflictError("SEALED_REVISION_IMMUTABLE")
        for segment in segments:
            self._segments[segment.segment_id] = segment.content_hash
        self._manifests.setdefault(manifest.manifest_id, manifest)
        self._revisions.setdefault(revision.revision_id, revision)
        self._seals.setdefault(revision.revision_id, seal)

    def is_segment_committed(self, segment_id: str, content_hash: str) -> bool:
        return self._segments.get(segment_id) == content_hash

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
        facts = self._fact_store.read_revision_facts(revision, scope)
        only_verify_canonical_uniqueness(facts)
        return only_deduplicate_facts(facts)


class OnlyRevisionCommitService:
    def __init__(
        self,
        fact_store: OnlyMarketFactStore,
        catalog: OnlyMarketDataCatalog,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
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
        facts = tuple(
            fact
            for segment in ordered
            for bundle in records_by_segment[segment.segment_id]
            for fact in bundle.canonical_facts
        )
        only_verify_canonical_uniqueness(facts)
        manifest = only_build_coverage(scope, ordered, facts)
        normalizers = tuple({(item.normalizer_id, item.normalizer_version) for item in facts})
        revision = OnlyMarketDataRevision.build(
            manifest, normalizers=normalizers, creation_reason=reason, parent_revision_id=parent_revision_id
        )
        seal = only_build_seal(revision, manifest, sealed_at=self._now())
        self._catalog.commit_revision(ordered, manifest, revision, seal)
        return manifest, revision, seal


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
