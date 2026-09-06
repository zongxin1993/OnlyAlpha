from __future__ import annotations

from dataclasses import replace

from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV1,
    OnlySearchHypothesisSourceKind,
    OnlySearchHypothesisSourceReferenceV1,
    OnlySearchHypothesisV1,
    OnlySearchIterationPlanV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)


def fingerprint(character: str) -> str:
    return character * 64


def hypothesis() -> OnlySearchHypothesisV1:
    return OnlySearchHypothesisV1(
        "Short-term reversal is stronger after abnormal volume.",
        (
            OnlySearchHypothesisSourceReferenceV1(
                OnlySearchHypothesisSourceKind.RESEARCH_NOTE,
                fingerprint("1"),
            ),
        ),
    )


def experiment(**changes: object) -> OnlySearchExperimentManifestV1:
    value = OnlySearchExperimentManifestV1(
        hypothesis(),
        OnlySearchAlgorithmBindingV1("deterministic.enumeration", "1", fingerprint("2"), "revision-1"),
        OnlySearchSpaceReferenceV1("SYMBOLIC_FACTOR_GRAPH", 1, fingerprint("3")),
        OnlySearchRandomnessMode.SEEDED,
        17,
        OnlySearchBudgetV1(10, 8, 4),
        fingerprint("4"),
        fingerprint("5"),
        OnlySearchWorkflowBindingV1("search.workflow", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )
    return replace(value, **changes)  # type: ignore[arg-type]


def plan(
    experiment_fingerprint: str,
    iteration_index: int = 0,
    **changes: object,
) -> OnlySearchIterationPlanV1:
    value = OnlySearchIterationPlanV1(
        experiment_fingerprint,
        iteration_index,
        "SYMBOLIC_FACTOR_GRAPH",
        1,
        fingerprint("6"),
        (fingerprint("7"), fingerprint("8")),
        (fingerprint("9"), fingerprint("a")),
        fingerprint("b"),
    )
    return replace(value, **changes)  # type: ignore[arg-type]
