"""Read-only verified composition of sealed market-data ranges."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.market import OnlyBarSemantic

from .models import (
    OnlyBarCoverageGap,
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyIngestSegment,
    OnlyMarketDataRangeFamily,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from .revision import (
    OnlyMarketDataConflictError,
    OnlyMarketDataSealError,
    only_build_coverage,
    only_build_seal,
    only_deduplicate_facts,
)

MINUTE_NS = 60_000_000_000
DAY_NS = 86_400 * 1_000_000_000


class OnlyBarWindowAnchorKind(StrEnum):
    LATEST_CLOSED = "LATEST_CLOSED"
    BEFORE_TIME = "BEFORE_TIME"


@dataclass(frozen=True, slots=True)
class OnlyBarWindowPlan:
    anchor_kind: OnlyBarWindowAnchorKind
    requested_before_ns: int | None
    requested_bar_count: int
    resolved_start_ns: int
    resolved_end_ns: int
    target_intervals: tuple[OnlyBarCoverageGap, ...]
    provider_intervals: tuple[OnlyBarCoverageGap, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketDataRevisionEvidence:
    revision_id: str
    revision_fingerprint: str
    manifest_id: str
    manifest_fingerprint: str
    seal_id: str
    covered_start_ns: int
    covered_end_ns: int


@dataclass(frozen=True, slots=True)
class OnlyVerifiedMarketDataRange:
    coverage_status: OnlyCoverageStatus
    facts: tuple[OnlyCanonicalMarketFactRecord, ...]
    evidence: tuple[OnlyMarketDataRevisionEvidence, ...]
    gaps: tuple[OnlyBarCoverageGap, ...]
    expected_base_fact_count: int
    complete_interval_count: int
    issues: tuple[str, ...]


def only_plan_utc_24x7_bar_window(
    semantic: OnlyBarSemantic,
    *,
    anchor_kind: OnlyBarWindowAnchorKind,
    before_ns: int | None,
    target_bar_count: int,
    latest_closed_ns: int,
) -> OnlyBarWindowPlan:
    """Resolve final complete session-aligned Bars without encoding this math in Web."""

    if target_bar_count < 1 or not semantic.is_fixed_duration or not semantic.is_aligned:
        raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
    if (anchor_kind is OnlyBarWindowAnchorKind.LATEST_CLOSED) != (before_ns is None):
        raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
    if before_ns is not None and (before_ns <= 0 or before_ns > latest_closed_ns):
        raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
    anchor = latest_closed_ns if before_ns is None else before_ns
    step_ns = semantic.stride_minutes * MINUTE_NS
    complete_session_ns = DAY_NS - DAY_NS % step_ns
    day_start = anchor // DAY_NS * DAY_NS
    end = min(day_start + complete_session_ns, day_start + ((anchor - day_start) // step_ns) * step_ns)
    if end == day_start:
        day_start -= DAY_NS
        end = day_start + complete_session_ns

    intervals: list[OnlyBarCoverageGap] = []
    while len(intervals) < target_bar_count:
        start = end - step_ns
        if start < day_start:
            day_start -= DAY_NS
            end = day_start + complete_session_ns
            continue
        intervals.append(OnlyBarCoverageGap(start, end))
        end = start
    ordered = tuple(reversed(intervals))
    if ordered[0].start_ns < 0:
        raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
    merged = _merge_ranges(ordered)
    return OnlyBarWindowPlan(
        anchor_kind,
        before_ns,
        target_bar_count,
        ordered[0].start_ns,
        ordered[-1].end_ns,
        ordered,
        merged,
    )


def only_plan_acquisition_ranges(
    gaps: tuple[OnlyBarCoverageGap, ...],
    target_intervals: tuple[OnlyBarCoverageGap, ...],
    *,
    maximum_duration_ns: int,
    provider_grid_step_ns: int | None = None,
) -> tuple[OnlyBarCoverageGap, ...]:
    if provider_grid_step_ns is not None:
        if provider_grid_step_ns <= 0:
            raise ValueError("MARKET_DATA_ACQUISITION_PLAN_UNAVAILABLE")
        if not gaps:
            return ()
        start_ns = min(item.start_ns for item in gaps)
        end_ns = max(item.end_ns for item in gaps)
        if start_ns % provider_grid_step_ns or end_ns % provider_grid_step_ns:
            raise ValueError("MARKET_DATA_ACQUISITION_PLAN_UNAVAILABLE")
        chunk_ns = maximum_duration_ns - maximum_duration_ns % provider_grid_step_ns
        if chunk_ns <= 0:
            raise ValueError("MARKET_DATA_ACQUISITION_PLAN_UNAVAILABLE")
        return tuple(
            OnlyBarCoverageGap(cursor, min(end_ns, cursor + chunk_ns)) for cursor in range(start_ns, end_ns, chunk_ns)
        )
    affected = _merge_ranges(
        tuple(
            target
            for target in target_intervals
            if any(target.start_ns < gap.end_ns and target.end_ns > gap.start_ns for gap in gaps)
        )
    )
    if not affected:
        return ()
    step_ns = target_intervals[0].end_ns - target_intervals[0].start_ns
    chunk_ns = maximum_duration_ns - maximum_duration_ns % step_ns
    if chunk_ns <= 0:
        raise ValueError("MARKET_DATA_ACQUISITION_PLAN_UNAVAILABLE")
    planned: list[OnlyBarCoverageGap] = []
    for item in affected:
        cursor = item.start_ns
        while cursor < item.end_ns:
            end = min(item.end_ns, cursor + chunk_ns)
            planned.append(OnlyBarCoverageGap(cursor, end))
            cursor = end
    return tuple(planned)


class OnlyVerifiedMarketDataRangeQuery:
    def __init__(self, catalog: OnlyMarketDataCatalog, fact_store: OnlyMarketFactStore) -> None:
        self._catalog = catalog
        self._facts = fact_store

    def read(
        self,
        family: OnlyMarketDataRangeFamily,
        intervals: tuple[OnlyBarCoverageGap, ...],
    ) -> OnlyVerifiedMarketDataRange:
        if not intervals:
            raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
        start_ns = min(item.start_ns for item in intervals)
        end_ns = max(item.end_ns for item in intervals)
        requested_ranges = _merge_ranges(intervals)
        try:
            revisions = self._catalog.list_current_sealed_revisions_overlapping(family, start_ns, end_ns)
        except Exception as exc:
            raise OnlyMarketDataSealError("MARKET_DATA_CATALOG_UNAVAILABLE") from exc
        facts: list[OnlyCanonicalMarketFactRecord] = []
        segments: dict[str, OnlyIngestSegment] = {}
        evidence: list[OnlyMarketDataRevisionEvidence] = []
        verified_revisions: list[
            tuple[OnlyMarketDataRevision, tuple[OnlyIngestSegment, ...], OnlyCoverageManifest, OnlyMarketDataSeal]
        ] = []
        for revision in revisions:
            if not any(
                revision.scope.start_ns < interval.end_ns and revision.scope.end_ns > interval.start_ns
                for interval in requested_ranges
            ):
                continue
            revision_segments, manifest, seal = self._verify_revision(family, revision)
            verified_revisions.append((revision, revision_segments, manifest, seal))
            for segment in revision_segments:
                prior = segments.setdefault(segment.segment_id, segment)
                if prior != segment:
                    raise OnlyMarketDataConflictError("SEGMENT_ID_CONTENT_CONFLICT")

        ordered_segments = tuple(sorted(segments.values(), key=lambda item: (item.segment_id, item.content_hash)))
        if ordered_segments:
            read_scope = OnlyMarketDataScope(
                family.source_id,
                family.market,
                family.instrument_id,
                family.data_kind,
                start_ns,
                end_ns,
                family.data_version,
                family.bar_type,
                bar_construction=family.bar_construction,
            )
            range_facts = only_deduplicate_facts(self._facts.read_segment_facts(ordered_segments, read_scope))
        else:
            range_facts = ()

        for revision, revision_segments, manifest, seal in verified_revisions:
            revision_segment_ids = {item.segment_id for item in revision_segments}
            facts.extend(
                fact
                for fact in range_facts
                if fact.segment_id in revision_segment_ids
                and revision.scope.start_ns < fact.ts_event_ns <= revision.scope.end_ns
                and any(item.start_ns < fact.ts_event_ns <= item.end_ns for item in requested_ranges)
            )
            evidence.append(
                OnlyMarketDataRevisionEvidence(
                    revision.revision_id,
                    revision.fingerprint,
                    manifest.manifest_id,
                    manifest.fingerprint,
                    seal.seal_id,
                    max(start_ns, revision.scope.start_ns),
                    min(end_ns, revision.scope.end_ns),
                )
            )

        selected = only_deduplicate_facts(tuple(facts))
        interval_inputs = _partition_interval_inputs(intervals, ordered_segments, selected)
        gaps: list[OnlyBarCoverageGap] = []
        issues: list[str] = []
        expected_base_facts = 0
        unprovable = False
        incomplete = False
        complete_intervals = 0
        for interval, (interval_segments, interval_facts) in zip(intervals, interval_inputs, strict=True):
            scope = OnlyMarketDataScope(
                family.source_id,
                family.market,
                family.instrument_id,
                family.data_kind,
                interval.start_ns,
                interval.end_ns,
                family.data_version,
                family.bar_type,
                bar_construction=family.bar_construction,
            )
            coverage = only_build_coverage(scope, interval_segments, interval_facts)
            expected_base_facts += int(
                next(item.split("=", 1)[1] for item in coverage.proof if item.startswith("bar_grid_count="))
            )
            gaps.extend(item for item in coverage.gaps if isinstance(item, OnlyBarCoverageGap))
            unprovable = unprovable or coverage.coverage_status is OnlyCoverageStatus.UNPROVABLE
            incomplete = incomplete or coverage.coverage_status is OnlyCoverageStatus.INCOMPLETE
            issues.extend(coverage.issues)
            if coverage.coverage_status is OnlyCoverageStatus.COMPLETE and not coverage.issues and not coverage.gaps:
                complete_intervals += 1
        status = (
            OnlyCoverageStatus.UNPROVABLE
            if unprovable
            else OnlyCoverageStatus.INCOMPLETE
            if incomplete or issues or gaps
            else OnlyCoverageStatus.COMPLETE
        )
        return OnlyVerifiedMarketDataRange(
            status,
            selected if status is OnlyCoverageStatus.COMPLETE else (),
            tuple(sorted(evidence, key=lambda item: (item.covered_start_ns, item.covered_end_ns, item.revision_id))),
            tuple(sorted(set(gaps), key=lambda item: (item.start_ns, item.end_ns))),
            expected_base_facts,
            complete_intervals,
            tuple(sorted(set(issues))),
        )

    def _verify_revision(
        self, family: OnlyMarketDataRangeFamily, revision: OnlyMarketDataRevision
    ) -> tuple[
        tuple[OnlyIngestSegment, ...],
        OnlyCoverageManifest,
        OnlyMarketDataSeal,
    ]:
        if not family.matches(revision.scope):
            raise OnlyMarketDataSealError("MARKET_DATA_RANGE_FAMILY_MISMATCH")
        try:
            stored, seal = self._catalog.load_sealed_revision(revision.revision_id)
            manifest = self._catalog.load_coverage_manifest(revision.manifest_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID") from exc
        except Exception as exc:
            raise OnlyMarketDataSealError("MARKET_DATA_CATALOG_UNAVAILABLE") from exc
        if (
            stored != revision
            or manifest.manifest_id != revision.manifest_id
            or manifest.scope != revision.scope
            or manifest.segment_refs != revision.segment_refs
            or manifest.coverage_status is not OnlyCoverageStatus.COMPLETE
            or manifest.issues
            or OnlyMarketDataRevision.build(
                manifest,
                normalizers=revision.normalizers,
                creation_reason=revision.creation_reason,
                parent_revision_id=revision.parent_revision_id,
            )
            != revision
            or only_build_seal(revision, manifest, sealed_at=seal.sealed_at) != seal
        ):
            raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
        try:
            segments = self._catalog.load_durable_segments(tuple(item[0] for item in revision.segment_refs))
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID") from exc
        except Exception as exc:
            raise OnlyMarketDataSealError("MARKET_DATA_CATALOG_UNAVAILABLE") from exc
        if tuple((item.segment_id, item.content_hash) for item in segments) != revision.segment_refs:
            raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
        return segments, manifest, seal


def only_history_projection_fingerprint(value: object) -> str:
    return only_canonical_fingerprint(value)


def _partition_interval_inputs(
    intervals: tuple[OnlyBarCoverageGap, ...],
    segments: tuple[OnlyIngestSegment, ...],
    facts: tuple[OnlyCanonicalMarketFactRecord, ...],
) -> tuple[tuple[tuple[OnlyIngestSegment, ...], tuple[OnlyCanonicalMarketFactRecord, ...]], ...]:
    indexed = sorted(enumerate(intervals), key=lambda item: (item[1].start_ns, item[1].end_ns))
    if any(left.end_ns > right.start_ns for (_, left), (_, right) in zip(indexed, indexed[1:], strict=False)):
        raise ValueError("MARKET_DATA_WINDOW_REQUEST_INVALID")
    starts = tuple(item.start_ns for _, item in indexed)
    ends = tuple(item.end_ns for _, item in indexed)
    segment_buckets: list[list[OnlyIngestSegment]] = [[] for _ in intervals]
    fact_buckets: list[list[OnlyCanonicalMarketFactRecord]] = [[] for _ in intervals]
    for fact in facts:
        position = bisect_left(ends, fact.ts_event_ns)
        if position < len(indexed) and starts[position] < fact.ts_event_ns:
            fact_buckets[indexed[position][0]].append(fact)
    for segment in segments:
        if segment.start_ns is None or segment.end_ns is None:
            raise OnlyMarketDataConflictError(f"SEGMENT_SCOPE_MISMATCH:{segment.segment_id}")
        position = bisect_right(ends, segment.start_ns)
        while position < len(indexed) and starts[position] < segment.end_ns:
            segment_buckets[indexed[position][0]].append(segment)
            position += 1
    return tuple((tuple(segment_buckets[index]), tuple(fact_buckets[index])) for index in range(len(intervals)))


def _merge_ranges(ranges: tuple[OnlyBarCoverageGap, ...]) -> tuple[OnlyBarCoverageGap, ...]:
    merged: list[OnlyBarCoverageGap] = []
    for item in sorted(set(ranges), key=lambda value: (value.start_ns, value.end_ns)):
        if merged and merged[-1].end_ns >= item.start_ns:
            prior = merged[-1]
            merged[-1] = OnlyBarCoverageGap(prior.start_ns, max(prior.end_ns, item.end_ns))
        else:
            merged.append(item)
    return tuple(merged)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
