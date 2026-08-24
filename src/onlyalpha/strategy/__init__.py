"""Immutable Strategy Product authority and execution projection."""

# ruff: noqa: F401

from onlyalpha.strategy.admission import (
    OnlyCalculationEquivalenceEvidenceReader,
    OnlyStrategyAdmission,
    OnlyStrategyTradingAdmissionService,
)
from onlyalpha.strategy.errors import (
    OnlyStrategyAdmissionError,
    OnlyStrategyError,
    OnlyStrategyFreezeError,
    OnlyStrategyPromotionError,
    OnlyStrategyResolutionError,
    OnlyStrategyStoreError,
)
from onlyalpha.strategy.execution import (
    OnlyStrategyDecision,
    OnlyStrategyExecutionPlan,
    OnlyStrategyExecutionResolver,
    OnlyStrategyIncrementalExecutor,
    OnlyStrategyObservationKey,
    only_strategy_observation_fingerprint,
    only_strategy_observation_key,
)

# Freeze orchestration imports the Research product surface.  It deliberately
# stays behind ``onlyalpha.strategy.freeze`` so importing the lightweight
# Strategy contract from the trading runtime cannot initialize Research and
# form a Cluster -> Strategy -> Research -> MarketData -> Cluster cycle.
from onlyalpha.strategy.promotion import (
    OnlyInMemoryStrategyPromotionLedger,
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionLedger,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
)
from onlyalpha.strategy.revision import (
    STRATEGY_REVISION_SCHEMA_VERSION,
    OnlyStrategyDataKind,
    OnlyStrategyFingerprint,
    OnlyStrategyImplementationBinding,
    OnlyStrategyMarketInputContract,
    OnlyStrategyMissingDecisionPolicy,
    OnlyStrategyObservationAdmission,
    OnlyStrategyRevision,
    OnlyStrategySignalBinding,
    OnlyStrategySignalSemantics,
    OnlyStrategyUniverse,
    OnlyStrategyUniverseKind,
    only_strategy_revision_fingerprint,
)
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore, OnlyStrategyRevisionReader

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "STRATEGY_"))]
