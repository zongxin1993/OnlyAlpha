from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.agent import (
    OnlyAgentBudgetV1,
    OnlyAgentContextError,
    OnlyAgentContextReferenceV1,
    OnlyAgentDecisionApplicationServiceV1,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentResearchBriefReferenceReadersV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentResearchBriefV2,
    OnlyAgentSearchMethod,
    OnlyAgentStructuredHypothesisV1,
    OnlyAgentSymbolicSearchDirectiveV2,
    only_agent_research_brief_from_dict,
    verify_agent_research_brief_references,
)
from onlyalpha.research.experiment import OnlySearchBudgetV1


def _reference(kind: str, digit: str) -> OnlyAgentContextReferenceV1:
    return OnlyAgentContextReferenceV1(kind, 1, digit * 64)


def _hypothesis() -> OnlyAgentStructuredHypothesisV1:
    return OnlyAgentStructuredHypothesisV1(
        "reversal",
        "Recent losers may reverse.",
        "Temporary liquidity pressure.",
        "Lower lagged return predicts higher forward return.",
        ("liquid instruments",),
        ("rank IC is non-positive",),
    )


def _brief_v2() -> OnlyAgentResearchBriefV2:
    references = tuple(
        sorted(
            (
                _reference("SYMBOLIC_SEARCH_SPACE", "d"),
                _reference("SEARCH_ALGORITHM", "e"),
            )
        )
    )
    return OnlyAgentResearchBriefV2(
        _hypothesis(),
        "a" * 64,
        "b" * 64,
        OnlyAgentEvaluationContextReferenceV1("ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT", 1, "c" * 64),
        (OnlyAgentSearchMethod.SYMBOLIC_SEARCH,),
        OnlyAgentBudgetV1(4, 12),
        OnlySearchBudgetV1(1, 1, 1),
        references,
    )


def test_brief_v1_bytes_and_parser_remain_exactly_backward_compatible() -> None:
    brief = OnlyAgentResearchBriefV1(
        _hypothesis(),
        "a" * 64,
        "b" * 64,
        OnlyAgentEvaluationContextReferenceV1("ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT", 1, "c" * 64),
        (OnlyAgentSearchMethod.SYMBOLIC_SEARCH,),
        OnlyAgentBudgetV1(4, 12),
    )
    encoded = only_canonical_json(brief.to_dict())
    loaded = only_agent_research_brief_from_dict(brief.to_dict())
    assert type(loaded) is OnlyAgentResearchBriefV1
    assert only_canonical_json(loaded.to_dict()) == encoded


def test_brief_v2_identity_binds_distinct_search_budget_and_exact_authoring_allowlist() -> None:
    brief = _brief_v2()
    loaded = only_agent_research_brief_from_dict(brief.to_dict())
    assert loaded == brief
    assert loaded.requested_child_search_budget_fingerprint == only_canonical_fingerprint(
        brief.requested_child_search_budget.to_dict()
    )
    assert (
        replace(
            brief,
            requested_child_search_budget=OnlySearchBudgetV1(2, 1, 1),
            research_brief_fingerprint="",
        ).research_brief_fingerprint
        != brief.research_brief_fingerprint
    )
    with pytest.raises(ValueError, match="AUTHORING_REFERENCES_INVALID"):
        replace(
            brief,
            ordered_search_authoring_references=tuple(reversed(brief.ordered_search_authoring_references)),
            research_brief_fingerprint="",
        )
    with pytest.raises(ValueError, match="AUTHORING_REFERENCES_INVALID"):
        replace(
            brief,
            ordered_search_authoring_references=(_reference("SEARCH_BUDGET", "f"),),
            research_brief_fingerprint="",
        )


def test_brief_v2_admission_exact_verifies_every_authoring_reference() -> None:
    brief = _brief_v2()

    class Readers:
        def generation(self, fingerprint: str):  # type: ignore[no-untyped-def]
            return SimpleNamespace(generation_fingerprint=fingerprint)

        def load_verified_table(self, fingerprint: str):  # type: ignore[no-untyped-def]
            return SimpleNamespace(snapshot=SimpleNamespace(snapshot_fingerprint=fingerprint))

        def load_evaluation_context_verified(self, reference):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                evaluation_kind=reference.evaluation_kind,
                evaluation_schema_version=reference.evaluation_schema_version,
                evaluation_fingerprint=reference.evaluation_fingerprint,
            )

        def load_search_authoring_reference_verified(self, reference):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                reference_kind=reference.reference_kind,
                reference_schema_version=reference.reference_schema_version,
                reference_fingerprint=reference.reference_fingerprint,
            )

    readers = Readers()
    verify_agent_research_brief_references(
        brief,
        OnlyAgentResearchBriefReferenceReadersV1(readers, readers, readers, readers),  # type: ignore[arg-type]
    )
    with pytest.raises(OnlyAgentContextError, match="AGENT_RESEARCH_BRIEF_REFERENCE_INVALID"):
        verify_agent_research_brief_references(
            brief,
            OnlyAgentResearchBriefReferenceReadersV1(readers, readers, readers),  # type: ignore[arg-type]
        )


def test_v2_directive_budget_is_brief_derived_and_authoring_selection_is_allowlisted() -> None:
    brief = _brief_v2()

    class References:
        def verify_exact_reference(self, _reference):  # type: ignore[no-untyped-def]
            return None

    service = OnlyAgentDecisionApplicationServiceV1(
        sessions=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
        references=References(),  # type: ignore[arg-type]
        store=object(),  # type: ignore[arg-type]
    )
    context = SimpleNamespace(research_brief=brief)
    valid = OnlyAgentSymbolicSearchDirectiveV2(
        _reference("SYMBOLIC_SEARCH_SPACE", "d"),
        _reference("RESEARCH_EVALUATION", "c"),
        _reference("SEARCH_ALGORITHM", "e"),
        brief.requested_child_search_budget_fingerprint,
    )
    service._verify_action_references(valid, context)  # type: ignore[arg-type]
    with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
        service._verify_action_references(
            replace(valid, search_space_reference=_reference("SYMBOLIC_SEARCH_SPACE", "f")),
            context,  # type: ignore[arg-type]
        )
    with pytest.raises(OnlyAgentContextError, match="Search Budget binding"):
        service._verify_action_references(
            replace(valid, search_budget_fingerprint="f" * 64),
            context,  # type: ignore[arg-type]
        )
