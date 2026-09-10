"""Immutable Agent decision and launch provenance values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint

from .model import OnlyAgentBudgetV1
from .occurrence import OnlyAgentContextReferenceV1


def _exact(payload: Mapping[str, object], fields: set[str], context: str) -> None:
    if set(payload) != fields:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _identifier(value: object, context: str) -> str:
    result = _string(value, context)
    if any(character.isspace() for character in result):
        raise ValueError(f"{context} must not contain whitespace")
    return result


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _sha(value: object, context: str) -> str:
    result = _string(value, context)
    if len(result) != 64 or any(item not in "0123456789abcdef" for item in result):
        raise ValueError(f"{context} must be a lower-case SHA256")
    return result


def _strings(value: object, context: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = tuple(_string(item, context) for item in _array(value, context))
    if (non_empty and not result) or len(result) != len(set(result)):
        raise ValueError(f"{context} must be {'non-empty and ' if non_empty else ''}unique")
    return result


def _references(value: object, context: str, *, non_empty: bool = False) -> tuple[OnlyAgentContextReferenceV1, ...]:
    result = tuple(OnlyAgentContextReferenceV1.from_dict(_mapping(item, context)) for item in _array(value, context))
    if (non_empty and not result) or len(result) != len(set(result)):
        raise ValueError(f"{context} must be {'non-empty and ' if non_empty else ''}unique")
    return result


class OnlyAgentDecisionKind(StrEnum):
    RESEARCH_PLAN = "RESEARCH_PLAN"
    SEARCH_DIRECTIVE = "SEARCH_DIRECTIVE"
    NEXT_EXPERIMENT_PROPOSAL = "NEXT_EXPERIMENT_PROPOSAL"


class OnlyAgentRouterAction(StrEnum):
    REUSE_EXISTING = "REUSE_EXISTING"
    SYMBOLIC_SEARCH = "SYMBOLIC_SEARCH"
    PARAMETER_SEARCH = "PARAMETER_SEARCH"
    CAPABILITY_GAP = "CAPABILITY_GAP"


class OnlyAgentEvaluationPathKind(StrEnum):
    DIRECT_REUSE_RESEARCH = "DIRECT_REUSE_RESEARCH"
    CHILD_SEARCH = "CHILD_SEARCH"


class OnlyAgentEvidenceObservationCodeV1(StrEnum):
    EFFECT_DIRECTION_SUPPORTS_HYPOTHESIS = "EFFECT_DIRECTION_SUPPORTS_HYPOTHESIS"
    WEAK_TEMPORAL_STABILITY = "WEAK_TEMPORAL_STABILITY"
    LIMITED_COVERAGE = "LIMITED_COVERAGE"
    HIGH_REDUNDANCY = "HIGH_REDUNDANCY"
    ROBUSTNESS_UNCERTAIN = "ROBUSTNESS_UNCERTAIN"
    FOLLOW_UP_RECOMMENDED = "FOLLOW_UP_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class OnlyAgentEvidenceObservationV1:
    observation_code: OnlyAgentEvidenceObservationCodeV1
    supporting_authority_references: tuple[OnlyAgentContextReferenceV1, ...]
    categorical_assessment: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not isinstance(self.observation_code, OnlyAgentEvidenceObservationCodeV1)
            or not self.supporting_authority_references
            or len(self.supporting_authority_references) != len(set(self.supporting_authority_references))
            or any(
                reference.reference_kind != "RESEARCH_STATISTICS" or reference.reference_schema_version != 1
                for reference in self.supporting_authority_references
            )
        ):
            raise ValueError("AGENT_EVIDENCE_OBSERVATION_INVALID")
        if self.categorical_assessment is not None:
            _identifier(self.categorical_assessment, "categorical_assessment")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observation_code": self.observation_code.value,
            "supporting_authority_references": [
                reference.to_dict() for reference in self.supporting_authority_references
            ],
            "categorical_assessment": self.categorical_assessment,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentEvidenceObservationV1:
        _exact(
            payload,
            {
                "schema_version",
                "observation_code",
                "supporting_authority_references",
                "categorical_assessment",
            },
            "Evidence Observation",
        )
        assessment = payload["categorical_assessment"]
        if assessment is not None and not isinstance(assessment, str):
            raise ValueError("AGENT_EVIDENCE_OBSERVATION_INVALID")
        return cls(
            OnlyAgentEvidenceObservationCodeV1(_string(payload["observation_code"], "observation_code")),
            _references(payload["supporting_authority_references"], "supporting evidence", non_empty=True),
            assessment,
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentResearchPlanV1:
    research_brief_fingerprint: str
    ordered_logical_role_sequence: tuple[str, ...]
    permitted_router_actions: tuple[OnlyAgentRouterAction, ...]
    agent_budget: OnlyAgentBudgetV1
    terminal_boundary: str = "ONE_EVALUATION_PATH_THEN_ADVISORY_PROPOSAL"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.agent_budget, OnlyAgentBudgetV1):
            raise ValueError("AGENT_RESEARCH_PLAN_INVALID")
        _sha(self.research_brief_fingerprint, "research_brief_fingerprint")
        if not self.ordered_logical_role_sequence or len(self.ordered_logical_role_sequence) != len(
            set(self.ordered_logical_role_sequence)
        ):
            raise ValueError("AGENT_RESEARCH_PLAN_INVALID")
        for role in self.ordered_logical_role_sequence:
            _identifier(role, "logical role")
        if (
            not self.permitted_router_actions
            or len(self.permitted_router_actions) != len(set(self.permitted_router_actions))
            or any(not isinstance(item, OnlyAgentRouterAction) for item in self.permitted_router_actions)
        ):
            raise ValueError("AGENT_RESEARCH_PLAN_INVALID")
        _identifier(self.terminal_boundary, "terminal_boundary")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "research_brief_fingerprint": self.research_brief_fingerprint,
            "ordered_logical_role_sequence": list(self.ordered_logical_role_sequence),
            "permitted_router_actions": [item.value for item in self.permitted_router_actions],
            "agent_budget": self.agent_budget.to_dict(),
            "terminal_boundary": self.terminal_boundary,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentResearchPlanV1:
        _exact(
            payload,
            {
                "schema_version",
                "research_brief_fingerprint",
                "ordered_logical_role_sequence",
                "permitted_router_actions",
                "agent_budget",
                "terminal_boundary",
            },
            "Research Plan",
        )
        return cls(
            _sha(payload["research_brief_fingerprint"], "research_brief_fingerprint"),
            _strings(payload["ordered_logical_role_sequence"], "logical role", non_empty=True),
            tuple(
                OnlyAgentRouterAction(_string(item, "router action"))
                for item in _array(payload["permitted_router_actions"], "permitted_router_actions")
            ),
            OnlyAgentBudgetV1.from_dict(_mapping(payload["agent_budget"], "agent_budget")),
            _string(payload["terminal_boundary"], "terminal_boundary"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentReuseDirectiveV1:
    reused_capability_references: tuple[OnlyAgentContextReferenceV1, ...]
    research_definition_reference: OnlyAgentContextReferenceV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not self.reused_capability_references
            or len(self.reused_capability_references) != len(set(self.reused_capability_references))
            or any(not isinstance(item, OnlyAgentContextReferenceV1) for item in self.reused_capability_references)
            or not isinstance(self.research_definition_reference, OnlyAgentContextReferenceV1)
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")
        if self.research_definition_reference.reference_kind != "RESEARCH_DEFINITION" or (
            self.research_definition_reference.reference_schema_version != 1
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "reused_capability_references": [item.to_dict() for item in self.reused_capability_references],
            "research_definition_reference": self.research_definition_reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentReuseDirectiveV1:
        _exact(
            payload,
            {"schema_version", "reused_capability_references", "research_definition_reference"},
            "Reuse Directive",
        )
        return cls(
            _references(payload["reused_capability_references"], "reused capability", non_empty=True),
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["research_definition_reference"], "research_definition_reference")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentSymbolicSearchDirectiveV1:
    search_space_reference: OnlyAgentContextReferenceV1
    evaluation_reference: OnlyAgentContextReferenceV1
    algorithm_reference: OnlyAgentContextReferenceV1
    search_budget_reference: OnlyAgentContextReferenceV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or any(
            not isinstance(item, OnlyAgentContextReferenceV1)
            for item in (
                self.search_space_reference,
                self.evaluation_reference,
                self.algorithm_reference,
                self.search_budget_reference,
            )
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")
        expected = (
            (self.search_space_reference, "SYMBOLIC_SEARCH_SPACE"),
            (self.evaluation_reference, "RESEARCH_EVALUATION"),
            (self.algorithm_reference, "SEARCH_ALGORITHM"),
            (self.search_budget_reference, "SEARCH_BUDGET"),
        )
        if any(
            reference.reference_kind != kind or reference.reference_schema_version != 1 for reference, kind in expected
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "search_space_reference": self.search_space_reference.to_dict(),
            "evaluation_reference": self.evaluation_reference.to_dict(),
            "algorithm_reference": self.algorithm_reference.to_dict(),
            "search_budget_reference": self.search_budget_reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentSymbolicSearchDirectiveV1:
        _exact(
            payload,
            {
                "schema_version",
                "search_space_reference",
                "evaluation_reference",
                "algorithm_reference",
                "search_budget_reference",
            },
            "Symbolic Search Directive",
        )
        return cls(
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["search_space_reference"], "search_space_reference")
            ),
            OnlyAgentContextReferenceV1.from_dict(_mapping(payload["evaluation_reference"], "evaluation_reference")),
            OnlyAgentContextReferenceV1.from_dict(_mapping(payload["algorithm_reference"], "algorithm_reference")),
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["search_budget_reference"], "search_budget_reference")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentParameterSearchDirectiveV1:
    search_space_reference: OnlyAgentContextReferenceV1
    evaluation_reference: OnlyAgentContextReferenceV1
    search_policy_reference: OnlyAgentContextReferenceV1
    algorithm_reference: OnlyAgentContextReferenceV1
    search_budget_reference: OnlyAgentContextReferenceV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or any(
            not isinstance(item, OnlyAgentContextReferenceV1)
            for item in (
                self.search_space_reference,
                self.evaluation_reference,
                self.search_policy_reference,
                self.algorithm_reference,
                self.search_budget_reference,
            )
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")
        expected = (
            (self.search_space_reference, "PARAMETER_SEARCH_SPACE"),
            (self.evaluation_reference, "RESEARCH_EVALUATION"),
            (self.search_policy_reference, "SEARCH_POLICY"),
            (self.algorithm_reference, "SEARCH_ALGORITHM"),
            (self.search_budget_reference, "SEARCH_BUDGET"),
        )
        if any(
            reference.reference_kind != kind or reference.reference_schema_version != 1 for reference, kind in expected
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "search_space_reference": self.search_space_reference.to_dict(),
            "evaluation_reference": self.evaluation_reference.to_dict(),
            "search_policy_reference": self.search_policy_reference.to_dict(),
            "algorithm_reference": self.algorithm_reference.to_dict(),
            "search_budget_reference": self.search_budget_reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentParameterSearchDirectiveV1:
        _exact(
            payload,
            {
                "schema_version",
                "search_space_reference",
                "evaluation_reference",
                "search_policy_reference",
                "algorithm_reference",
                "search_budget_reference",
            },
            "Parameter Search Directive",
        )
        return cls(
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["search_space_reference"], "search_space_reference")
            ),
            OnlyAgentContextReferenceV1.from_dict(_mapping(payload["evaluation_reference"], "evaluation_reference")),
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["search_policy_reference"], "search_policy_reference")
            ),
            OnlyAgentContextReferenceV1.from_dict(_mapping(payload["algorithm_reference"], "algorithm_reference")),
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["search_budget_reference"], "search_budget_reference")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentCapabilityGapDirectiveV1:
    missing_capability_references: tuple[OnlyAgentContextReferenceV1, ...]
    required_semantic_roles: tuple[str, ...]
    reason_codes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not self.missing_capability_references
            or len(self.missing_capability_references) != len(set(self.missing_capability_references))
            or any(not isinstance(item, OnlyAgentContextReferenceV1) for item in self.missing_capability_references)
            or not self.required_semantic_roles
            or len(self.required_semantic_roles) != len(set(self.required_semantic_roles))
            or not self.reason_codes
            or len(self.reason_codes) != len(set(self.reason_codes))
        ):
            raise ValueError("AGENT_CAPABILITY_GAP_INVALID")
        for value in (*self.required_semantic_roles, *self.reason_codes):
            _identifier(value, "capability gap value")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "missing_capability_references": [item.to_dict() for item in self.missing_capability_references],
            "required_semantic_roles": list(self.required_semantic_roles),
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentCapabilityGapDirectiveV1:
        _exact(
            payload,
            {"schema_version", "missing_capability_references", "required_semantic_roles", "reason_codes"},
            "Capability Gap Directive",
        )
        return cls(
            _references(payload["missing_capability_references"], "missing capability", non_empty=True),
            _strings(payload["required_semantic_roles"], "required semantic role", non_empty=True),
            _strings(payload["reason_codes"], "reason code", non_empty=True),
            _integer(payload["schema_version"], "schema_version"),
        )


OnlyAgentSearchDirectivePayloadV1 = (
    OnlyAgentReuseDirectiveV1
    | OnlyAgentSymbolicSearchDirectiveV1
    | OnlyAgentParameterSearchDirectiveV1
    | OnlyAgentCapabilityGapDirectiveV1
)

_ACTION_PAYLOAD_TYPES: dict[OnlyAgentRouterAction, type[OnlyAgentSearchDirectivePayloadV1]] = {
    OnlyAgentRouterAction.REUSE_EXISTING: OnlyAgentReuseDirectiveV1,
    OnlyAgentRouterAction.SYMBOLIC_SEARCH: OnlyAgentSymbolicSearchDirectiveV1,
    OnlyAgentRouterAction.PARAMETER_SEARCH: OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentRouterAction.CAPABILITY_GAP: OnlyAgentCapabilityGapDirectiveV1,
}


@dataclass(frozen=True, slots=True)
class OnlyAgentSearchDirectiveV1:
    router_action: OnlyAgentRouterAction
    exact_catalog_context_tool_result_fingerprint: str
    action_payload: OnlyAgentSearchDirectivePayloadV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not isinstance(self.router_action, OnlyAgentRouterAction)
            or not isinstance(self.action_payload, _ACTION_PAYLOAD_TYPES[self.router_action])
        ):
            raise ValueError("AGENT_SEARCH_DIRECTIVE_INVALID")
        _sha(self.exact_catalog_context_tool_result_fingerprint, "catalog Tool Result fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "router_action": self.router_action.value,
            "exact_catalog_context_tool_result_fingerprint": self.exact_catalog_context_tool_result_fingerprint,
            "action_payload": self.action_payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentSearchDirectiveV1:
        _exact(
            payload,
            {
                "schema_version",
                "router_action",
                "exact_catalog_context_tool_result_fingerprint",
                "action_payload",
            },
            "Search Directive",
        )
        action = OnlyAgentRouterAction(_string(payload["router_action"], "router_action"))
        return cls(
            action,
            _sha(payload["exact_catalog_context_tool_result_fingerprint"], "catalog Tool Result fingerprint"),
            _ACTION_PAYLOAD_TYPES[action].from_dict(_mapping(payload["action_payload"], "action_payload")),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentFollowUpBriefDeltaV1:
    hypothesis_delta: str
    rationale_delta: str
    proposed_changes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not self.proposed_changes
            or len(self.proposed_changes) != len(set(self.proposed_changes))
        ):
            raise ValueError("AGENT_NEXT_EXPERIMENT_PROPOSAL_INVALID")
        _string(self.hypothesis_delta, "hypothesis_delta")
        _string(self.rationale_delta, "rationale_delta")
        for change in self.proposed_changes:
            _string(change, "proposed change")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_delta": self.hypothesis_delta,
            "rationale_delta": self.rationale_delta,
            "proposed_changes": list(self.proposed_changes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentFollowUpBriefDeltaV1:
        _exact(
            payload,
            {"schema_version", "hypothesis_delta", "rationale_delta", "proposed_changes"},
            "Follow-up Brief Delta",
        )
        return cls(
            _string(payload["hypothesis_delta"], "hypothesis_delta"),
            _string(payload["rationale_delta"], "rationale_delta"),
            _strings(payload["proposed_changes"], "proposed change", non_empty=True),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentNextExperimentProposalV1:
    evaluation_path_kind: OnlyAgentEvaluationPathKind
    completed_path_reference: OnlyAgentContextReferenceV1
    research_result_references: tuple[OnlyAgentContextReferenceV1, ...]
    research_statistics_references: tuple[OnlyAgentContextReferenceV1, ...]
    qualitative_observations: tuple[OnlyAgentEvidenceObservationV1, ...]
    proposed_follow_up_brief_delta: OnlyAgentFollowUpBriefDeltaV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not isinstance(self.evaluation_path_kind, OnlyAgentEvaluationPathKind)
            or not isinstance(self.completed_path_reference, OnlyAgentContextReferenceV1)
            or not self.research_result_references
            or len(self.research_result_references) != len(set(self.research_result_references))
            or any(not isinstance(item, OnlyAgentContextReferenceV1) for item in self.research_result_references)
            or not self.research_statistics_references
            or len(self.research_statistics_references) != len(set(self.research_statistics_references))
            or any(not isinstance(item, OnlyAgentContextReferenceV1) for item in self.research_statistics_references)
            or not self.qualitative_observations
            or len(self.qualitative_observations) != len(set(self.qualitative_observations))
            or not isinstance(self.proposed_follow_up_brief_delta, OnlyAgentFollowUpBriefDeltaV1)
        ):
            raise ValueError("AGENT_NEXT_EXPERIMENT_PROPOSAL_INVALID")
        if any(
            not isinstance(observation, OnlyAgentEvidenceObservationV1) for observation in self.qualitative_observations
        ):
            raise ValueError("AGENT_NEXT_EXPERIMENT_PROPOSAL_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evaluation_path_kind": self.evaluation_path_kind.value,
            "completed_path_reference": self.completed_path_reference.to_dict(),
            "research_result_references": [item.to_dict() for item in self.research_result_references],
            "research_statistics_references": [item.to_dict() for item in self.research_statistics_references],
            "qualitative_observations": [item.to_dict() for item in self.qualitative_observations],
            "proposed_follow_up_brief_delta": self.proposed_follow_up_brief_delta.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentNextExperimentProposalV1:
        _exact(
            payload,
            {
                "schema_version",
                "evaluation_path_kind",
                "completed_path_reference",
                "research_result_references",
                "research_statistics_references",
                "qualitative_observations",
                "proposed_follow_up_brief_delta",
            },
            "Next Experiment Proposal",
        )
        return cls(
            OnlyAgentEvaluationPathKind(_string(payload["evaluation_path_kind"], "evaluation_path_kind")),
            OnlyAgentContextReferenceV1.from_dict(
                _mapping(payload["completed_path_reference"], "completed_path_reference")
            ),
            _references(payload["research_result_references"], "Research Result", non_empty=True),
            _references(payload["research_statistics_references"], "Research Statistics", non_empty=True),
            tuple(
                OnlyAgentEvidenceObservationV1.from_dict(_mapping(item, "qualitative observation"))
                for item in _array(payload["qualitative_observations"], "qualitative_observations")
            ),
            OnlyAgentFollowUpBriefDeltaV1.from_dict(
                _mapping(payload["proposed_follow_up_brief_delta"], "proposed_follow_up_brief_delta")
            ),
            _integer(payload["schema_version"], "schema_version"),
        )


OnlyAgentDecisionPayloadV1 = OnlyAgentResearchPlanV1 | OnlyAgentSearchDirectiveV1 | OnlyAgentNextExperimentProposalV1

_DECISION_PAYLOAD_TYPES: dict[OnlyAgentDecisionKind, type[OnlyAgentDecisionPayloadV1]] = {
    OnlyAgentDecisionKind.RESEARCH_PLAN: OnlyAgentResearchPlanV1,
    OnlyAgentDecisionKind.SEARCH_DIRECTIVE: OnlyAgentSearchDirectiveV1,
    OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL: OnlyAgentNextExperimentProposalV1,
}


@dataclass(frozen=True, slots=True)
class OnlyAgentDecisionV1:
    agent_session_fingerprint: str
    decision_ordinal: int
    decision_kind: OnlyAgentDecisionKind
    logical_role: str
    role_policy_fingerprint: str
    ordered_model_call_result_fingerprints: tuple[str, ...]
    ordered_tool_call_result_fingerprints: tuple[str, ...]
    ordered_context_references: tuple[OnlyAgentContextReferenceV1, ...]
    structured_payload: OnlyAgentDecisionPayloadV1
    workflow_implementation_fingerprint: str
    structured_payload_fingerprint: str = ""
    decision_fingerprint: str = ""
    decision_payload_schema_version: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.decision_payload_schema_version != 1
            or not isinstance(self.decision_kind, OnlyAgentDecisionKind)
            or not isinstance(self.structured_payload, _DECISION_PAYLOAD_TYPES[self.decision_kind])
        ):
            raise ValueError("AGENT_DECISION_INVALID")
        expected_kind = (
            OnlyAgentDecisionKind.RESEARCH_PLAN,
            OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
            OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL,
        )
        if self.decision_ordinal not in range(3) or self.decision_kind is not expected_kind[self.decision_ordinal]:
            raise ValueError("AGENT_DECISION_ORDINAL_INVALID")
        _sha(self.agent_session_fingerprint, "agent_session_fingerprint")
        _identifier(self.logical_role, "logical_role")
        _sha(self.role_policy_fingerprint, "role_policy_fingerprint")
        _sha(self.workflow_implementation_fingerprint, "workflow_implementation_fingerprint")
        for values, context in (
            (self.ordered_model_call_result_fingerprints, "Model Result fingerprint"),
            (self.ordered_tool_call_result_fingerprints, "Tool Result fingerprint"),
        ):
            if len(values) != len(set(values)):
                raise ValueError("AGENT_DECISION_INPUT_INVALID")
            for value in values:
                _sha(value, context)
        if (
            not isinstance(self.ordered_context_references, tuple)
            or len(self.ordered_context_references) != len(set(self.ordered_context_references))
            or any(not isinstance(item, OnlyAgentContextReferenceV1) for item in self.ordered_context_references)
        ):
            raise ValueError("AGENT_DECISION_INPUT_INVALID")
        payload_fingerprint = only_canonical_fingerprint(self.structured_payload.to_dict())
        if not self.structured_payload_fingerprint:
            object.__setattr__(self, "structured_payload_fingerprint", payload_fingerprint)
        elif self.structured_payload_fingerprint != payload_fingerprint:
            raise ValueError("AGENT_DECISION_PAYLOAD_FINGERPRINT_MISMATCH")
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-decision", **self.to_dict(include_fingerprint=False)}
        )
        if not self.decision_fingerprint:
            object.__setattr__(self, "decision_fingerprint", expected)
        elif self.decision_fingerprint != expected:
            raise ValueError("AGENT_DECISION_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_session_fingerprint": self.agent_session_fingerprint,
            "decision_ordinal": self.decision_ordinal,
            "decision_kind": self.decision_kind.value,
            "logical_role": self.logical_role,
            "role_policy_fingerprint": self.role_policy_fingerprint,
            "ordered_model_call_result_fingerprints": list(self.ordered_model_call_result_fingerprints),
            "ordered_tool_call_result_fingerprints": list(self.ordered_tool_call_result_fingerprints),
            "ordered_context_references": [item.to_dict() for item in self.ordered_context_references],
            "decision_payload_schema_version": self.decision_payload_schema_version,
            "structured_payload": self.structured_payload.to_dict(),
            "structured_payload_fingerprint": self.structured_payload_fingerprint,
            "workflow_implementation_fingerprint": self.workflow_implementation_fingerprint,
        }
        if include_fingerprint:
            result["decision_fingerprint"] = self.decision_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentDecisionV1:
        _exact(
            payload,
            {
                "schema_version",
                "agent_session_fingerprint",
                "decision_ordinal",
                "decision_kind",
                "logical_role",
                "role_policy_fingerprint",
                "ordered_model_call_result_fingerprints",
                "ordered_tool_call_result_fingerprints",
                "ordered_context_references",
                "decision_payload_schema_version",
                "structured_payload",
                "structured_payload_fingerprint",
                "workflow_implementation_fingerprint",
                "decision_fingerprint",
            },
            "Agent Decision",
        )
        kind = OnlyAgentDecisionKind(_string(payload["decision_kind"], "decision_kind"))
        return cls(
            _sha(payload["agent_session_fingerprint"], "agent_session_fingerprint"),
            _integer(payload["decision_ordinal"], "decision_ordinal"),
            kind,
            _string(payload["logical_role"], "logical_role"),
            _sha(payload["role_policy_fingerprint"], "role_policy_fingerprint"),
            tuple(
                _sha(item, "Model Result fingerprint")
                for item in _array(payload["ordered_model_call_result_fingerprints"], "Model Result fingerprints")
            ),
            tuple(
                _sha(item, "Tool Result fingerprint")
                for item in _array(payload["ordered_tool_call_result_fingerprints"], "Tool Result fingerprints")
            ),
            _references(payload["ordered_context_references"], "context reference"),
            _DECISION_PAYLOAD_TYPES[kind].from_dict(_mapping(payload["structured_payload"], "structured_payload")),
            _sha(payload["workflow_implementation_fingerprint"], "workflow_implementation_fingerprint"),
            _sha(payload["structured_payload_fingerprint"], "structured_payload_fingerprint"),
            _sha(payload["decision_fingerprint"], "decision_fingerprint"),
            _integer(payload["decision_payload_schema_version"], "decision_payload_schema_version"),
            _integer(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyAgentExperimentLaunchRecordV1:
    agent_session_fingerprint: str
    agent_decision_fingerprint: str
    tool_call_result_fingerprint: str
    child_search_experiment_fingerprint: str
    experiment_launch_record_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("AGENT_EXPERIMENT_LAUNCH_INVALID")
        for value, context in (
            (self.agent_session_fingerprint, "agent_session_fingerprint"),
            (self.agent_decision_fingerprint, "agent_decision_fingerprint"),
            (self.tool_call_result_fingerprint, "tool_call_result_fingerprint"),
            (self.child_search_experiment_fingerprint, "child_search_experiment_fingerprint"),
        ):
            _sha(value, context)
        expected = only_canonical_fingerprint(
            {"domain": "onlyalpha.agent-experiment-launch", **self.to_dict(include_fingerprint=False)}
        )
        if not self.experiment_launch_record_fingerprint:
            object.__setattr__(self, "experiment_launch_record_fingerprint", expected)
        elif self.experiment_launch_record_fingerprint != expected:
            raise ValueError("AGENT_EXPERIMENT_LAUNCH_FINGERPRINT_MISMATCH")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "agent_session_fingerprint": self.agent_session_fingerprint,
            "agent_decision_fingerprint": self.agent_decision_fingerprint,
            "tool_call_result_fingerprint": self.tool_call_result_fingerprint,
            "child_search_experiment_fingerprint": self.child_search_experiment_fingerprint,
        }
        if include_fingerprint:
            result["experiment_launch_record_fingerprint"] = self.experiment_launch_record_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyAgentExperimentLaunchRecordV1:
        _exact(
            payload,
            {
                "schema_version",
                "agent_session_fingerprint",
                "agent_decision_fingerprint",
                "tool_call_result_fingerprint",
                "child_search_experiment_fingerprint",
                "experiment_launch_record_fingerprint",
            },
            "Experiment Launch Record",
        )
        return cls(
            _sha(payload["agent_session_fingerprint"], "agent_session_fingerprint"),
            _sha(payload["agent_decision_fingerprint"], "agent_decision_fingerprint"),
            _sha(payload["tool_call_result_fingerprint"], "tool_call_result_fingerprint"),
            _sha(payload["child_search_experiment_fingerprint"], "child_search_experiment_fingerprint"),
            _sha(payload["experiment_launch_record_fingerprint"], "experiment_launch_record_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


__all__ = [name for name in globals() if name.startswith("OnlyAgent")]
