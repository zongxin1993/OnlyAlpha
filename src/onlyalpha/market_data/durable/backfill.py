"""Provider-neutral requested-scope backfill and immutable correction composition."""

from __future__ import annotations

from dataclasses import dataclass

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
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from .recovery import OnlyMarketDataRecoveryCoordinator
from .revision import OnlyRevisionCommitService, only_build_coverage


@dataclass(frozen=True, slots=True)
class OnlyMarketDataBackfillResult:
    acquisition: OnlyMarketDataAcquisitionIntent
    manifest: OnlyCoverageManifest
    revision: OnlyMarketDataRevision | None
    seal: OnlyMarketDataSeal | None
    recovery_results: tuple[str, ...]


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

    def inspect(self, acquisition: OnlyMarketDataAcquisitionIntent) -> OnlyCoverageManifest:
        self._validate_acquisition(acquisition)
        self._catalog.commit_acquisition_intent(acquisition)
        segments = self._catalog.list_durable_segments(acquisition.requested_scope)
        facts = self._facts.read_segment_facts(segments, acquisition.requested_scope)
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
        before = self.inspect(acquisition)
        if gap not in before.gaps:
            raise ValueError("BACKFILL_BAR_GAP_NOT_REQUESTED")
        if (
            acquisition.requested_scope.data_kind != "BAR"
            or OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos != gap.start_ns
            or OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos != gap.end_ns
        ):
            raise ValueError("BACKFILL_BAR_REQUEST_SCOPE_MISMATCH")
        prior = {item.segment_id for item in self._catalog.list_durable_segments(acquisition.requested_scope)}
        tuple(self._source.load_bars(request))
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
        tuple(self._source.load_trades(request))
        recovery_results = self._recovery.recover_all()
        return self._finish(acquisition, prior, parent_revision_id, recovery_results)

    def _finish(
        self,
        acquisition: OnlyMarketDataAcquisitionIntent,
        prior_segment_ids: set[str],
        parent_revision_id: str | None,
        recovery_results: tuple[str, ...],
    ) -> OnlyMarketDataBackfillResult:
        available = self._catalog.list_durable_segments(acquisition.requested_scope)
        if not any(item.segment_id not in prior_segment_ids for item in available):
            raise RuntimeError("BACKFILL_DURABLE_SEGMENT_NOT_CREATED")
        if parent_revision_id is None:
            selected = available
        else:
            parent, _ = self._catalog.load_sealed_revision(parent_revision_id)
            if parent.scope != acquisition.requested_scope:
                raise ValueError("BACKFILL_PARENT_SCOPE_MISMATCH")
            ids = {item[0] for item in parent.segment_refs} | {
                item.segment_id for item in available if item.segment_id not in prior_segment_ids
            }
            selected = self._catalog.load_durable_segments(tuple(sorted(ids)))
        facts = self._facts.read_segment_facts(selected, acquisition.requested_scope)
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
        parent, _ = self._catalog.load_sealed_revision(parent_revision_id)
        replacement_map = dict(replacements)
        if not replacement_map or len(replacement_map) != len(replacements):
            raise ValueError("CORRECTION_REPLACEMENT_SET_INVALID")
        parent_ids = {item[0] for item in parent.segment_refs}
        if not set(replacement_map).issubset(parent_ids):
            raise ValueError("CORRECTION_REPLACED_SEGMENT_NOT_IN_PARENT")
        selected_ids = tuple(sorted(replacement_map.get(segment_id, segment_id) for segment_id in parent_ids))
        segments = self._catalog.load_durable_segments(selected_ids)
        facts = self._facts.read_segment_facts(segments, parent.scope)
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
