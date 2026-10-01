"""Provider-neutral requested-scope backfill and immutable correction composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter_ns

from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalTradeRequest
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.domain.time import OnlyTimestamp

from .models import (
    OnlyBarCoverageGap,
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataRevision,
    OnlyMarketDataSeal,
    OnlyTradeCoverageGap,
)
from .performance import only_market_data_phase, only_market_data_timed
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from .recovery import OnlyMarketDataRecoveryCoordinator
from .revision import (
    OnlyRevisionCommitService,
    _OnlyVerifiedMarketDataCompletion,
    only_build_coverage,
    only_verify_revision_authority,
)

_LOGGER = logging.getLogger(__name__)


def only_plan_contiguous_bar_gaps(
    gaps: tuple[OnlyBarCoverageGap, ...],
) -> tuple[OnlyBarCoverageGap, ...]:
    """Coalesce adjacent canonical 1m gaps into bounded provider fetch ranges."""

    ordered = tuple(sorted(gaps, key=lambda item: (item.start_ns, item.end_ns)))
    planned: list[OnlyBarCoverageGap] = []
    for gap in ordered:
        if planned and planned[-1].end_ns >= gap.start_ns:
            prior = planned[-1]
            planned[-1] = OnlyBarCoverageGap(prior.start_ns, max(prior.end_ns, gap.end_ns))
            continue
        planned.append(gap)
    return tuple(planned)


def only_bar_gap_is_backfillable(planned: OnlyBarCoverageGap, gaps: tuple[OnlyBarCoverageGap, ...]) -> bool:
    """A planned range is fetchable only when exact canonical gaps tile it completely."""

    if planned.start_ns >= planned.end_ns:
        return False
    cursor = planned.start_ns
    for gap in sorted(gaps, key=lambda item: (item.start_ns, item.end_ns)):
        if gap.end_ns <= cursor:
            continue
        if gap.start_ns != cursor or gap.end_ns > planned.end_ns:
            return False
        cursor = gap.end_ns
        if cursor == planned.end_ns:
            return True
    return False


@dataclass(frozen=True, slots=True)
class OnlyMarketDataBackfillResult:
    acquisition: OnlyMarketDataAcquisitionIntent
    manifest: OnlyCoverageManifest
    revision: OnlyMarketDataRevision | None
    seal: OnlyMarketDataSeal | None
    recovery_results: tuple[str, ...]
    verified_completion: _OnlyVerifiedMarketDataCompletion | None = None


class OnlyMarketDataBackfillCoordinator:
    def __init__(
        self,
        source: OnlyHistoricalDataSource,
        catalog: OnlyMarketDataCatalog,
        fact_store: OnlyMarketFactStore,
        recovery: OnlyMarketDataRecoveryCoordinator,
        revision_committer: OnlyRevisionCommitService,
    ) -> None:
        self._source = source
        self._catalog = catalog
        self._facts = fact_store
        self._recovery = recovery
        self._committer = revision_committer

    @only_market_data_timed("inspect")
    def inspect(self, acquisition: OnlyMarketDataAcquisitionIntent) -> OnlyCoverageManifest:
        self._validate_acquisition(acquisition)
        self._catalog.admit_acquisition_intent(acquisition)
        segments = self._catalog.list_durable_segments(acquisition.requested_scope)
        proofs = self._catalog.load_physical_proofs(tuple(item.segment_id for item in segments))
        facts = self._facts.read_segment_facts(segments, acquisition.requested_scope, proofs)
        manifest = only_build_coverage(acquisition.requested_scope, segments, facts)
        self._catalog.commit_coverage_manifest(manifest)
        return manifest

    def backfill_bar_gap(
        self,
        acquisition: OnlyMarketDataAcquisitionIntent,
        request: OnlyHistoricalBarRequest,
        gap: OnlyBarCoverageGap,
        *,
        parent_revision_id: str | None = None,
    ) -> OnlyMarketDataBackfillResult:
        with only_market_data_phase("backfill_preinspect"):
            before = self.inspect(acquisition)
        if not only_bar_gap_is_backfillable(
            gap, tuple(item for item in before.gaps if isinstance(item, OnlyBarCoverageGap))
        ):
            raise ValueError("BACKFILL_BAR_GAP_NOT_REQUESTED")
        if (
            acquisition.requested_scope.data_kind != "BAR"
            or OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos != gap.start_ns
            or OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos != gap.end_ns
        ):
            raise ValueError("BACKFILL_BAR_REQUEST_SCOPE_MISMATCH")
        prior = {item.segment_id for item in self._catalog.list_durable_segments(acquisition.requested_scope)}
        fetch_started = perf_counter_ns()
        with only_market_data_phase("provider_fetch"):
            tuple(self._source.load_bars(request))
        _LOGGER.info(
            "market_data_provider_fetch provider_fetch_ms=%d", (perf_counter_ns() - fetch_started) // 1_000_000
        )
        recovery_results = self._recovery.recover_all()
        return self._finish(acquisition, prior, parent_revision_id, recovery_results)

    def backfill_trade_gap(
        self,
        acquisition: OnlyMarketDataAcquisitionIntent,
        request: OnlyHistoricalTradeRequest,
        gap: OnlyTradeCoverageGap,
        *,
        parent_revision_id: str | None = None,
    ) -> OnlyMarketDataBackfillResult:
        before = self.inspect(acquisition)
        if acquisition.requested_scope.data_kind != "TRADE" or gap not in before.gaps:
            raise ValueError("BACKFILL_TRADE_GAP_NOT_REQUESTED")
        prior = {item.segment_id for item in self._catalog.list_durable_segments(acquisition.requested_scope)}
        fetch_started = perf_counter_ns()
        tuple(self._source.load_trades(request))
        _LOGGER.info(
            "market_data_provider_fetch provider_fetch_ms=%d", (perf_counter_ns() - fetch_started) // 1_000_000
        )
        recovery_results = self._recovery.recover_all()
        return self._finish(acquisition, prior, parent_revision_id, recovery_results)

    @only_market_data_timed("finish_scope_compose")
    def _finish(
        self,
        acquisition: OnlyMarketDataAcquisitionIntent,
        prior_segment_ids: set[str],
        parent_revision_id: str | None,
        recovery_results: tuple[str, ...],
    ) -> OnlyMarketDataBackfillResult:
        available = self._catalog.list_durable_segments(acquisition.requested_scope)
        new_segment_refs = {
            (item.segment_id, item.content_hash) for item in available if item.segment_id not in prior_segment_ids
        }
        if not new_segment_refs:
            raise RuntimeError("BACKFILL_DURABLE_SEGMENT_NOT_CREATED")
        if parent_revision_id is None:
            try:
                latest_revision = self._catalog.latest_sealed_revision(acquisition.requested_scope)
            except KeyError as exc:
                if not exc.args or exc.args[0] != "SEALED_REVISION_NOT_FOUND":
                    raise
            else:
                stored, latest_seal = self._catalog.load_sealed_revision(latest_revision.revision_id)
                manifest = self._catalog.load_coverage_manifest(stored.manifest_id)
                only_verify_revision_authority(stored, manifest, latest_seal)
                if (
                    stored != latest_revision
                    or stored.scope != acquisition.requested_scope
                    or stored.creation_reason != "BACKFILL"
                    or stored.parent_revision_id != parent_revision_id
                ):
                    raise RuntimeError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
                if {item[0] for item in new_segment_refs}.issubset({item[0] for item in stored.segment_refs}):
                    if not new_segment_refs.issubset(set(stored.segment_refs)):
                        raise RuntimeError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
                    completion = self._recovery._completion
                    if completion is not None:
                        completion.assert_matches(completion.manifest, completion.revision, completion.seal)
                        if (completion.manifest, completion.revision, completion.seal) != (
                            manifest,
                            stored,
                            latest_seal,
                        ):
                            completion = None
                    return OnlyMarketDataBackfillResult(
                        acquisition, manifest, stored, latest_seal, recovery_results, completion
                    )
            selected = available
        else:
            parent, parent_seal = self._catalog.load_sealed_revision(parent_revision_id)
            only_verify_revision_authority(
                parent, self._catalog.load_coverage_manifest(parent.manifest_id), parent_seal
            )
            if parent.scope != acquisition.requested_scope:
                raise ValueError("BACKFILL_PARENT_SCOPE_MISMATCH")
            ids = {item[0] for item in parent.segment_refs} | {
                item.segment_id for item in available if item.segment_id not in prior_segment_ids
            }
            selected = self._catalog.load_durable_segments(tuple(sorted(ids)))
        proofs = self._catalog.load_physical_proofs(tuple(item.segment_id for item in selected))
        facts = self._facts.read_segment_facts(selected, acquisition.requested_scope, proofs)
        manifest, revision, seal = self._committer.commit_durable_facts(
            selected,
            acquisition.requested_scope,
            facts,
            parent_revision_id=parent_revision_id,
            reason="BACKFILL",
        )
        return OnlyMarketDataBackfillResult(acquisition, manifest, revision, seal, recovery_results)

    def _validate_acquisition(self, acquisition: OnlyMarketDataAcquisitionIntent) -> None:
        if str(self._source.source_id) != acquisition.source_id:
            raise ValueError("BACKFILL_SOURCE_ID_MISMATCH")


class OnlyMarketDataCorrectionComposer:
    def __init__(
        self,
        catalog: OnlyMarketDataCatalog,
        fact_store: OnlyMarketFactStore,
        revision_committer: OnlyRevisionCommitService,
    ) -> None:
        self._catalog = catalog
        self._facts = fact_store
        self._committer = revision_committer

    def compose(
        self,
        parent_revision_id: str,
        replacements: tuple[tuple[str, str], ...],
    ) -> tuple[OnlyCoverageManifest, OnlyMarketDataRevision, OnlyMarketDataSeal]:
        parent, parent_seal = self._catalog.load_sealed_revision(parent_revision_id)
        only_verify_revision_authority(parent, self._catalog.load_coverage_manifest(parent.manifest_id), parent_seal)
        replacement_map = dict(replacements)
        if not replacement_map or len(replacement_map) != len(replacements):
            raise ValueError("CORRECTION_REPLACEMENT_SET_INVALID")
        parent_ids = {item[0] for item in parent.segment_refs}
        if not set(replacement_map).issubset(parent_ids):
            raise ValueError("CORRECTION_REPLACED_SEGMENT_NOT_IN_PARENT")
        selected_ids = tuple(sorted(replacement_map.get(segment_id, segment_id) for segment_id in parent_ids))
        segments = self._catalog.load_durable_segments(selected_ids)
        proofs = self._catalog.load_physical_proofs(tuple(item.segment_id for item in segments))
        facts = self._facts.read_segment_facts(segments, parent.scope, proofs)
        manifest, revision, seal = self._committer.commit_durable_facts(
            segments,
            parent.scope,
            facts,
            parent_revision_id=parent.revision_id,
            reason="CORRECTION",
        )
        if revision is None or seal is None or manifest.coverage_status is not OnlyCoverageStatus.COMPLETE:
            raise RuntimeError("CORRECTION_RESULT_NOT_COMPLETE")
        return manifest, revision, seal


__all__ = [name for name in globals() if name.startswith("Only")]
