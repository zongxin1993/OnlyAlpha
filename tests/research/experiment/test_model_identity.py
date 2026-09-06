from __future__ import annotations

from dataclasses import fields, replace

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV1,
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
    OnlySearchRandomnessMode,
)
from onlyalpha.research.specification.identity import only_research_candidate_fingerprint

from .support import experiment, fingerprint, plan


def test_experiment_identity_is_deterministic_and_round_trips() -> None:
    value = experiment()
    assert value.experiment_fingerprint == experiment().experiment_fingerprint
    assert OnlySearchExperimentManifestV1.from_dict(value.to_dict()) == value


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        (
            "search_algorithm_binding",
            OnlySearchAlgorithmBindingV1("deterministic.enumeration", "2", fingerprint("2"), "revision-1"),
        ),
        (
            "search_algorithm_binding",
            OnlySearchAlgorithmBindingV1("deterministic.enumeration", "1", fingerprint("c"), "revision-1"),
        ),
        ("seed", 18),
        ("search_budget", OnlySearchBudgetV1(11, 8, 4)),
        ("catalog_generation_fingerprint", fingerprint("d")),
        ("dataset_snapshot_fingerprint", fingerprint("e")),
    ),
)
def test_each_experiment_binding_changes_identity(field: str, replacement: object) -> None:
    original = experiment()
    changed = replace(original, **{field: replacement})  # type: ignore[arg-type]
    assert changed.experiment_fingerprint != original.experiment_fingerprint


def test_search_space_and_decision_configuration_change_identity() -> None:
    original = experiment()
    changed_space = replace(
        original.search_space_reference,
        search_space_fingerprint=fingerprint("f"),
    )
    model = OnlySearchDecisionEngineBindingV1(
        OnlySearchDecisionMode.MODEL_ASSISTED,
        "provider",
        "model",
        "2026-09",
        fingerprint("c"),
        fingerprint("d"),
    )
    assert (
        replace(original, search_space_reference=changed_space).experiment_fingerprint
        != original.experiment_fingerprint
    )
    assert replace(original, decision_engine_binding=model).experiment_fingerprint != original.experiment_fingerprint


def test_search_experiment_identity_domain_is_not_candidate_or_authoring_payload() -> None:
    value = experiment()
    candidate = only_research_candidate_fingerprint(
        fingerprint("1"),
        "factor",
        {},
        fingerprint("2"),
    )
    assert value.experiment_fingerprint != candidate
    with pytest.raises(ValueError, match="fields are invalid"):
        OnlySearchExperimentManifestV1.from_dict(
            {
                "schema_version": 1,
                "source_repository": "private",
                "source_revision": "abc",
                "experiment_fingerprint": value.experiment_fingerprint,
            }
        )
    assert value.experiment_fingerprint != only_canonical_fingerprint(
        {"domain": "onlyalpha.private.authoring-experiment", **value.to_dict(include_fingerprint=False)}
    )


@pytest.mark.parametrize(
    ("mode", "seed"),
    (
        (OnlySearchRandomnessMode.NONE, 1),
        (OnlySearchRandomnessMode.SEEDED, None),
        (OnlySearchRandomnessMode.SEEDED, True),
    ),
)
def test_randomness_contract_rejects_invalid_seed(mode: OnlySearchRandomnessMode, seed: int | None) -> None:
    with pytest.raises(ValueError):
        experiment(randomness_mode=mode, seed=seed)


def test_randomness_none_and_seeded_are_explicit() -> None:
    assert experiment(randomness_mode=OnlySearchRandomnessMode.NONE, seed=None).seed is None
    assert experiment().seed == 17


@pytest.mark.parametrize("value", (0, -1, True))
@pytest.mark.parametrize("field", ("proposal_limit", "research_evaluation_limit", "qualification_attempt_limit"))
def test_budget_rejects_non_positive_and_boolean_values(field: str, value: int) -> None:
    values = {"proposal_limit": 1, "research_evaluation_limit": 1, "qualification_attempt_limit": 1}
    values[field] = value
    with pytest.raises(ValueError, match="positive integer"):
        OnlySearchBudgetV1(**values)


def test_budget_round_trip_preserves_distinct_dimensions() -> None:
    budget = OnlySearchBudgetV1(3, 5, 7)
    assert OnlySearchBudgetV1.from_dict(budget.to_dict()) == budget


def test_model_assisted_requires_all_exact_model_bindings() -> None:
    with pytest.raises(ValueError):
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.MODEL_ASSISTED)
    with pytest.raises(ValueError):
        OnlySearchDecisionEngineBindingV1(
            OnlySearchDecisionMode.MODEL_ASSISTED,
            "provider",
            "model",
            "version",
            fingerprint("1"),
            None,
        )
    assert OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC).model_id is None


def test_ordered_decision_references_and_output_are_identity_bound() -> None:
    value = plan(experiment().experiment_fingerprint)
    reversed_inputs = replace(
        value,
        decision_input_context_fingerprints=tuple(reversed(value.decision_input_context_fingerprints)),
    )
    reversed_tools = replace(
        value,
        decision_tool_result_fingerprints=tuple(reversed(value.decision_tool_result_fingerprints)),
    )
    changed_output = replace(value, decision_output_fingerprint=fingerprint("c"))
    assert (
        len(
            {
                value.iteration_plan_fingerprint,
                reversed_inputs.iteration_plan_fingerprint,
                reversed_tools.iteration_plan_fingerprint,
                changed_output.iteration_plan_fingerprint,
            }
        )
        == 4
    )


def test_repeated_proposal_is_a_distinct_iteration_occurrence() -> None:
    experiment_fingerprint = experiment().experiment_fingerprint
    first = plan(experiment_fingerprint, 0)
    second = plan(experiment_fingerprint, 1)
    assert first.proposal_fingerprint == second.proposal_fingerprint
    assert first.iteration_plan_fingerprint != second.iteration_plan_fingerprint


def test_iteration_result_identity_and_failure_without_candidate() -> None:
    plan_fingerprint = plan(experiment().experiment_fingerprint).iteration_plan_fingerprint
    failed = OnlySearchIterationResultV1(
        plan_fingerprint,
        None,
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.FAILED,
        OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
    )
    assert OnlySearchIterationResultV1.from_dict(failed.to_dict()) == failed
    assert failed.iteration_result_fingerprint == replace(failed).iteration_result_fingerprint


def test_result_disposition_rejects_inconsistent_authority_references() -> None:
    plan_fingerprint = plan(experiment().experiment_fingerprint).iteration_plan_fingerprint
    with pytest.raises(ValueError, match="Research Result reference"):
        OnlySearchIterationResultV1(
            plan_fingerprint,
            fingerprint("1"),
            False,
            fingerprint("2"),
            False,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
        )
    with pytest.raises(ValueError, match="failure code"):
        OnlySearchIterationResultV1(
            plan_fingerprint,
            fingerprint("1"),
            False,
            None,
            False,
            None,
            OnlySearchIterationDisposition.CANDIDATE_BOUND,
            OnlySearchFailureCode.QUALIFICATION_NOT_ATTEMPTED,
        )


def test_formal_models_contain_no_second_truth_or_chain_of_thought_fields() -> None:
    names = {
        field.name for model in (OnlySearchExperimentManifestV1, OnlySearchIterationResultV1) for field in fields(model)
    }
    forbidden = {
        "chain_of_thought",
        "hidden_reasoning",
        "ic",
        "rank_ic",
        "information_ratio",
        "coverage",
        "stability_score",
        "correlation_score",
        "sharpe",
        "generic_score",
        "qualification_outcome",
        "approved",
        "factor_status",
        "production_factor",
        "approved_factor",
        "best_factor",
        "active_factor",
        "created_at",
        "filesystem_path",
        "hostname",
    }
    assert names.isdisjoint(forbidden)
