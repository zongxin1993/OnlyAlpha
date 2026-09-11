"""Pure Agent Decision language to Search Product language translation."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.experiment import (
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisSourceKind,
    OnlySearchHypothesisSourceReferenceV1,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)

from .decision import (
    OnlyAgentParameterSearchDirectiveV1,
    OnlyAgentRouterAction,
    OnlyAgentSearchDirectiveV1,
    OnlyAgentSymbolicSearchDirectiveV1,
)
from .errors import OnlyAgentContextError
from .model import OnlyAgentStructuredHypothesisV1
from .occurrence_service import OnlyAgentProductRequestSemanticProjectionV1
from .verification import OnlyVerifiedAgentDecisionContextV1

ONLYAGENT_SYMBOLIC_SEARCH_WORKFLOW_BINDING_V1 = OnlySearchWorkflowBindingV1("symbolic.factor.search", "1")
ONLYAGENT_PARAMETER_SEARCH_WORKFLOW_BINDING_V1 = OnlySearchWorkflowBindingV1("parameter.factor.search", "1")
ONLYAGENT_SEARCH_DECISION_ENGINE_BINDING_V1 = OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC)


class OnlyAgentSearchRuntimeGenerationAuthority(Protocol):
    """Product/Runtime Authority used to admit a requested new-work generation."""

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object: ...


def only_agent_structured_hypothesis_fingerprint(
    hypothesis: OnlyAgentStructuredHypothesisV1,
) -> str:
    return only_canonical_fingerprint({"domain": "onlyalpha.agent-structured-hypothesis", **hypothesis.to_dict()})


def translate_agent_hypothesis_to_search_hypothesis(
    hypothesis: OnlyAgentStructuredHypothesisV1,
) -> OnlySearchHypothesisV1:
    """Freeze the V1 lossless identity bridge into Search hypothesis language.

    Search owns the executable statement.  Agent-only rationale, expected
    relationship, universe assumptions, and falsification context remain in the
    immutable Agent hypothesis and affect Search identity through its exact
    RESEARCH_NOTE source reference; no free-form rewriting occurs.
    """

    return OnlySearchHypothesisV1(
        hypothesis.statement,
        (
            OnlySearchHypothesisSourceReferenceV1(
                OnlySearchHypothesisSourceKind.RESEARCH_NOTE,
                only_agent_structured_hypothesis_fingerprint(hypothesis),
            ),
        ),
    )


def expected_agent_search_submit_semantics(
    *,
    operation_identity: str,
    context: OnlyVerifiedAgentDecisionContextV1,
    directive: OnlyAgentSearchDirectiveV1,
    runtime_generation_fingerprint: str,
) -> OnlyAgentProductRequestSemanticProjectionV1:
    """Compile the one exact Search Submit intent authorized by Agent facts."""

    payload = directive.action_payload
    if directive.router_action is OnlyAgentRouterAction.SYMBOLIC_SEARCH and isinstance(
        payload, OnlyAgentSymbolicSearchDirectiveV1
    ):
        method = "SYMBOLIC"
        workflow = ONLYAGENT_SYMBOLIC_SEARCH_WORKFLOW_BINDING_V1
        policy_fingerprint: str | None = None
    elif directive.router_action is OnlyAgentRouterAction.PARAMETER_SEARCH and isinstance(
        payload, OnlyAgentParameterSearchDirectiveV1
    ):
        method = "PARAMETER"
        workflow = ONLYAGENT_PARAMETER_SEARCH_WORKFLOW_BINDING_V1
        policy_fingerprint = payload.search_policy_reference.reference_fingerprint
    else:
        raise OnlyAgentContextError("AGENT_TOOL_OPERATION_NOT_ALLOWED", operation_identity)

    hypothesis = translate_agent_hypothesis_to_search_hypothesis(context.research_brief.hypothesis)
    return OnlyAgentProductRequestSemanticProjectionV1(
        operation_identity,
        {
            "method": method,
            "search_hypothesis_fingerprint": hypothesis.hypothesis_fingerprint,
            "search_space_fingerprint": payload.search_space_reference.reference_fingerprint,
            "evaluation_fingerprint": payload.evaluation_reference.reference_fingerprint,
            "algorithm_fingerprint": payload.algorithm_reference.reference_fingerprint,
            "search_budget_fingerprint": payload.search_budget_reference.reference_fingerprint,
            "search_policy_fingerprint": policy_fingerprint,
            "catalog_generation_fingerprint": context.research_brief.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": context.research_brief.dataset_snapshot_fingerprint,
            "workflow_binding": workflow.to_dict(),
            "decision_engine_binding": ONLYAGENT_SEARCH_DECISION_ENGINE_BINDING_V1.to_dict(),
            "parent_experiment_fingerprint": None,
            "runtime_generation_fingerprint": runtime_generation_fingerprint,
        },
    )


__all__ = [
    name
    for name in globals()
    if name.startswith("OnlyAgent")
    or name.startswith("ONLYAGENT")
    or name.startswith("expected_")
    or name.startswith("only_agent")
    or name.startswith("translate_")
]
