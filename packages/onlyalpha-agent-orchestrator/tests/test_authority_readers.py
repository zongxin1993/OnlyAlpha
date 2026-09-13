from __future__ import annotations

from collections.abc import Mapping

import pytest
from onlyalpha_agent_orchestrator.authority_readers import (
    OnlyApiBackedAgentBriefReferenceReaderV1,
    OnlyApiBackedAgentResearchStateReaderV1,
    OnlyApiBackedAgentSearchStateReaderV1,
)
from onlyalpha_agent_orchestrator.production import OnlyAgentProductionContextReaderV1

from onlyalpha.application.search_product import OnlySearchBoundedOperationV1
from onlyalpha.research.agent import OnlyAgentContextError
from onlyalpha.research.agent.occurrence import (
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentReferenceLocatorKind,
)
from onlyalpha.research.experiment.model import OnlySearchEvaluationContextReferenceV1
from tests.research.run.test_contract import specification

SHA = "a" * 64


def _ledger(*, plans: list[object] | None = None, results: list[object] | None = None) -> dict[str, object]:
    plans = [] if plans is None else plans
    results = [] if results is None else results
    return {
        "schema_version": 1,
        "experiment_fingerprint": SHA,
        "method": "SYMBOLIC",
        "ledger": {
            "method": "SYMBOLIC",
            "experiment_fingerprint": SHA,
            "plans": plans,
            "results": results,
            "expected_state": {
                "schema_version": 1,
                "experiment_fingerprint": SHA,
                "enumeration_result_fingerprint": None,
                "ordered_plan_states": [],
                "next_iteration_ordinal": 0,
                "research_attempt_count": 0,
                "qualification_attempt_count": 0,
                "target_plan_fingerprint": None,
            },
            "enumeration_result": None,
            "feedback_decisions": [],
            "frontier_fingerprint": None,
        },
    }


def _terminal() -> dict[str, object]:
    return {
        "schema_version": 1,
        "experiment_fingerprint": SHA,
        "method": "SYMBOLIC",
        "terminal_kind": "NON_TERMINAL",
        "terminal_fact": None,
        "stop_reason": None,
    }


class _Client:
    def __init__(self, responses: list[Mapping[str, object]]) -> None:
        self.responses = responses
        self.paths: list[str] = []

    def get_json_verified(self, path: str) -> Mapping[str, object]:
        self.paths.append(path)
        return self.responses.pop(0)


def test_search_reader_uses_ledger_terminal_ledger_and_derives_one_bounded_operation() -> None:
    client = _Client([_ledger(), _terminal(), _ledger()])
    view = OnlyApiBackedAgentSearchStateReaderV1(client).load_search_state_verified(SHA)
    assert view.next_bounded_operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
    assert client.paths == [
        f"/api/v2/research/search/experiments/{SHA}/ledger",
        f"/api/v2/research/search/experiments/{SHA}/terminal",
        f"/api/v2/research/search/experiments/{SHA}/ledger",
    ]


def test_torn_search_observation_fails_once_without_loop_or_mutation() -> None:
    changed = _ledger()
    changed["ledger"] = {**changed["ledger"], "frontier_fingerprint": "b" * 64}  # type: ignore[dict-item]
    client = _Client([_ledger(), _terminal(), changed])
    with pytest.raises(OnlyAgentContextError) as raised:
        OnlyApiBackedAgentSearchStateReaderV1(client).load_search_state_verified(SHA)
    assert raised.value.code == "AGENT_AUTHORITY_OBSERVATION_UNSTABLE"
    assert len(client.paths) == 3


def test_product_api_unavailable_fails_search_observation_once_without_guessing_state() -> None:
    class UnavailableClient:
        request_count = 0

        def get_json_verified(self, _path: str) -> Mapping[str, object]:
            self.request_count += 1
            raise OnlyAgentContextError("AGENT_TOOL_CALL_FAILED", "Product API unavailable")

    client = UnavailableClient()
    with pytest.raises(OnlyAgentContextError, match="AGENT_TOOL_CALL_FAILED"):
        OnlyApiBackedAgentSearchStateReaderV1(client).load_search_state_verified(SHA)
    assert client.request_count == 1


def test_search_reader_preserves_terminal_fact_identity_for_evidence_causality() -> None:
    terminal = _terminal()
    terminal["terminal_kind"] = "TERMINAL_SYMBOLIC_COMPLETION"
    terminal["terminal_fact"] = {
        "schema_version": 1,
        "enumeration_result_fingerprint": "b" * 64,
    }
    terminal["stop_reason"] = "SEARCH_SPACE_EXHAUSTED"
    client = _Client([_ledger(), terminal, _ledger()])
    view = OnlyApiBackedAgentSearchStateReaderV1(client).load_search_state_verified(SHA)
    assert view.terminal.terminal_fact is not None
    assert view.terminal.terminal_fact.enumeration_result_fingerprint == "b" * 64  # type: ignore[union-attr]


def test_brief_reference_reader_exact_verifies_all_product_identities() -> None:
    evaluation = OnlySearchEvaluationContextReferenceV1("ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT", 1, SHA)
    client = _Client(
        [
            {"catalog_generation_fingerprint": SHA, "extra_projection": "allowed"},
            {"schema_version": 1, "snapshot_fingerprint": SHA},
            {
                "schema_version": 1,
                "evaluation_kind": evaluation.evaluation_kind,
                "evaluation_schema_version": evaluation.evaluation_schema_version,
                "evaluation_fingerprint": evaluation.evaluation_fingerprint,
            },
        ]
    )
    reader = OnlyApiBackedAgentBriefReferenceReaderV1(client)
    assert reader.generation(SHA).generation_fingerprint == SHA
    assert reader.load_verified_table(SHA).snapshot.snapshot_fingerprint == SHA
    assert reader.load_evaluation_context_verified(evaluation).evaluation_fingerprint == SHA


def test_brief_reference_reader_fails_closed_on_identity_substitution() -> None:
    client = _Client([{"schema_version": 1, "snapshot_fingerprint": "b" * 64}])
    with pytest.raises(OnlyAgentContextError) as raised:
        OnlyApiBackedAgentBriefReferenceReaderV1(client).load_verified_table(SHA)
    assert raised.value.code == "AGENT_RESEARCH_BRIEF_REFERENCE_INVALID"


@pytest.mark.parametrize(
    "reference_kind",
    ["SYMBOLIC_SEARCH_SPACE", "PARAMETER_SEARCH_SPACE", "SEARCH_POLICY", "SEARCH_ALGORITHM"],
)
def test_brief_reference_reader_exact_verifies_existing_search_authorities(reference_kind: str) -> None:
    client = _Client(
        [
            {
                "schema_version": 1,
                "reference_kind": reference_kind,
                "reference_fingerprint": SHA,
                "payload": {"schema_version": 1, "identity": SHA},
            }
        ]
    )
    reference = OnlyAgentExactAuthorityReferenceV2(
        reference_kind,
        1,
        OnlyAgentReferenceLocatorKind.SHA256,
        SHA,
    )
    value = OnlyApiBackedAgentBriefReferenceReaderV1(client).load_search_authoring_reference_verified(reference)
    assert value.reference_kind == reference_kind
    assert value.reference_fingerprint == SHA


def test_brief_reference_reader_rejects_search_budget_and_identity_substitution() -> None:
    reader = OnlyApiBackedAgentBriefReferenceReaderV1(_Client([]))
    budget = OnlyAgentExactAuthorityReferenceV2("SEARCH_BUDGET", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    with pytest.raises(OnlyAgentContextError, match="AGENT_RESEARCH_BRIEF_REFERENCE_INVALID"):
        reader.load_search_authoring_reference_verified(budget)

    substituted = _Client(
        [
            {
                "schema_version": 1,
                "reference_kind": "SEARCH_POLICY",
                "reference_fingerprint": "b" * 64,
                "payload": {"schema_version": 1, "policy_fingerprint": "b" * 64},
            }
        ]
    )
    policy = OnlyAgentExactAuthorityReferenceV2("SEARCH_POLICY", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    with pytest.raises(OnlyAgentContextError, match="AGENT_RESEARCH_BRIEF_REFERENCE_INVALID"):
        OnlyApiBackedAgentBriefReferenceReaderV1(substituted).load_search_authoring_reference_verified(policy)


def test_research_reader_reconstructs_strict_uuid_addressed_product_dto() -> None:
    run_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    spec = specification()
    client = _Client(
        [
            {
                "schema_version": 2,
                "run_id": run_id,
                "revision": "0",
                "state": "QUEUED",
                "specification_schema_version": spec.schema_version,
                "specification_fingerprint": spec.specification_fingerprint,
                "admission_resolution_fingerprint": SHA,
                "specification": spec.to_dict(),
                "queued_at": "2026-09-12T00:00:00Z",
                "started_at": None,
                "cancel_requested_at": None,
                "finished_at": None,
                "result_ref": None,
                "artifact_ref": None,
                "failure": None,
            }
        ]
    )
    reference = OnlyAgentExactAuthorityReferenceV2("RESEARCH_RUN", 1, OnlyAgentReferenceLocatorKind.UUID4, run_id)
    run = OnlyApiBackedAgentResearchStateReaderV1(client).load_research_run_verified(reference)
    assert run.run_id.value == run_id
    assert run.specification == spec


def test_production_context_reads_statistics_from_statistics_authority_projection() -> None:
    client = _Client(
        [
            {
                "schema_version": 1,
                "statistics_result_fingerprint": SHA,
                "payload": {"manifest": {"statistics_result_fingerprint": SHA}, "rows": []},
            }
        ]
    )
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2("RESEARCH_STATISTICS", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    assert reader.load_semantic_payload_verified(reference)["rows"] == []
    assert client.paths == [f"/api/v2/research/statistics/{SHA}"]


def test_production_context_reads_iteration_result_from_search_provenance_projection() -> None:
    client = _Client(
        [
            {
                "schema_version": 1,
                "iteration_result_fingerprint": SHA,
                "payload": {
                    "schema_version": 1,
                    "iteration_result_fingerprint": SHA,
                    "research_result_reference": {"result_fingerprint": "b" * 64},
                },
            }
        ]
    )
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2(
        "SEARCH_ITERATION_RESULT", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA
    )
    assert reader.load_semantic_payload_verified(reference)["iteration_result_fingerprint"] == SHA
    assert client.paths == [f"/api/v2/research/search/iteration-results/{SHA}"]


def test_production_context_reads_terminal_projection_from_search_authority_projection() -> None:
    client = _Client(
        [
            {
                "schema_version": 1,
                "terminal_projection_fingerprint": SHA,
                "payload": {"schema_version": 1, "enumeration_result_fingerprint": SHA},
            }
        ]
    )
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2(
        "SEARCH_TERMINAL_PROJECTION", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA
    )
    assert reader.load_semantic_payload_verified(reference)["enumeration_result_fingerprint"] == SHA
    assert client.paths == [f"/api/v2/research/search/iteration-results/terminal-projections/{SHA}"]


def test_production_context_does_not_invent_search_expected_state_authority_lookup() -> None:
    client = _Client([])
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2(
        "SEARCH_EXPECTED_STATE", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA
    )

    reader.verify_exact_reference(reference)
    assert client.paths == []
    with pytest.raises(OnlyAgentContextError, match="AGENT_EXACT_AUTHORITY_REFERENCE_INVALID"):
        reader.load_semantic_payload_verified(reference)
    assert client.paths == []


def test_production_context_exact_verifies_historical_runtime_generation_not_active_projection() -> None:
    client = _Client(
        [
            {
                "schema_version": 1,
                "runtime_generation_fingerprint": SHA,
            }
        ]
    )
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2("RUNTIME_GENERATION", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)

    assert reader.load_semantic_payload_verified(reference)["runtime_generation_fingerprint"] == SHA
    assert client.paths == [f"/api/v2/research/runtime-generations/{SHA}"]


def test_production_context_never_attempts_search_budget_authoring_lookup() -> None:
    client = _Client([])
    reader = OnlyAgentProductionContextReaderV1(
        client=client,
        briefs=object(),  # type: ignore[arg-type]
        models=object(),  # type: ignore[arg-type]
        tools=object(),  # type: ignore[arg-type]
    )
    reference = OnlyAgentExactAuthorityReferenceV2("SEARCH_BUDGET", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)

    with pytest.raises(OnlyAgentContextError, match="AGENT_EXACT_AUTHORITY_REFERENCE_INVALID"):
        reader.load_semantic_payload_verified(reference)
    assert client.paths == []
