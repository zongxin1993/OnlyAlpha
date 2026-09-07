"""Immutable B3.3 parameter-search authority contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation.definition import (
    OnlyCalculationScalar,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.sweep.definition import (
    OnlyResearchSweepDefinition,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
)
from onlyalpha.research.sweep.materialization import OnlyResearchGraphTemplateMaterializer
from onlyalpha.research.sweep.planning import OnlyResearchSweepPlanner

PARAMETER_SEARCH_SPACE_KIND = "ONLY_PARAMETER_FACTOR_SEARCH_SPACE"
PARAMETER_SEARCH_SPACE_SCHEMA_VERSION = 1
PARAMETER_PROPOSAL_KIND = "ONLY_PARAMETER_GRAPH_PROPOSAL"
PARAMETER_PROPOSAL_SCHEMA_VERSION = 1
PARAMETER_SEARCH_POLICY_KIND = "ONLY_PARAMETER_SEARCH_POLICY"
PARAMETER_SEARCH_POLICY_SCHEMA_VERSION = 1
PARAMETER_FEEDBACK_DECISION_SCHEMA_VERSION = 1
DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID = "DETERMINISTIC_COARSE_TO_FINE"
DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION = "1"

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"{context} must be non-empty without whitespace")
    return value


def _positive(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context} must be a positive integer")
    return value


def _non_negative(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{context} fields are invalid")


@dataclass(frozen=True, slots=True, order=True)
class OnlyParameterAssignmentValueV1:
    target: OnlyResearchSweepParameterTarget
    value: OnlyCalculationScalar

    def __post_init__(self) -> None:
        if not isinstance(self.target, OnlyResearchSweepParameterTarget):
            raise ValueError("Parameter assignment target is invalid")
        only_calculation_scalar_from_dict(only_calculation_scalar_to_dict(self.value), "Parameter assignment")

    def to_dict(self) -> dict[str, object]:
        return {"target": dict(self.target.to_dict()), "value": dict(only_calculation_scalar_to_dict(self.value))}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterAssignmentValueV1:
        _exact(payload, {"target", "value"}, "Parameter assignment")
        return cls(
            OnlyResearchSweepParameterTarget.from_dict(_mapping(payload["target"], "assignment target")),
            only_calculation_scalar_from_dict(payload["value"], "Parameter assignment"),
        )


@dataclass(frozen=True, slots=True)
class OnlyParameterFactorSearchSpaceV1:
    catalog_generation_fingerprint: str
    sweep_definition: OnlyResearchSweepDefinition
    candidate_template_node_id: str
    candidate_output_name: str
    schema_version: int = PARAMETER_SEARCH_SPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARAMETER_SEARCH_SPACE_SCHEMA_VERSION:
            raise ValueError("PARAMETER_SEARCH_SPACE_SCHEMA_UNSUPPORTED")
        _sha(self.catalog_generation_fingerprint, "Catalog Generation fingerprint")
        if not isinstance(self.sweep_definition, OnlyResearchSweepDefinition):
            raise ValueError("PARAMETER_SEARCH_SPACE_DEFINITION_INVALID")
        _identifier(self.candidate_template_node_id, "candidate template node")
        _identifier(self.candidate_output_name, "candidate output")
        if self.candidate_template_node_id not in {
            item.template_node_id for item in self.sweep_definition.graph_template.nodes
        }:
            raise ValueError("PARAMETER_SEARCH_CANDIDATE_NODE_MISSING")

    @classmethod
    def from_sweep(
        cls,
        *,
        catalog_generation_fingerprint: str,
        sweep_definition: OnlyResearchSweepDefinition,
        candidate_template_node_id: str,
        candidate_output_name: str,
        calculation_registry: object,
    ) -> OnlyParameterFactorSearchSpaceV1:
        plan = OnlyResearchSweepPlanner(calculation_registry).plan(sweep_definition)  # type: ignore[arg-type]
        dimensions = []
        for original in sweep_definition.dimensions:
            values = tuple(
                dict(cell.assignment_by_key)[original.target.key]
                for cell in plan.cells
                if original.target.key in cell.assignment_by_key
            )
            unique = tuple(dict.fromkeys(values))
            dimensions.append(OnlyResearchSweepParameterDimension(original.target, unique))
        normalized = OnlyResearchSweepDefinition(
            sweep_definition.dataset_snapshot_fingerprint,
            sweep_definition.graph_template,
            tuple(dimensions),
        )
        OnlyResearchSweepPlanner(calculation_registry).plan(normalized)  # type: ignore[arg-type]
        return cls(
            catalog_generation_fingerprint,
            normalized,
            candidate_template_node_id,
            candidate_output_name,
        )

    @property
    def search_space_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.parameter-search-space", **self.to_dict(include_fingerprint=False)}
        )

    @property
    def cardinality(self) -> int:
        result = 1
        for dimension in self.sweep_definition.dimensions:
            result *= len(dimension.candidates)
        return result

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "sweep_definition": dict(self.sweep_definition.to_dict()),
            "candidate_template_node_id": self.candidate_template_node_id,
            "candidate_output_name": self.candidate_output_name,
        }
        if include_fingerprint:
            payload["search_space_fingerprint"] = self.search_space_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterFactorSearchSpaceV1:
        _exact(
            payload,
            {
                "schema_version",
                "catalog_generation_fingerprint",
                "sweep_definition",
                "candidate_template_node_id",
                "candidate_output_name",
                "search_space_fingerprint",
            },
            "Parameter Search Space",
        )
        value = cls(
            _sha(payload["catalog_generation_fingerprint"], "catalog_generation_fingerprint"),
            OnlyResearchSweepDefinition.from_dict(_mapping(payload["sweep_definition"], "sweep definition")),
            _identifier(payload["candidate_template_node_id"], "candidate_template_node_id"),
            _identifier(payload["candidate_output_name"], "candidate_output_name"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["search_space_fingerprint"] != value.search_space_fingerprint:
            raise ValueError("PARAMETER_SEARCH_SPACE_IDENTITY_MISMATCH")
        return value


@dataclass(frozen=True, slots=True)
class OnlyParameterGraphProposalV1:
    search_space_fingerprint: str
    assignment: tuple[OnlyParameterAssignmentValueV1, ...]
    graph: OnlyCalculationGraphDefinition
    candidate_node_fingerprint: str
    candidate_output_name: str
    ordinal: int
    schema_version: int = PARAMETER_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARAMETER_PROPOSAL_SCHEMA_VERSION:
            raise ValueError("PARAMETER_PROPOSAL_SCHEMA_UNSUPPORTED")
        _sha(self.search_space_fingerprint, "Search Space fingerprint")
        if not self.assignment or tuple(sorted(self.assignment, key=lambda item: item.target.key)) != self.assignment:
            raise ValueError("PARAMETER_PROPOSAL_ASSIGNMENT_INVALID")
        if len({item.target for item in self.assignment}) != len(self.assignment):
            raise ValueError("PARAMETER_PROPOSAL_ASSIGNMENT_DUPLICATE")
        if not isinstance(self.graph, OnlyCalculationGraphDefinition):
            raise ValueError("PARAMETER_PROPOSAL_GRAPH_INVALID")
        _sha(self.candidate_node_fingerprint, "candidate node fingerprint")
        _identifier(self.candidate_output_name, "candidate output")
        _non_negative(self.ordinal, "proposal ordinal")
        node = next((item for item in self.graph.nodes if item.fingerprint == self.candidate_node_fingerprint), None)
        if node is None or self.candidate_output_name not in {item.name for item in node.definition.outputs}:
            raise ValueError("PARAMETER_PROPOSAL_CANDIDATE_OUTPUT_INVALID")

    @property
    def graph_fingerprint(self) -> str:
        return self.graph.fingerprint

    @property
    def proposal_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.parameter-proposal", **self.to_dict(include_fingerprint=False)}
        )

    @property
    def assignment_by_key(self) -> Mapping[str, OnlyCalculationScalar]:
        return MappingProxyType({item.target.key: item.value for item in self.assignment})

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "search_space_fingerprint": self.search_space_fingerprint,
            "assignment": [item.to_dict() for item in self.assignment],
            "graph": self.graph.to_dict(),
            "candidate_node_fingerprint": self.candidate_node_fingerprint,
            "candidate_output_name": self.candidate_output_name,
            "ordinal": self.ordinal,
        }
        if include_fingerprint:
            payload["proposal_fingerprint"] = self.proposal_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterGraphProposalV1:
        _exact(
            payload,
            {
                "schema_version",
                "search_space_fingerprint",
                "assignment",
                "graph",
                "candidate_node_fingerprint",
                "candidate_output_name",
                "ordinal",
                "proposal_fingerprint",
            },
            "Parameter Proposal",
        )
        value = cls(
            _sha(payload["search_space_fingerprint"], "search_space_fingerprint"),
            tuple(
                OnlyParameterAssignmentValueV1.from_dict(_mapping(item, "assignment"))
                for item in _array(payload["assignment"], "assignment")
            ),
            OnlyCalculationGraphDefinition.from_dict(_mapping(payload["graph"], "graph")),
            _sha(payload["candidate_node_fingerprint"], "candidate_node_fingerprint"),
            _identifier(payload["candidate_output_name"], "candidate_output_name"),
            _non_negative(payload["ordinal"], "ordinal"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["proposal_fingerprint"] != value.proposal_fingerprint:
            raise ValueError("PARAMETER_PROPOSAL_IDENTITY_MISMATCH")
        return value


class OnlyParameterObjectiveDirection(StrEnum):
    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


class OnlyParameterConstraintOperator(StrEnum):
    GE = "GE"
    LE = "LE"
    GT = "GT"
    LT = "LT"


@dataclass(frozen=True, slots=True, order=True)
class OnlyParameterMetricConstraintV1:
    metric_id: str
    operator: OnlyParameterConstraintOperator
    threshold: Decimal

    def __post_init__(self) -> None:
        _identifier(self.metric_id, "constraint metric")
        if not isinstance(self.operator, OnlyParameterConstraintOperator):
            raise ValueError("PARAMETER_POLICY_CONSTRAINT_INVALID")
        if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite():
            raise ValueError("PARAMETER_POLICY_CONSTRAINT_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {"metric_id": self.metric_id, "operator": self.operator.value, "threshold": str(self.threshold)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterMetricConstraintV1:
        _exact(payload, {"metric_id", "operator", "threshold"}, "Metric constraint")
        return cls(
            _identifier(payload["metric_id"], "metric_id"),
            OnlyParameterConstraintOperator(str(payload["operator"])),
            Decimal(str(payload["threshold"])),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyParameterTieBreakerV1:
    metric_id: str
    direction: OnlyParameterObjectiveDirection

    def __post_init__(self) -> None:
        _identifier(self.metric_id, "tie-breaker metric")
        if not isinstance(self.direction, OnlyParameterObjectiveDirection):
            raise ValueError("PARAMETER_POLICY_TIE_BREAKER_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {"metric_id": self.metric_id, "direction": self.direction.value}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterTieBreakerV1:
        _exact(payload, {"metric_id", "direction"}, "Tie breaker")
        return cls(
            _identifier(payload["metric_id"], "metric_id"),
            OnlyParameterObjectiveDirection(str(payload["direction"])),
        )


class OnlyParameterMissingEvidencePolicy(StrEnum):
    FAIL_CLOSED = "FAIL_CLOSED"


class OnlyParameterResearchFailurePolicy(StrEnum):
    EXCLUDE_UNAVAILABLE = "EXCLUDE_UNAVAILABLE"


class OnlyParameterConvergenceRule(StrEnum):
    CONSECUTIVE_NO_MINIMUM_IMPROVEMENT = "CONSECUTIVE_NO_MINIMUM_IMPROVEMENT"


@dataclass(frozen=True, slots=True)
class OnlyParameterSearchPolicyV1:
    primary_metric_selector: str
    objective_direction: OnlyParameterObjectiveDirection
    required_constraints: tuple[OnlyParameterMetricConstraintV1, ...]
    ordered_tie_breakers: tuple[OnlyParameterTieBreakerV1, ...]
    minimum_improvement: Decimal
    max_no_improvement_decisions: int
    batch_size: int
    coarse_stride: int
    convergence_rule: OnlyParameterConvergenceRule = OnlyParameterConvergenceRule.CONSECUTIVE_NO_MINIMUM_IMPROVEMENT
    missing_evidence_policy: OnlyParameterMissingEvidencePolicy = OnlyParameterMissingEvidencePolicy.FAIL_CLOSED
    research_failure_policy: OnlyParameterResearchFailurePolicy = OnlyParameterResearchFailurePolicy.EXCLUDE_UNAVAILABLE
    schema_version: int = PARAMETER_SEARCH_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARAMETER_SEARCH_POLICY_SCHEMA_VERSION:
            raise ValueError("PARAMETER_POLICY_SCHEMA_UNSUPPORTED")
        _identifier(self.primary_metric_selector, "primary metric")
        if not isinstance(self.objective_direction, OnlyParameterObjectiveDirection):
            raise ValueError("PARAMETER_POLICY_DIRECTION_INVALID")
        if tuple(sorted(self.required_constraints)) != self.required_constraints:
            raise ValueError("PARAMETER_POLICY_CONSTRAINT_ORDER_INVALID")
        if len({item.metric_id for item in self.required_constraints}) != len(self.required_constraints):
            raise ValueError("PARAMETER_POLICY_CONSTRAINT_DUPLICATE")
        if len({item.metric_id for item in self.ordered_tie_breakers}) != len(self.ordered_tie_breakers):
            raise ValueError("PARAMETER_POLICY_TIE_BREAKER_DUPLICATE")
        if (
            not isinstance(self.minimum_improvement, Decimal)
            or not self.minimum_improvement.is_finite()
            or self.minimum_improvement < 0
        ):
            raise ValueError("PARAMETER_POLICY_IMPROVEMENT_INVALID")
        _positive(self.max_no_improvement_decisions, "max no-improvement decisions")
        _positive(self.batch_size, "batch size")
        _positive(self.coarse_stride, "coarse stride")
        if self.convergence_rule is not OnlyParameterConvergenceRule.CONSECUTIVE_NO_MINIMUM_IMPROVEMENT:
            raise ValueError("PARAMETER_POLICY_CONVERGENCE_INVALID")
        if self.missing_evidence_policy is not OnlyParameterMissingEvidencePolicy.FAIL_CLOSED:
            raise ValueError("PARAMETER_POLICY_MISSING_EVIDENCE_INVALID")
        if self.research_failure_policy is not OnlyParameterResearchFailurePolicy.EXCLUDE_UNAVAILABLE:
            raise ValueError("PARAMETER_POLICY_RESEARCH_FAILURE_INVALID")

    @property
    def policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.parameter-search-policy", **self.to_dict(include_fingerprint=False)}
        )

    @property
    def required_metric_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.primary_metric_selector,
                    *(item.metric_id for item in self.required_constraints),
                    *(item.metric_id for item in self.ordered_tie_breakers),
                )
            )
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "primary_metric_selector": self.primary_metric_selector,
            "objective_direction": self.objective_direction.value,
            "required_constraints": [item.to_dict() for item in self.required_constraints],
            "ordered_tie_breakers": [item.to_dict() for item in self.ordered_tie_breakers],
            "minimum_improvement": str(self.minimum_improvement),
            "max_no_improvement_decisions": self.max_no_improvement_decisions,
            "batch_size": self.batch_size,
            "coarse_stride": self.coarse_stride,
            "convergence_rule": self.convergence_rule.value,
            "missing_evidence_policy": self.missing_evidence_policy.value,
            "research_failure_policy": self.research_failure_policy.value,
        }
        if include_fingerprint:
            payload["policy_fingerprint"] = self.policy_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterSearchPolicyV1:
        _exact(
            payload,
            {
                "schema_version",
                "primary_metric_selector",
                "objective_direction",
                "required_constraints",
                "ordered_tie_breakers",
                "minimum_improvement",
                "max_no_improvement_decisions",
                "batch_size",
                "coarse_stride",
                "convergence_rule",
                "missing_evidence_policy",
                "research_failure_policy",
                "policy_fingerprint",
            },
            "Parameter Policy",
        )
        value = cls(
            _identifier(payload["primary_metric_selector"], "primary_metric_selector"),
            OnlyParameterObjectiveDirection(str(payload["objective_direction"])),
            tuple(
                OnlyParameterMetricConstraintV1.from_dict(_mapping(item, "constraint"))
                for item in _array(payload["required_constraints"], "constraints")
            ),
            tuple(
                OnlyParameterTieBreakerV1.from_dict(_mapping(item, "tie breaker"))
                for item in _array(payload["ordered_tie_breakers"], "tie breakers")
            ),
            Decimal(str(payload["minimum_improvement"])),
            _positive(payload["max_no_improvement_decisions"], "max_no_improvement_decisions"),
            _positive(payload["batch_size"], "batch_size"),
            _positive(payload["coarse_stride"], "coarse_stride"),
            OnlyParameterConvergenceRule(str(payload["convergence_rule"])),
            OnlyParameterMissingEvidencePolicy(str(payload["missing_evidence_policy"])),
            OnlyParameterResearchFailurePolicy(str(payload["research_failure_policy"])),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["policy_fingerprint"] != value.policy_fingerprint:
            raise ValueError("PARAMETER_POLICY_IDENTITY_MISMATCH")
        return value


class OnlyParameterFeedbackDecisionKind(StrEnum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"


class OnlyParameterSearchStopReason(StrEnum):
    SEARCH_SPACE_EXHAUSTED = "SEARCH_SPACE_EXHAUSTED"
    PROPOSAL_BUDGET_EXHAUSTED = "PROPOSAL_BUDGET_EXHAUSTED"
    RESEARCH_BUDGET_EXHAUSTED = "RESEARCH_BUDGET_EXHAUSTED"
    NO_ELIGIBLE_EVIDENCE = "NO_ELIGIBLE_EVIDENCE"
    CONVERGED_NO_IMPROVEMENT = "CONVERGED_NO_IMPROVEMENT"
    NEIGHBORHOOD_EXHAUSTED = "NEIGHBORHOOD_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class OnlyParameterSearchFeedbackDecisionV1:
    experiment_fingerprint: str
    ordered_input_iteration_result_fingerprints: tuple[str, ...]
    selected_anchor_iteration_result_fingerprint: str | None
    ordered_next_proposal_fingerprints: tuple[str, ...]
    start_iteration_index: int
    decision_kind: OnlyParameterFeedbackDecisionKind
    stop_reason: OnlyParameterSearchStopReason | None
    search_policy_fingerprint: str
    algorithm_implementation_fingerprint: str
    schema_version: int = PARAMETER_FEEDBACK_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARAMETER_FEEDBACK_DECISION_SCHEMA_VERSION:
            raise ValueError("PARAMETER_FEEDBACK_SCHEMA_UNSUPPORTED")
        _sha(self.experiment_fingerprint, "Experiment fingerprint")
        for value in self.ordered_input_iteration_result_fingerprints:
            _sha(value, "input Iteration Result fingerprint")
        if len(set(self.ordered_input_iteration_result_fingerprints)) != len(
            self.ordered_input_iteration_result_fingerprints
        ):
            raise ValueError("PARAMETER_FEEDBACK_INPUT_DUPLICATE")
        if self.selected_anchor_iteration_result_fingerprint is not None:
            _sha(self.selected_anchor_iteration_result_fingerprint, "anchor Result fingerprint")
            if (
                self.selected_anchor_iteration_result_fingerprint
                not in self.ordered_input_iteration_result_fingerprints
            ):
                raise ValueError("PARAMETER_FEEDBACK_ANCHOR_NOT_INPUT")
        for value in self.ordered_next_proposal_fingerprints:
            _sha(value, "next Proposal fingerprint")
        if len(set(self.ordered_next_proposal_fingerprints)) != len(self.ordered_next_proposal_fingerprints):
            raise ValueError("PARAMETER_FEEDBACK_PROPOSAL_DUPLICATE")
        _non_negative(self.start_iteration_index, "start_iteration_index")
        _sha(self.search_policy_fingerprint, "Search Policy fingerprint")
        _sha(self.algorithm_implementation_fingerprint, "Algorithm fingerprint")
        if not isinstance(self.decision_kind, OnlyParameterFeedbackDecisionKind):
            raise ValueError("PARAMETER_FEEDBACK_KIND_INVALID")
        if self.stop_reason is not None and not isinstance(self.stop_reason, OnlyParameterSearchStopReason):
            raise ValueError("PARAMETER_FEEDBACK_STOP_REASON_INVALID")
        if self.decision_kind is OnlyParameterFeedbackDecisionKind.CONTINUE:
            if not self.ordered_next_proposal_fingerprints or self.stop_reason is not None:
                raise ValueError("PARAMETER_FEEDBACK_CONTINUE_INVALID")
        elif self.ordered_next_proposal_fingerprints or self.stop_reason is None:
            raise ValueError("PARAMETER_FEEDBACK_STOP_INVALID")

    @property
    def feedback_decision_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.parameter-feedback-decision", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "ordered_input_iteration_result_fingerprints": list(self.ordered_input_iteration_result_fingerprints),
            "selected_anchor_iteration_result_fingerprint": self.selected_anchor_iteration_result_fingerprint,
            "ordered_next_proposal_fingerprints": list(self.ordered_next_proposal_fingerprints),
            "start_iteration_index": self.start_iteration_index,
            "decision_kind": self.decision_kind.value,
            "stop_reason": None if self.stop_reason is None else self.stop_reason.value,
            "search_policy_fingerprint": self.search_policy_fingerprint,
            "algorithm_implementation_fingerprint": self.algorithm_implementation_fingerprint,
        }
        if include_fingerprint:
            payload["feedback_decision_fingerprint"] = self.feedback_decision_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterSearchFeedbackDecisionV1:
        _exact(
            payload,
            {
                "schema_version",
                "experiment_fingerprint",
                "ordered_input_iteration_result_fingerprints",
                "selected_anchor_iteration_result_fingerprint",
                "ordered_next_proposal_fingerprints",
                "start_iteration_index",
                "decision_kind",
                "stop_reason",
                "search_policy_fingerprint",
                "algorithm_implementation_fingerprint",
                "feedback_decision_fingerprint",
            },
            "Feedback Decision",
        )
        anchor = payload["selected_anchor_iteration_result_fingerprint"]
        reason = payload["stop_reason"]
        value = cls(
            _sha(payload["experiment_fingerprint"], "experiment_fingerprint"),
            tuple(
                _sha(item, "input result")
                for item in _array(payload["ordered_input_iteration_result_fingerprints"], "input results")
            ),
            None if anchor is None else _sha(anchor, "anchor"),
            tuple(
                _sha(item, "next proposal")
                for item in _array(payload["ordered_next_proposal_fingerprints"], "next proposals")
            ),
            _non_negative(payload["start_iteration_index"], "start_iteration_index"),
            OnlyParameterFeedbackDecisionKind(str(payload["decision_kind"])),
            None if reason is None else OnlyParameterSearchStopReason(str(reason)),
            _sha(payload["search_policy_fingerprint"], "search_policy_fingerprint"),
            _sha(payload["algorithm_implementation_fingerprint"], "algorithm_implementation_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["feedback_decision_fingerprint"] != value.feedback_decision_fingerprint:
            raise ValueError("PARAMETER_FEEDBACK_IDENTITY_MISMATCH")
        return value


@dataclass(frozen=True, slots=True)
class OnlyParameterSearchAlgorithmManifestV1:
    algorithm_id: str
    algorithm_semantic_version: str
    source_revision: str
    ordered_resource_sha256: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("PARAMETER_ALGORITHM_SCHEMA_UNSUPPORTED")
        _identifier(self.algorithm_id, "algorithm_id")
        _identifier(self.algorithm_semantic_version, "algorithm semantic version")
        _identifier(self.source_revision, "source revision")
        if not self.ordered_resource_sha256:
            raise ValueError("PARAMETER_ALGORITHM_RESOURCES_EMPTY")
        for value in self.ordered_resource_sha256:
            _sha(value, "algorithm resource SHA256")

    @property
    def implementation_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.parameter-search-algorithm", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "algorithm_id": self.algorithm_id,
            "algorithm_semantic_version": self.algorithm_semantic_version,
            "source_revision": self.source_revision,
            "ordered_resource_sha256": list(self.ordered_resource_sha256),
        }
        if include_fingerprint:
            payload["implementation_fingerprint"] = self.implementation_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyParameterSearchAlgorithmManifestV1:
        _exact(
            payload,
            {
                "schema_version",
                "algorithm_id",
                "algorithm_semantic_version",
                "source_revision",
                "ordered_resource_sha256",
                "implementation_fingerprint",
            },
            "Algorithm Manifest",
        )
        value = cls(
            _identifier(payload["algorithm_id"], "algorithm_id"),
            _identifier(payload["algorithm_semantic_version"], "algorithm_semantic_version"),
            _identifier(payload["source_revision"], "source_revision"),
            tuple(_sha(item, "resource sha") for item in _array(payload["ordered_resource_sha256"], "resources")),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["implementation_fingerprint"] != value.implementation_fingerprint:
            raise ValueError("PARAMETER_ALGORITHM_IDENTITY_MISMATCH")
        return value


def materialize_parameter_proposals(
    space: OnlyParameterFactorSearchSpaceV1,
    calculation_registry: object,
) -> tuple[OnlyParameterGraphProposalV1, ...]:
    plan = OnlyResearchSweepPlanner(calculation_registry).plan(space.sweep_definition)  # type: ignore[arg-type]
    materializer = OnlyResearchGraphTemplateMaterializer(calculation_registry)  # type: ignore[arg-type]
    proposals = []
    for cell in plan.cells:
        assignment_map = {
            OnlyResearchSweepParameterTarget(item.target.template_node_id, item.target.parameter_name): item.value
            for item in cell.assignment
        }
        materialized = materializer.materialize(space.sweep_definition.graph_template, assignment_map)
        candidate = materialized.node_fingerprints[space.candidate_template_node_id]
        proposals.append(
            OnlyParameterGraphProposalV1(
                space.search_space_fingerprint,
                tuple(
                    sorted(
                        (OnlyParameterAssignmentValueV1(item.target, item.value) for item in cell.assignment),
                        key=lambda item: item.target.key,
                    )
                ),
                materialized.graph,
                candidate,
                space.candidate_output_name,
                cell.ordinal,
            )
        )
    if len({item.proposal_fingerprint for item in proposals}) != len(proposals):
        raise ValueError("PARAMETER_PROPOSAL_SEMANTIC_DUPLICATE")
    return tuple(proposals)


__all__ = [
    name
    for name in globals()
    if name.startswith(("OnlyParameter", "PARAMETER_", "DETERMINISTIC_", "materialize_parameter"))
]
