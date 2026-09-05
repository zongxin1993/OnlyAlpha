"""First-class Factor-Pair correlation Statistics authority."""
# ruff: noqa: F401

from .alignment import (
    OnlyResearchFactorPairAlignedObservation,
    OnlyResearchFactorPairAlignedPair,
    only_align_research_factor_pair,
)
from .definition import (
    OnlyResearchFactorPairAlignment,
    OnlyResearchFactorPairStatisticsDefinition,
    OnlyResearchFactorPairStatisticsMethod,
)
from .execution import (
    OnlyResearchFactorPairStatisticsExecution,
    OnlyResearchFactorPairStatisticsExecutor,
    only_compute_research_factor_pair_statistics,
)
from .identity import (
    RESEARCH_FACTOR_PAIR_STATISTICS_DOMAIN,
    only_research_factor_pair_result_content_fingerprint,
    only_research_factor_pair_result_fingerprint,
    only_research_factor_pair_statistics_fingerprint,
)
from .plan import OnlyResearchFactorPairStatisticsPlan
from .reference import OnlyResearchFactorPairOperand
from .result import (
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticsDisposition,
    OnlyResearchFactorPairStatisticsOutcome,
    OnlyResearchFactorPairStatisticsResult,
    OnlyResearchFactorPairStatisticsResultManifest,
    OnlyResearchFactorPairStatisticsResultVerification,
    OnlyResearchFactorPairStatisticStatus,
)
from .result_store import OnlyParquetResearchFactorPairStatisticsResultStore

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "RESEARCH_FACTOR_PAIR_"))]
