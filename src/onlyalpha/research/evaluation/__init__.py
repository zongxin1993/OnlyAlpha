"""Research-only Target evaluation and immutable Statistics authority."""
# ruff: noqa: F401

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

from .alignment import (
    OnlyResearchAlignedObservation,
    OnlyResearchAlignedPair,
    only_align_research_series,
)
from .capability import (
    OnlyResearchStatisticsCapability,
    only_research_statistics_capabilities,
    only_research_statistics_capability,
)
from .definition import (
    OnlyResearchPairingPolicy,
    OnlyResearchRankTieMethod,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchUniversePolicy,
    OnlyResearchWeighting,
)
from .errors import OnlyResearchEvaluationError, OnlyResearchStatisticsResultStoreError
from .execution import (
    OnlyResearchStatisticsExecution,
    OnlyResearchStatisticsExecutor,
    only_compute_research_statistics,
)
from .factor_pair import *  # noqa: F403
from .plan import OnlyResearchStatisticsPlan
from .reference import OnlyResearchFeatureSeriesReference, OnlyResearchTargetSeriesReference
from .result import (
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsOutcome,
    OnlyResearchStatisticsResult,
    OnlyResearchStatisticsResultManifest,
    OnlyResearchStatisticsResultVerification,
    OnlyResearchStatisticStatus,
)
from .result_identity import (
    only_research_statistics_fingerprint,
    only_research_statistics_result_content_fingerprint,
    only_research_statistics_result_fingerprint,
)
from .result_store import OnlyParquetResearchStatisticsResultStore
from .summary import *  # noqa: F403

_SUBJECT_EXPORTS = (
    "OnlyExactAuthoringGenerationReader",
    "OnlyExactEvaluationIntentResolverV1",
    "OnlyExactEvaluationIntentSubjectV1",
    "OnlyResearchEvaluationSubjectSetV1",
)
if _TYPE_CHECKING:
    from .subject import OnlyExactAuthoringGenerationReader as OnlyExactAuthoringGenerationReader
    from .subject import OnlyExactEvaluationIntentResolverV1 as OnlyExactEvaluationIntentResolverV1
    from .subject import OnlyExactEvaluationIntentSubjectV1 as OnlyExactEvaluationIntentSubjectV1
    from .subject import OnlyResearchEvaluationSubjectSetV1 as OnlyResearchEvaluationSubjectSetV1


def __getattr__(name: str) -> object:
    if name not in _SUBJECT_EXPORTS:
        raise AttributeError(name)
    value = getattr(_import_module(".subject", __name__), name)
    globals()[name] = value
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLY_RESEARCH_"))] + list(_SUBJECT_EXPORTS)
