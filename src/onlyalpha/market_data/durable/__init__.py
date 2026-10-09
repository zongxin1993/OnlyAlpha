"""Lazy durable exports; pure evidence imports never load owning services."""

# ruff: noqa: F401

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backfill import (
        OnlyMarketDataBackfillCoordinator,
        OnlyMarketDataBackfillResult,
        OnlyMarketDataCorrectionComposer,
        only_bar_gap_is_backfillable,
        only_plan_contiguous_bar_gaps,
    )
    from .drain import OnlyMarketDataDrainService
    from .ingress import OnlyMarketDataIngress
    from .memory import OnlyInMemoryMarketFactStore
    from .models import (
        OnlyAcquisitionOutcome,
        OnlyBarCoverageGap,
        OnlyCanonicalMarketFactRecord,
        OnlyCoverageManifest,
        OnlyCoverageStatus,
        OnlyIngestSegment,
        OnlyMarketDataAcquisitionAttempt,
        OnlyMarketDataAcquisitionIntent,
        OnlyMarketDataHealth,
        OnlyMarketDataProvenance,
        OnlyMarketDataQualityState,
        OnlyMarketDataRangeFamily,
        OnlyMarketDataRecordBundle,
        OnlyMarketDataRevision,
        OnlyMarketDataScope,
        OnlyMarketDataSeal,
        OnlyRawProviderEvidence,
        OnlyRecordingState,
        OnlySegmentState,
        OnlyTradeCoverageGap,
        OnlyVerifiedSegmentBatch,
    )
    from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
    from .range_query import (
        OnlyBarWindowAnchorKind,
        OnlyBarWindowPlan,
        OnlyMarketDataRevisionEvidence,
        OnlyVerifiedMarketDataRange,
        OnlyVerifiedMarketDataRangeQuery,
        only_history_projection_fingerprint,
        only_plan_acquisition_ranges,
        only_plan_utc_24x7_bar_window,
    )
    from .recorder import OnlyDurableMarketDataRecorder
    from .recovery import OnlyInjectedMarketDataCrash, OnlyMarketDataCrashBoundary, OnlyMarketDataRecoveryCoordinator
    from .revision import (
        OnlyHistoricalMarketDataQueryService,
        OnlyInMemoryMarketDataCatalog,
        OnlyMarketDataConflictError,
        OnlyRevisionCommitService,
        only_build_coverage,
        only_deduplicate_facts,
        only_verify_canonical_uniqueness,
    )
    from .sealed_identity import OnlyMarketDataSealError, only_build_seal
    from .wal import (
        OnlyMarketDataWal,
        OnlyWalCapacityError,
        OnlyWalCorruptionError,
        OnlyWalError,
        OnlyWalRecoveryResult,
    )

_EXPORT_GROUPS = {
    "backfill": "OnlyMarketDataBackfillCoordinator OnlyMarketDataBackfillResult OnlyMarketDataCorrectionComposer only_bar_gap_is_backfillable only_plan_contiguous_bar_gaps",
    "drain": "OnlyMarketDataDrainService",
    "ingress": "OnlyMarketDataIngress",
    "memory": "OnlyInMemoryMarketFactStore",
    "models": "OnlyAcquisitionOutcome OnlyBarCoverageGap OnlyCanonicalMarketFactRecord OnlyCoverageManifest OnlyCoverageStatus OnlyIngestSegment OnlyMarketDataAcquisitionAttempt OnlyMarketDataAcquisitionIntent OnlyMarketDataHealth OnlyMarketDataProvenance OnlyMarketDataQualityState OnlyMarketDataRangeFamily OnlyMarketDataRecordBundle OnlyMarketDataRevision OnlyMarketDataScope OnlyMarketDataSeal OnlyRawProviderEvidence OnlyRecordingState OnlySegmentState OnlyTradeCoverageGap OnlyVerifiedSegmentBatch",
    "ports": "OnlyMarketDataCatalog OnlyMarketFactStore",
    "range_query": "OnlyBarWindowAnchorKind OnlyBarWindowPlan OnlyMarketDataRevisionEvidence OnlyVerifiedMarketDataRange OnlyVerifiedMarketDataRangeQuery only_history_projection_fingerprint only_plan_acquisition_ranges only_plan_utc_24x7_bar_window",
    "recorder": "OnlyDurableMarketDataRecorder",
    "recovery": "OnlyInjectedMarketDataCrash OnlyMarketDataCrashBoundary OnlyMarketDataRecoveryCoordinator",
    "revision": "OnlyHistoricalMarketDataQueryService OnlyInMemoryMarketDataCatalog OnlyMarketDataConflictError OnlyRevisionCommitService only_build_coverage only_deduplicate_facts only_verify_canonical_uniqueness",
    "sealed_identity": "OnlyMarketDataSealError only_build_seal",
    "wal": "OnlyMarketDataWal OnlyWalCapacityError OnlyWalCorruptionError OnlyWalError OnlyWalRecoveryResult",
}
_EXPORTS = {name: module for module, names in _EXPORT_GROUPS.items() for name in names.split()}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value: object = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value
