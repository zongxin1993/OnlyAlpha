from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from onlyalpha.research.experiment import (
    OnlySearchExperimentManifestV1,
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchProvenanceError,
    verify_search_iteration_lineage,
)

from .support import experiment, plan


class MemoryProvenance:
    def __init__(self) -> None:
        self.experiments: dict[str, OnlySearchExperimentManifestV1] = {}
        self.plans: dict[str, OnlySearchIterationPlanV1] = {}
        self.results: dict[str, OnlySearchIterationResultV1] = {}

    def load_experiment_verified(self, fingerprint: str) -> OnlySearchExperimentManifestV1:
        return self.experiments[fingerprint]

    def load_iteration_plan_verified(self, fingerprint: str) -> OnlySearchIterationPlanV1:
        return self.plans[fingerprint]

    def load_iteration_result_verified(self, fingerprint: str) -> OnlySearchIterationResultV1:
        return self.results[fingerprint]

    def add_experiment(self, value: OnlySearchExperimentManifestV1) -> None:
        self.experiments[value.experiment_fingerprint] = value

    def add_plan(self, value: OnlySearchIterationPlanV1) -> None:
        self.plans[value.iteration_plan_fingerprint] = value

    def add_result(self, value: OnlySearchIterationResultV1) -> None:
        self.results[value.iteration_result_fingerprint] = value


def result(value: OnlySearchIterationPlanV1) -> OnlySearchIterationResultV1:
    return OnlySearchIterationResultV1(
        value.iteration_plan_fingerprint,
        None,
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.FAILED,
        OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
    )


def test_root_linear_and_branching_lineage_are_valid() -> None:
    memory = MemoryProvenance()
    search = experiment()
    memory.add_experiment(search)
    root = plan(search.experiment_fingerprint, 0)
    verify_search_iteration_lineage(root, experiments=memory, plans=memory, results=memory)
    memory.add_plan(root)
    root_result = result(root)
    memory.add_result(root_result)
    first_branch = plan(
        search.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint=root_result.iteration_result_fingerprint,
    )
    second_branch = plan(
        search.experiment_fingerprint,
        2,
        parent_iteration_result_fingerprint=root_result.iteration_result_fingerprint,
    )
    verify_search_iteration_lineage(first_branch, experiments=memory, plans=memory, results=memory)
    verify_search_iteration_lineage(second_branch, experiments=memory, plans=memory, results=memory)
    memory.add_plan(first_branch)
    first_result = result(first_branch)
    memory.add_result(first_result)
    third = plan(
        search.experiment_fingerprint,
        3,
        parent_iteration_result_fingerprint=first_result.iteration_result_fingerprint,
    )
    verify_search_iteration_lineage(third, experiments=memory, plans=memory, results=memory)


def test_unknown_or_unterminated_parent_is_rejected() -> None:
    memory = MemoryProvenance()
    search = experiment()
    memory.add_experiment(search)
    child = plan(
        search.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint="c" * 64,
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_PARENT_INVALID"):
        verify_search_iteration_lineage(child, experiments=memory, plans=memory, results=memory)
    parent_plan = plan(search.experiment_fingerprint, 0)
    memory.add_plan(parent_plan)
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_PARENT_INVALID"):
        verify_search_iteration_lineage(child, experiments=memory, plans=memory, results=memory)


def test_cross_experiment_parent_is_rejected() -> None:
    memory = MemoryProvenance()
    first = experiment()
    second = replace(first, seed=99)
    memory.add_experiment(first)
    memory.add_experiment(second)
    parent = plan(first.experiment_fingerprint, 0)
    memory.add_plan(parent)
    parent_result = result(parent)
    memory.add_result(parent_result)
    child = plan(
        second.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint=parent_result.iteration_result_fingerprint,
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_CROSS_EXPERIMENT_PARENT"):
        verify_search_iteration_lineage(child, experiments=memory, plans=memory, results=memory)


def test_self_parent_and_cycle_are_rejected_even_for_hostile_readers() -> None:
    class HostileResult:
        def __init__(self, fingerprint: str, plan_fingerprint: str) -> None:
            self.iteration_result_fingerprint = fingerprint
            self.iteration_plan_fingerprint = plan_fingerprint

    memory = MemoryProvenance()
    search = experiment()
    memory.add_experiment(search)
    candidate = plan(search.experiment_fingerprint, 1, parent_iteration_result_fingerprint="d" * 64)
    memory.results["d" * 64] = cast(
        OnlySearchIterationResultV1,
        HostileResult("d" * 64, candidate.iteration_plan_fingerprint),
    )
    memory.plans[candidate.iteration_plan_fingerprint] = candidate
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_SELF_PARENT"):
        verify_search_iteration_lineage(candidate, experiments=memory, plans=memory, results=memory)

    first = plan(search.experiment_fingerprint, 2, parent_iteration_result_fingerprint="f" * 64)
    second = plan(search.experiment_fingerprint, 3, parent_iteration_result_fingerprint="e" * 64)
    memory.results["e" * 64] = cast(
        OnlySearchIterationResultV1,
        HostileResult("e" * 64, second.iteration_plan_fingerprint),
    )
    memory.results["f" * 64] = cast(
        OnlySearchIterationResultV1,
        HostileResult("f" * 64, first.iteration_plan_fingerprint),
    )
    memory.plans[first.iteration_plan_fingerprint] = first
    memory.plans[second.iteration_plan_fingerprint] = second
    outside = plan(search.experiment_fingerprint, 4, parent_iteration_result_fingerprint="e" * 64)
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_LINEAGE_CYCLE"):
        verify_search_iteration_lineage(outside, experiments=memory, plans=memory, results=memory)
