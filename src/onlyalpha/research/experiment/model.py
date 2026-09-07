"""Immutable Search Experiment and Search Iteration provenance V1 values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint

SEARCH_EXPERIMENT_SCHEMA_VERSION = 1
SEARCH_EXPERIMENT_CONTEXT_SCHEMA_VERSION = 2
SEARCH_HYPOTHESIS_SCHEMA_VERSION = 1
SEARCH_ITERATION_PLAN_SCHEMA_VERSION = 1
SEARCH_ITERATION_RESULT_SCHEMA_VERSION = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlySearchHypothesisSourceKind(StrEnum):
    PUBLICATION = "PUBLICATION"
    PRIOR_EXPERIMENT = "PRIOR_EXPERIMENT"
    RESEARCH_NOTE = "RESEARCH_NOTE"


class OnlySearchRandomnessMode(StrEnum):
    NONE = "NONE"
    SEEDED = "SEEDED"


class OnlySearchDecisionMode(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    HUMAN = "HUMAN"
    MODEL_ASSISTED = "MODEL_ASSISTED"


class OnlySearchIterationDisposition(StrEnum):
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANDIDATE_BOUND = "CANDIDATE_BOUND"
    RESEARCH_EVIDENCE_RECORDED = "RESEARCH_EVIDENCE_RECORDED"
    QUALIFICATION_DECISION_RECORDED = "QUALIFICATION_DECISION_RECORDED"


class OnlySearchFailureCode(StrEnum):
    SEARCH_INVALID_PROPOSAL = "SEARCH_INVALID_PROPOSAL"
    SEARCH_BUDGET_EXHAUSTED = "SEARCH_BUDGET_EXHAUSTED"
    CANDIDATE_BINDING_FAILED = "CANDIDATE_BINDING_FAILED"
    RESEARCH_SUBMISSION_FAILED = "RESEARCH_SUBMISSION_FAILED"
    RESEARCH_EXECUTION_FAILED = "RESEARCH_EXECUTION_FAILED"
    RESEARCH_EVIDENCE_UNAVAILABLE = "RESEARCH_EVIDENCE_UNAVAILABLE"
    QUALIFICATION_NOT_ATTEMPTED = "QUALIFICATION_NOT_ATTEMPTED"
    QUALIFICATION_EXECUTION_FAILED = "QUALIFICATION_EXECUTION_FAILED"
    DECISION_PROVENANCE_INVALID = "DECISION_PROVENANCE_INVALID"


class OnlySearchCommitDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _optional_sha(value: object, context: str) -> str | None:
    return None if value is None else _sha(value, context)


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"{context} must be non-empty without whitespace")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be non-empty")
    return value


def _positive_integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context} must be a positive integer")
    return value


def _non_negative_integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - set(payload))}, "
            f"unknown={sorted(set(payload) - expected)}"
        )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _sha_tuple(values: object, context: str) -> tuple[str, ...]:
    return tuple(_sha(item, context) for item in _array(values, context))


@dataclass(frozen=True, slots=True, order=True)
class OnlySearchHypothesisSourceReferenceV1:
    source_kind: OnlySearchHypothesisSourceKind
    source_fingerprint: str
    schema_version: int = SEARCH_HYPOTHESIS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_HYPOTHESIS_SCHEMA_VERSION:
            raise ValueError("unsupported Search Hypothesis Source Reference schema")
        if not isinstance(self.source_kind, OnlySearchHypothesisSourceKind):
            raise ValueError("Search Hypothesis source kind is invalid")
        _sha(self.source_fingerprint, "Search Hypothesis source fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_kind": self.source_kind.value,
            "source_fingerprint": self.source_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchHypothesisSourceReferenceV1:
        _exact(payload, {"schema_version", "source_kind", "source_fingerprint"}, "Hypothesis Source Reference")
        return cls(
            OnlySearchHypothesisSourceKind(_string(payload["source_kind"], "source_kind")),
            _sha(payload["source_fingerprint"], "source_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchHypothesisV1:
    statement: str
    source_references: tuple[OnlySearchHypothesisSourceReferenceV1, ...] = ()
    schema_version: int = SEARCH_HYPOTHESIS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_HYPOTHESIS_SCHEMA_VERSION:
            raise ValueError("unsupported Search Hypothesis schema")
        _text(self.statement, "Search Hypothesis statement")
        if not isinstance(self.source_references, tuple) or any(
            not isinstance(item, OnlySearchHypothesisSourceReferenceV1) for item in self.source_references
        ):
            raise ValueError("Search Hypothesis source references are invalid")
        if len(self.source_references) != len(set(self.source_references)):
            raise ValueError("Search Hypothesis source references must be unique")

    @property
    def hypothesis_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.search-hypothesis", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "statement": self.statement,
            "source_references": [item.to_dict() for item in self.source_references],
        }
        if include_fingerprint:
            payload["hypothesis_fingerprint"] = self.hypothesis_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchHypothesisV1:
        _exact(
            payload,
            {"schema_version", "statement", "source_references", "hypothesis_fingerprint"},
            "Search Hypothesis",
        )
        hypothesis = cls(
            _string(payload["statement"], "statement"),
            tuple(
                OnlySearchHypothesisSourceReferenceV1.from_dict(_mapping(item, "source reference"))
                for item in _array(payload["source_references"], "source_references")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["hypothesis_fingerprint"] != hypothesis.hypothesis_fingerprint:
            raise ValueError("Search Hypothesis identity differs")
        return hypothesis


@dataclass(frozen=True, slots=True)
class OnlySearchAlgorithmBindingV1:
    algorithm_id: str
    algorithm_semantic_version: str
    implementation_fingerprint: str
    source_revision: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Algorithm Binding schema")
        _identifier(self.algorithm_id, "Search algorithm_id")
        _identifier(self.algorithm_semantic_version, "Search algorithm semantic version")
        _sha(self.implementation_fingerprint, "Search algorithm implementation fingerprint")
        _identifier(self.source_revision, "Search algorithm source revision")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "algorithm_id": self.algorithm_id,
            "algorithm_semantic_version": self.algorithm_semantic_version,
            "implementation_fingerprint": self.implementation_fingerprint,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchAlgorithmBindingV1:
        _exact(
            payload,
            {
                "schema_version",
                "algorithm_id",
                "algorithm_semantic_version",
                "implementation_fingerprint",
                "source_revision",
            },
            "Search Algorithm Binding",
        )
        return cls(
            _string(payload["algorithm_id"], "algorithm_id"),
            _string(payload["algorithm_semantic_version"], "algorithm_semantic_version"),
            _sha(payload["implementation_fingerprint"], "implementation_fingerprint"),
            _string(payload["source_revision"], "source_revision"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchSpaceReferenceV1:
    search_space_kind: str
    search_space_schema_version: int
    search_space_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Space Reference schema")
        _identifier(self.search_space_kind, "search_space_kind")
        _positive_integer(self.search_space_schema_version, "search_space_schema_version")
        _sha(self.search_space_fingerprint, "search_space_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "search_space_kind": self.search_space_kind,
            "search_space_schema_version": self.search_space_schema_version,
            "search_space_fingerprint": self.search_space_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchSpaceReferenceV1:
        _exact(
            payload,
            {"schema_version", "search_space_kind", "search_space_schema_version", "search_space_fingerprint"},
            "Search Space Reference",
        )
        return cls(
            _string(payload["search_space_kind"], "search_space_kind"),
            _integer(payload["search_space_schema_version"], "search_space_schema_version"),
            _sha(payload["search_space_fingerprint"], "search_space_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchEvaluationContextReferenceV1:
    evaluation_kind: str
    evaluation_schema_version: int
    evaluation_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Evaluation Context Reference schema")
        _identifier(self.evaluation_kind, "evaluation_kind")
        _positive_integer(self.evaluation_schema_version, "evaluation_schema_version")
        _sha(self.evaluation_fingerprint, "evaluation_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evaluation_kind": self.evaluation_kind,
            "evaluation_schema_version": self.evaluation_schema_version,
            "evaluation_fingerprint": self.evaluation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchEvaluationContextReferenceV1:
        _exact(
            payload,
            {"schema_version", "evaluation_kind", "evaluation_schema_version", "evaluation_fingerprint"},
            "Search Evaluation Context Reference",
        )
        return cls(
            _string(payload["evaluation_kind"], "evaluation_kind"),
            _integer(payload["evaluation_schema_version"], "evaluation_schema_version"),
            _sha(payload["evaluation_fingerprint"], "evaluation_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchBudgetV1:
    proposal_limit: int
    research_evaluation_limit: int
    qualification_attempt_limit: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Budget schema")
        _positive_integer(self.proposal_limit, "proposal_limit")
        _positive_integer(self.research_evaluation_limit, "research_evaluation_limit")
        _positive_integer(self.qualification_attempt_limit, "qualification_attempt_limit")

    def to_dict(self) -> dict[str, int]:
        return {
            "schema_version": self.schema_version,
            "proposal_limit": self.proposal_limit,
            "research_evaluation_limit": self.research_evaluation_limit,
            "qualification_attempt_limit": self.qualification_attempt_limit,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchBudgetV1:
        _exact(
            payload,
            {"schema_version", "proposal_limit", "research_evaluation_limit", "qualification_attempt_limit"},
            "Search Budget",
        )
        return cls(
            _integer(payload["proposal_limit"], "proposal_limit"),
            _integer(payload["research_evaluation_limit"], "research_evaluation_limit"),
            _integer(payload["qualification_attempt_limit"], "qualification_attempt_limit"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchWorkflowBindingV1:
    workflow_id: str
    workflow_semantic_version: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Workflow Binding schema")
        _identifier(self.workflow_id, "workflow_id")
        _identifier(self.workflow_semantic_version, "workflow_semantic_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_semantic_version": self.workflow_semantic_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchWorkflowBindingV1:
        _exact(payload, {"schema_version", "workflow_id", "workflow_semantic_version"}, "Workflow Binding")
        return cls(
            _string(payload["workflow_id"], "workflow_id"),
            _string(payload["workflow_semantic_version"], "workflow_semantic_version"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchDecisionEngineBindingV1:
    mode: OnlySearchDecisionMode
    model_provider_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    prompt_template_fingerprint: str | None = None
    tool_policy_fingerprint: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Decision Engine Binding schema")
        if not isinstance(self.mode, OnlySearchDecisionMode):
            raise ValueError("Search decision mode is invalid")
        model_values = (self.model_provider_id, self.model_id, self.model_version)
        fingerprint_values = (self.prompt_template_fingerprint, self.tool_policy_fingerprint)
        if self.mode is OnlySearchDecisionMode.MODEL_ASSISTED:
            for value, context in zip(model_values, ("model_provider_id", "model_id", "model_version"), strict=True):
                _identifier(value, context)
            for value, context in zip(
                fingerprint_values,
                ("prompt_template_fingerprint", "tool_policy_fingerprint"),
                strict=True,
            ):
                _sha(value, context)
        elif any(value is not None for value in (*model_values, *fingerprint_values)):
            raise ValueError("non-model Search decision mode cannot carry model provenance")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "model_provider_id": self.model_provider_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_template_fingerprint": self.prompt_template_fingerprint,
            "tool_policy_fingerprint": self.tool_policy_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchDecisionEngineBindingV1:
        _exact(
            payload,
            {
                "schema_version",
                "mode",
                "model_provider_id",
                "model_id",
                "model_version",
                "prompt_template_fingerprint",
                "tool_policy_fingerprint",
            },
            "Decision Engine Binding",
        )

        def optional_string(name: str) -> str | None:
            value = payload[name]
            return None if value is None else _string(value, name)

        return cls(
            OnlySearchDecisionMode(_string(payload["mode"], "mode")),
            optional_string("model_provider_id"),
            optional_string("model_id"),
            optional_string("model_version"),
            optional_string("prompt_template_fingerprint"),
            optional_string("tool_policy_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchExperimentManifestV1:
    hypothesis: OnlySearchHypothesisV1
    search_algorithm_binding: OnlySearchAlgorithmBindingV1
    search_space_reference: OnlySearchSpaceReferenceV1
    randomness_mode: OnlySearchRandomnessMode
    seed: int | None
    search_budget: OnlySearchBudgetV1
    catalog_generation_fingerprint: str
    dataset_snapshot_fingerprint: str
    workflow_binding: OnlySearchWorkflowBindingV1
    decision_engine_binding: OnlySearchDecisionEngineBindingV1
    parent_experiment_fingerprint: str | None = None
    schema_version: int = SEARCH_EXPERIMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_EXPERIMENT_SCHEMA_VERSION:
            raise ValueError("unsupported Search Experiment Manifest schema")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Search Experiment hypothesis is invalid")
        if not isinstance(self.search_algorithm_binding, OnlySearchAlgorithmBindingV1):
            raise ValueError("Search Experiment algorithm binding is invalid")
        if not isinstance(self.search_space_reference, OnlySearchSpaceReferenceV1):
            raise ValueError("Search Experiment search-space reference is invalid")
        if not isinstance(self.randomness_mode, OnlySearchRandomnessMode):
            raise ValueError("Search Experiment randomness mode is invalid")
        if self.randomness_mode is OnlySearchRandomnessMode.NONE:
            if self.seed is not None:
                raise ValueError("NONE randomness mode requires a null seed")
        elif isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("SEEDED randomness mode requires an exact integer seed")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Search Experiment budget is invalid")
        _sha(self.catalog_generation_fingerprint, "Catalog Generation fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "Dataset Snapshot fingerprint")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Search Experiment workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Search Experiment decision-engine binding is invalid")
        _optional_sha(self.parent_experiment_fingerprint, "parent Experiment fingerprint")

    @property
    def experiment_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.search-experiment", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "parent_experiment_fingerprint": self.parent_experiment_fingerprint,
            "hypothesis": self.hypothesis.to_dict(),
            "search_algorithm_binding": self.search_algorithm_binding.to_dict(),
            "search_space_reference": self.search_space_reference.to_dict(),
            "randomness_mode": self.randomness_mode.value,
            "seed": self.seed,
            "search_budget": self.search_budget.to_dict(),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "workflow_binding": self.workflow_binding.to_dict(),
            "decision_engine_binding": self.decision_engine_binding.to_dict(),
        }
        if include_fingerprint:
            payload["experiment_fingerprint"] = self.experiment_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchExperimentManifestV1:
        _exact(
            payload,
            {
                "schema_version",
                "parent_experiment_fingerprint",
                "hypothesis",
                "search_algorithm_binding",
                "search_space_reference",
                "randomness_mode",
                "seed",
                "search_budget",
                "catalog_generation_fingerprint",
                "dataset_snapshot_fingerprint",
                "workflow_binding",
                "decision_engine_binding",
                "experiment_fingerprint",
            },
            "Search Experiment Manifest",
        )
        seed = payload["seed"]
        experiment = cls(
            OnlySearchHypothesisV1.from_dict(_mapping(payload["hypothesis"], "hypothesis")),
            OnlySearchAlgorithmBindingV1.from_dict(
                _mapping(payload["search_algorithm_binding"], "search_algorithm_binding")
            ),
            OnlySearchSpaceReferenceV1.from_dict(_mapping(payload["search_space_reference"], "search_space_reference")),
            OnlySearchRandomnessMode(_string(payload["randomness_mode"], "randomness_mode")),
            None if seed is None else _integer(seed, "seed"),
            OnlySearchBudgetV1.from_dict(_mapping(payload["search_budget"], "search_budget")),
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            _sha(payload["dataset_snapshot_fingerprint"], "dataset_snapshot_fingerprint"),
            OnlySearchWorkflowBindingV1.from_dict(_mapping(payload["workflow_binding"], "workflow_binding")),
            OnlySearchDecisionEngineBindingV1.from_dict(
                _mapping(payload["decision_engine_binding"], "decision_engine_binding")
            ),
            _optional_sha(payload["parent_experiment_fingerprint"], "parent_experiment_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["experiment_fingerprint"] != experiment.experiment_fingerprint:
            raise ValueError("Search Experiment identity differs")
        return experiment


@dataclass(frozen=True, slots=True)
class OnlySearchExperimentManifestV2:
    """Forward-only Search Experiment contract with exact Evaluation binding."""

    hypothesis: OnlySearchHypothesisV1
    search_algorithm_binding: OnlySearchAlgorithmBindingV1
    search_space_reference: OnlySearchSpaceReferenceV1
    evaluation_context_reference: OnlySearchEvaluationContextReferenceV1
    randomness_mode: OnlySearchRandomnessMode
    seed: int | None
    search_budget: OnlySearchBudgetV1
    catalog_generation_fingerprint: str
    dataset_snapshot_fingerprint: str
    workflow_binding: OnlySearchWorkflowBindingV1
    decision_engine_binding: OnlySearchDecisionEngineBindingV1
    parent_experiment_fingerprint: str | None = None
    schema_version: int = SEARCH_EXPERIMENT_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_EXPERIMENT_CONTEXT_SCHEMA_VERSION:
            raise ValueError("unsupported Search Experiment Manifest V2 schema")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Search Experiment hypothesis is invalid")
        if not isinstance(self.search_algorithm_binding, OnlySearchAlgorithmBindingV1):
            raise ValueError("Search Experiment algorithm binding is invalid")
        if not isinstance(self.search_space_reference, OnlySearchSpaceReferenceV1):
            raise ValueError("Search Experiment search-space reference is invalid")
        if not isinstance(self.evaluation_context_reference, OnlySearchEvaluationContextReferenceV1):
            raise ValueError("Search Experiment evaluation-context reference is invalid")
        if not isinstance(self.randomness_mode, OnlySearchRandomnessMode):
            raise ValueError("Search Experiment randomness mode is invalid")
        if self.randomness_mode is OnlySearchRandomnessMode.NONE:
            if self.seed is not None:
                raise ValueError("NONE randomness mode requires a null seed")
        elif isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("SEEDED randomness mode requires an exact integer seed")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Search Experiment budget is invalid")
        _sha(self.catalog_generation_fingerprint, "Catalog Generation fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "Dataset Snapshot fingerprint")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Search Experiment workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Search Experiment decision-engine binding is invalid")
        _optional_sha(self.parent_experiment_fingerprint, "parent Experiment fingerprint")

    @property
    def experiment_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.search-experiment", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "parent_experiment_fingerprint": self.parent_experiment_fingerprint,
            "hypothesis": self.hypothesis.to_dict(),
            "search_algorithm_binding": self.search_algorithm_binding.to_dict(),
            "search_space_reference": self.search_space_reference.to_dict(),
            "evaluation_context_reference": self.evaluation_context_reference.to_dict(),
            "randomness_mode": self.randomness_mode.value,
            "seed": self.seed,
            "search_budget": self.search_budget.to_dict(),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "workflow_binding": self.workflow_binding.to_dict(),
            "decision_engine_binding": self.decision_engine_binding.to_dict(),
        }
        if include_fingerprint:
            payload["experiment_fingerprint"] = self.experiment_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchExperimentManifestV2:
        _exact(
            payload,
            {
                "schema_version",
                "parent_experiment_fingerprint",
                "hypothesis",
                "search_algorithm_binding",
                "search_space_reference",
                "evaluation_context_reference",
                "randomness_mode",
                "seed",
                "search_budget",
                "catalog_generation_fingerprint",
                "dataset_snapshot_fingerprint",
                "workflow_binding",
                "decision_engine_binding",
                "experiment_fingerprint",
            },
            "Search Experiment Manifest V2",
        )
        seed = payload["seed"]
        experiment = cls(
            OnlySearchHypothesisV1.from_dict(_mapping(payload["hypothesis"], "hypothesis")),
            OnlySearchAlgorithmBindingV1.from_dict(
                _mapping(payload["search_algorithm_binding"], "search_algorithm_binding")
            ),
            OnlySearchSpaceReferenceV1.from_dict(_mapping(payload["search_space_reference"], "search_space_reference")),
            OnlySearchEvaluationContextReferenceV1.from_dict(
                _mapping(payload["evaluation_context_reference"], "evaluation_context_reference")
            ),
            OnlySearchRandomnessMode(_string(payload["randomness_mode"], "randomness_mode")),
            None if seed is None else _integer(seed, "seed"),
            OnlySearchBudgetV1.from_dict(_mapping(payload["search_budget"], "search_budget")),
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            _sha(payload["dataset_snapshot_fingerprint"], "dataset_snapshot_fingerprint"),
            OnlySearchWorkflowBindingV1.from_dict(_mapping(payload["workflow_binding"], "workflow_binding")),
            OnlySearchDecisionEngineBindingV1.from_dict(
                _mapping(payload["decision_engine_binding"], "decision_engine_binding")
            ),
            _optional_sha(payload["parent_experiment_fingerprint"], "parent_experiment_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["experiment_fingerprint"] != experiment.experiment_fingerprint:
            raise ValueError("Search Experiment V2 identity differs")
        return experiment


OnlySearchExperimentManifest = OnlySearchExperimentManifestV1 | OnlySearchExperimentManifestV2


def only_search_experiment_manifest_from_dict(payload: Mapping[str, object]) -> OnlySearchExperimentManifest:
    version = _integer(payload.get("schema_version"), "schema_version")
    if version == SEARCH_EXPERIMENT_SCHEMA_VERSION:
        return OnlySearchExperimentManifestV1.from_dict(payload)
    if version == SEARCH_EXPERIMENT_CONTEXT_SCHEMA_VERSION:
        return OnlySearchExperimentManifestV2.from_dict(payload)
    raise ValueError("unsupported Search Experiment Manifest schema")


@dataclass(frozen=True, slots=True)
class OnlySearchIterationPlanV1:
    experiment_fingerprint: str
    iteration_index: int
    proposal_kind: str
    proposal_schema_version: int
    proposal_fingerprint: str
    decision_input_context_fingerprints: tuple[str, ...]
    decision_tool_result_fingerprints: tuple[str, ...]
    decision_output_fingerprint: str
    parent_iteration_result_fingerprint: str | None = None
    schema_version: int = SEARCH_ITERATION_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_ITERATION_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported Search Iteration Plan schema")
        _sha(self.experiment_fingerprint, "Search Experiment fingerprint")
        _non_negative_integer(self.iteration_index, "iteration_index")
        _identifier(self.proposal_kind, "proposal_kind")
        _positive_integer(self.proposal_schema_version, "proposal_schema_version")
        _sha(self.proposal_fingerprint, "proposal_fingerprint")
        for values, context in (
            (self.decision_input_context_fingerprints, "decision input-context fingerprints"),
            (self.decision_tool_result_fingerprints, "decision tool-result fingerprints"),
        ):
            if not isinstance(values, tuple):
                raise ValueError(f"{context} must be a tuple")
            for value in values:
                _sha(value, context)
        _sha(self.decision_output_fingerprint, "decision_output_fingerprint")
        _optional_sha(self.parent_iteration_result_fingerprint, "parent Iteration Result fingerprint")

    @property
    def iteration_plan_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.search-iteration-plan", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "iteration_index": self.iteration_index,
            "parent_iteration_result_fingerprint": self.parent_iteration_result_fingerprint,
            "proposal_kind": self.proposal_kind,
            "proposal_schema_version": self.proposal_schema_version,
            "proposal_fingerprint": self.proposal_fingerprint,
            "decision_input_context_fingerprints": list(self.decision_input_context_fingerprints),
            "decision_tool_result_fingerprints": list(self.decision_tool_result_fingerprints),
            "decision_output_fingerprint": self.decision_output_fingerprint,
        }
        if include_fingerprint:
            payload["iteration_plan_fingerprint"] = self.iteration_plan_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchIterationPlanV1:
        _exact(
            payload,
            {
                "schema_version",
                "experiment_fingerprint",
                "iteration_index",
                "parent_iteration_result_fingerprint",
                "proposal_kind",
                "proposal_schema_version",
                "proposal_fingerprint",
                "decision_input_context_fingerprints",
                "decision_tool_result_fingerprints",
                "decision_output_fingerprint",
                "iteration_plan_fingerprint",
            },
            "Search Iteration Plan",
        )
        plan = cls(
            _sha(payload["experiment_fingerprint"], "experiment_fingerprint"),
            _integer(payload["iteration_index"], "iteration_index"),
            _string(payload["proposal_kind"], "proposal_kind"),
            _integer(payload["proposal_schema_version"], "proposal_schema_version"),
            _sha(payload["proposal_fingerprint"], "proposal_fingerprint"),
            _sha_tuple(payload["decision_input_context_fingerprints"], "decision input-context fingerprint"),
            _sha_tuple(payload["decision_tool_result_fingerprints"], "decision tool-result fingerprint"),
            _sha(payload["decision_output_fingerprint"], "decision_output_fingerprint"),
            _optional_sha(payload["parent_iteration_result_fingerprint"], "parent_iteration_result_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["iteration_plan_fingerprint"] != plan.iteration_plan_fingerprint:
            raise ValueError("Search Iteration Plan identity differs")
        return plan


@dataclass(frozen=True, slots=True)
class OnlySearchResearchResultReferenceV1:
    """Exact canonical locator and resulting Research Evidence identity."""

    locator_fingerprint: str
    result_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Search Research Result Reference schema")
        _sha(self.locator_fingerprint, "Research Result locator fingerprint")
        _sha(self.result_fingerprint, "Research Result identity fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "locator_fingerprint": self.locator_fingerprint,
            "result_fingerprint": self.result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchResearchResultReferenceV1:
        _exact(
            payload,
            {"schema_version", "locator_fingerprint", "result_fingerprint"},
            "Search Research Result Reference",
        )
        return cls(
            _sha(payload["locator_fingerprint"], "locator_fingerprint"),
            _sha(payload["result_fingerprint"], "result_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlySearchIterationResultV1:
    iteration_plan_fingerprint: str
    candidate_fingerprint: str | None
    research_attempted: bool
    research_result_reference: OnlySearchResearchResultReferenceV1 | None
    qualification_attempted: bool
    qualification_decision_fingerprint: str | None
    disposition: OnlySearchIterationDisposition
    failure_code: OnlySearchFailureCode | None
    schema_version: int = SEARCH_ITERATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_ITERATION_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported Search Iteration Result schema")
        _sha(self.iteration_plan_fingerprint, "Search Iteration Plan fingerprint")
        _optional_sha(self.candidate_fingerprint, "Candidate fingerprint")
        if not isinstance(self.research_attempted, bool) or not isinstance(self.qualification_attempted, bool):
            raise ValueError("Search Iteration attempted flags must be booleans")
        if self.research_result_reference is not None and not isinstance(
            self.research_result_reference, OnlySearchResearchResultReferenceV1
        ):
            raise ValueError("Search Research Result reference is invalid")
        _optional_sha(self.qualification_decision_fingerprint, "Qualification Decision fingerprint")
        if not isinstance(self.disposition, OnlySearchIterationDisposition):
            raise ValueError("Search Iteration disposition is invalid")
        if self.failure_code is not None and not isinstance(self.failure_code, OnlySearchFailureCode):
            raise ValueError("Search Iteration failure code is invalid")
        if self.research_result_reference is not None and not self.research_attempted:
            raise ValueError("Research Result reference requires research_attempted")
        if self.qualification_decision_fingerprint is not None and not self.qualification_attempted:
            raise ValueError("Qualification Decision reference requires qualification_attempted")
        if self.research_attempted and self.candidate_fingerprint is None:
            raise ValueError("Research attempt requires a Candidate binding")
        if self.qualification_attempted and (
            self.candidate_fingerprint is None or not self.research_attempted or self.research_result_reference is None
        ):
            raise ValueError("Qualification attempt requires exact Candidate and Research Result bindings")
        if self.failure_code is OnlySearchFailureCode.QUALIFICATION_NOT_ATTEMPTED and self.qualification_attempted:
            raise ValueError("QUALIFICATION_NOT_ATTEMPTED contradicts qualification_attempted")
        if self.qualification_attempted and self.qualification_decision_fingerprint is None:
            if self.failure_code is not OnlySearchFailureCode.QUALIFICATION_EXECUTION_FAILED:
                raise ValueError("failed Qualification attempt requires QUALIFICATION_EXECUTION_FAILED")
        if (
            self.failure_code is OnlySearchFailureCode.QUALIFICATION_EXECUTION_FAILED
            and not self.qualification_attempted
        ):
            raise ValueError("QUALIFICATION_EXECUTION_FAILED requires qualification_attempted")
        if self.research_attempted and self.research_result_reference is None and not self.qualification_attempted:
            if self.failure_code is not OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED:
                raise ValueError("failed Research attempt requires RESEARCH_EXECUTION_FAILED")
        if self.disposition in {OnlySearchIterationDisposition.SKIPPED, OnlySearchIterationDisposition.FAILED}:
            if self.failure_code is None:
                raise ValueError("failed/skipped Search Iteration requires a failure code")
            if self.disposition is OnlySearchIterationDisposition.SKIPPED and any(
                (
                    self.candidate_fingerprint is not None,
                    self.research_attempted,
                    self.research_result_reference is not None,
                    self.qualification_attempted,
                    self.qualification_decision_fingerprint is not None,
                )
            ):
                raise ValueError("skipped Search Iteration cannot contain execution bindings")
            if (
                self.disposition is OnlySearchIterationDisposition.FAILED
                and self.qualification_decision_fingerprint is not None
            ):
                raise ValueError("failed Search Iteration cannot contain a completed Qualification Decision")
        elif self.failure_code is not None:
            raise ValueError("successful Search Iteration disposition cannot contain a failure code")
        if self.disposition is OnlySearchIterationDisposition.CANDIDATE_BOUND and (
            self.candidate_fingerprint is None
            or self.research_attempted
            or self.research_result_reference is not None
            or self.qualification_attempted
            or self.qualification_decision_fingerprint is not None
        ):
            raise ValueError("CANDIDATE_BOUND disposition is inconsistent")
        if self.disposition is OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED and (
            self.candidate_fingerprint is None
            or not self.research_attempted
            or self.research_result_reference is None
            or self.qualification_attempted
            or self.qualification_decision_fingerprint is not None
        ):
            raise ValueError("RESEARCH_EVIDENCE_RECORDED disposition is inconsistent")
        if self.disposition is OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED and (
            self.candidate_fingerprint is None
            or not self.research_attempted
            or self.research_result_reference is None
            or not self.qualification_attempted
            or self.qualification_decision_fingerprint is None
        ):
            raise ValueError("QUALIFICATION_DECISION_RECORDED disposition is inconsistent")

    @property
    def iteration_result_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.search-iteration-result", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "iteration_plan_fingerprint": self.iteration_plan_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "research_attempted": self.research_attempted,
            "research_result_reference": (
                None if self.research_result_reference is None else self.research_result_reference.to_dict()
            ),
            "qualification_attempted": self.qualification_attempted,
            "qualification_decision_fingerprint": self.qualification_decision_fingerprint,
            "disposition": self.disposition.value,
            "failure_code": None if self.failure_code is None else self.failure_code.value,
        }
        if include_fingerprint:
            payload["iteration_result_fingerprint"] = self.iteration_result_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySearchIterationResultV1:
        _exact(
            payload,
            {
                "schema_version",
                "iteration_plan_fingerprint",
                "candidate_fingerprint",
                "research_attempted",
                "research_result_reference",
                "qualification_attempted",
                "qualification_decision_fingerprint",
                "disposition",
                "failure_code",
                "iteration_result_fingerprint",
            },
            "Search Iteration Result",
        )
        failure_code = payload["failure_code"]
        result = cls(
            _sha(payload["iteration_plan_fingerprint"], "iteration_plan_fingerprint"),
            _optional_sha(payload["candidate_fingerprint"], "candidate_fingerprint"),
            _boolean(payload["research_attempted"], "research_attempted"),
            None
            if payload["research_result_reference"] is None
            else OnlySearchResearchResultReferenceV1.from_dict(
                _mapping(payload["research_result_reference"], "research_result_reference")
            ),
            _boolean(payload["qualification_attempted"], "qualification_attempted"),
            _optional_sha(payload["qualification_decision_fingerprint"], "qualification_decision_fingerprint"),
            OnlySearchIterationDisposition(_string(payload["disposition"], "disposition")),
            None if failure_code is None else OnlySearchFailureCode(_string(failure_code, "failure_code")),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["iteration_result_fingerprint"] != result.iteration_result_fingerprint:
            raise ValueError("Search Iteration Result identity differs")
        return result


@dataclass(frozen=True, slots=True)
class OnlySearchCommitOutcome:
    disposition: OnlySearchCommitDisposition
    fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, OnlySearchCommitDisposition):
            raise ValueError("Search provenance commit disposition is invalid")
        _sha(self.fingerprint, "Search provenance commit fingerprint")


__all__ = [name for name in globals() if name.startswith(("OnlySearch", "SEARCH_"))]
