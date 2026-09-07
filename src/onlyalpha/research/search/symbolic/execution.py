"""Current-runtime enumeration and reproduction certification boundaries."""

from __future__ import annotations

from onlyalpha.research.experiment import OnlySearchExperimentManifestV2

from .context import (
    OnlyExecutableSymbolicSearchContextV1,
    OnlyVerifiedSymbolicSearchContextV1,
    admit_current_symbolic_algorithm_runtime,
)
from .enumeration import OnlySymbolicEnumerationExecutionV1, enumerate_symbolic_factor_proposals
from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchError
from .historical import (
    OnlySymbolicHistoricalStore,
    load_symbolic_enumeration_result_historical_verified,
)


def build_symbolic_enumeration_result(
    experiment: OnlySearchExperimentManifestV2,
    execution: OnlySymbolicEnumerationExecutionV1,
) -> OnlySymbolicEnumerationResultV1:
    return OnlySymbolicEnumerationResultV1(
        experiment.experiment_fingerprint,
        experiment.search_algorithm_binding.implementation_fingerprint,
        experiment.search_space_reference.search_space_fingerprint,
        experiment.search_budget.proposal_limit,
        tuple(item.proposal_fingerprint for item in execution.proposals),
        execution.proposal_limit_reached,
        execution.search_space_exhausted,
    )


def enumerate_symbolic_executable_context(
    executable: OnlyExecutableSymbolicSearchContextV1,
) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1]:
    context = executable.historical_context
    execution = enumerate_symbolic_factor_proposals(
        context.verified_search_space,
        proposal_limit=context.experiment.search_budget.proposal_limit,
    )
    return execution, build_symbolic_enumeration_result(context.experiment, execution)


def certify_symbolic_enumeration_reproduction(
    context: OnlyVerifiedSymbolicSearchContextV1,
    store: OnlySymbolicHistoricalStore,
) -> OnlySymbolicEnumerationResultV1:
    """Admit current code, re-enumerate, and require equality with durable history."""

    executable = admit_current_symbolic_algorithm_runtime(context)
    _execution, reproduced = enumerate_symbolic_executable_context(executable)
    stored = load_symbolic_enumeration_result_historical_verified(context.experiment, context, store).result
    if reproduced != stored:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_REPRODUCTION_MISMATCH", stored.enumeration_result_fingerprint)
    return reproduced


__all__ = [name for name in globals() if name.startswith(("Only", "build_", "certify_", "enumerate_"))]
