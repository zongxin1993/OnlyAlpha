from __future__ import annotations

from uuid import UUID

import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.agent import (
    OnlyAgentContextReferenceV1,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentObservedResponseStorageKind,
    OnlyAgentReferenceLocatorKind,
    OnlyAgentResearchRunAuthorityReaderV1,
    OnlyAgentToolCallOutcome,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
    OnlyAgentToolClass,
    only_agent_exact_authority_reference_from_dict,
    only_agent_exact_reference_from_schema,
    only_agent_reference_schema_extensions,
    only_agent_reference_sort_key,
    validate_agent_strict_schema,
    validate_agent_strict_value,
)
from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.occurrence_store import OnlyJsonAgentToolOccurrenceStore
from onlyalpha.research.run import OnlyResearchRunId
from tests.research.run.test_contract import _queued

RUN_A = str(UUID(int=401, version=4))
RUN_B = str(UUID(int=402, version=4))
SHA = "a" * 64


def test_historical_sha_only_reference_cannot_represent_canonical_research_run_uuid4() -> None:
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyAgentContextReferenceV1("RESEARCH_RUN", 1, RUN_A)


def test_v2_exact_reference_strictly_discriminates_sha256_and_uuid4() -> None:
    sha = OnlyAgentExactAuthorityReferenceV2("CATALOG_GENERATION", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    run = OnlyAgentExactAuthorityReferenceV2("RESEARCH_RUN", 1, OnlyAgentReferenceLocatorKind.UUID4, RUN_A)
    assert sha.to_dict() == {
        "schema_version": 2,
        "reference_kind": "CATALOG_GENERATION",
        "reference_schema_version": 1,
        "locator_kind": "SHA256",
        "locator_value": SHA,
    }
    assert OnlyAgentExactAuthorityReferenceV2.from_dict(run.to_dict()) == run
    assert only_agent_exact_authority_reference_from_dict(sha.to_dict()) == sha
    assert sha != run
    assert only_agent_reference_sort_key(sha) != only_agent_reference_sort_key(run)


@pytest.mark.parametrize(
    ("kind", "locator_kind", "value"),
    (
        ("RESEARCH_RUN", OnlyAgentReferenceLocatorKind.SHA256, SHA),
        ("CATALOG_GENERATION", OnlyAgentReferenceLocatorKind.UUID4, RUN_A),
        ("RESEARCH_RUN", OnlyAgentReferenceLocatorKind.UUID4, "00000000-0000-1000-8000-000000000191"),
        ("RESEARCH_RUN", OnlyAgentReferenceLocatorKind.UUID4, "550E8400-E29B-41D4-A716-446655440000"),
        ("RESEARCH_RUN", OnlyAgentReferenceLocatorKind.UUID4, f"{{{RUN_A}}}"),
        ("CATALOG_GENERATION", OnlyAgentReferenceLocatorKind.SHA256, "A" * 64),
        ("CATALOG_GENERATION", OnlyAgentReferenceLocatorKind.SHA256, "a" * 63),
    ),
)
def test_v2_exact_reference_rejects_invalid_or_wrong_locator_domain(
    kind: str, locator_kind: OnlyAgentReferenceLocatorKind, value: str
) -> None:
    with pytest.raises(ValueError):
        OnlyAgentExactAuthorityReferenceV2(kind, 1, locator_kind, value)


def test_reference_union_rejects_unknown_missing_and_ambiguous_fields() -> None:
    valid = OnlyAgentExactAuthorityReferenceV2("RESEARCH_RUN", 1, OnlyAgentReferenceLocatorKind.UUID4, RUN_A).to_dict()
    for payload in (
        {**valid, "unexpected": True},
        {key: value for key, value in valid.items() if key != "locator_kind"},
        {**valid, "schema_version": 1},
    ):
        with pytest.raises(ValueError):
            only_agent_exact_authority_reference_from_dict(payload)


def test_reference_union_is_nominal_and_rejects_structurally_similar_objects() -> None:
    class ReferenceLookalike:
        reference_kind = "RESEARCH_RUN"
        reference_schema_version = 1
        locator_kind = OnlyAgentReferenceLocatorKind.UUID4
        locator_value = RUN_A

        def to_dict(self) -> dict[str, object]:
            return _run_reference(RUN_A).to_dict()

    with pytest.raises(ValueError, match="AGENT_TOOL_CALL_PLAN_INVALID"):
        OnlyAgentToolCallPlanV1(
            "1" * 64,
            0,
            "7" * 64,
            OnlyAgentToolClass.RESEARCH_RUN_QUERY,
            2,
            "8" * 64,
            "research_run_query.v1",
            {"run_id": RUN_A},
            exact_identity_inputs=(ReferenceLookalike(),),  # type: ignore[arg-type]
            tool_policy_fingerprint="5" * 64,
        )


def _historical_values() -> tuple[
    OnlyAgentContextReferenceV1,
    OnlyAgentModelCallPlanV1,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
]:
    reference = OnlyAgentContextReferenceV1("CATALOG_GENERATION", 1, SHA)
    setting = OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, "0")
    model_plan = OnlyAgentModelCallPlanV1(
        "1" * 64,
        0,
        "ROLE",
        "2" * 64,
        "provider",
        "model",
        "v1",
        "3" * 64,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        (setting,),
        (reference,),
    )
    tool_plan = OnlyAgentToolCallPlanV1(
        "1" * 64,
        0,
        "7" * 64,
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        2,
        "8" * 64,
        "exact.v1",
        {"id": SHA},
        exact_identity_inputs=(reference,),
        tool_policy_fingerprint="5" * 64,
    )
    response = {"id": SHA}
    tool_result = OnlyAgentToolCallResultV1(
        tool_plan.tool_call_plan_fingerprint,
        OnlyAgentToolCallOutcome.SUCCEEDED,
        OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
        response,
        None,
        only_canonical_fingerprint(response),
        (reference,),
    )
    return reference, model_plan, tool_plan, tool_result


def test_historical_v1_bytes_fingerprints_and_readers_are_frozen() -> None:
    reference, model_plan, tool_plan, tool_result = _historical_values()
    assert only_canonical_json(reference.to_dict()).strip() == (
        '{"reference_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"reference_kind":"CATALOG_GENERATION","reference_schema_version":1}'
    )
    assert model_plan.model_call_plan_fingerprint == "8d882b2b1d878998331ba1d96d50f597aea7ff2f81065ad4fc350cca96b46334"
    assert tool_plan.tool_call_plan_fingerprint == "a1b171ce3285510c63aa7dba2c67ec4372ca7195dd912ded8f8c5e1531c0a26f"
    assert (
        tool_result.tool_call_result_fingerprint == "9609bfe6af08c9af03b8db95a7130ed1b2e6018b6ec1bfd3dab3d7434f68044c"
    )
    assert OnlyAgentContextReferenceV1.from_dict(reference.to_dict()) == reference
    assert OnlyAgentModelCallPlanV1.from_dict(model_plan.to_dict()) == model_plan
    assert OnlyAgentToolCallPlanV1.from_dict(tool_plan.to_dict()) == tool_plan
    assert OnlyAgentToolCallResultV1.from_dict(tool_result.to_dict()) == tool_result


class _Runs:
    def __init__(self, *, wrong: bool = False) -> None:
        self.runs = {OnlyResearchRunId(RUN_A): _queued(RUN_A), OnlyResearchRunId(RUN_B): _queued(RUN_B)}
        self.wrong = wrong
        self.requested: list[OnlyResearchRunId] = []

    def get_run(self, run_id: OnlyResearchRunId):  # type: ignore[no-untyped-def]
        self.requested.append(run_id)
        if self.wrong:
            return self.runs[OnlyResearchRunId(RUN_B)]
        return self.runs[run_id]


def _run_reference(value: str) -> OnlyAgentExactAuthorityReferenceV2:
    return OnlyAgentExactAuthorityReferenceV2("RESEARCH_RUN", 1, OnlyAgentReferenceLocatorKind.UUID4, value)


def test_research_run_reader_exact_loads_the_passed_uuid_and_rejects_wrong_or_missing() -> None:
    queries = _Runs()
    reader = OnlyAgentResearchRunAuthorityReaderV1(queries)  # type: ignore[arg-type]
    assert reader.load_research_run_verified(_run_reference(RUN_A)).run_id == OnlyResearchRunId(RUN_A)
    assert reader.load_research_run_verified(_run_reference(RUN_B)).run_id == OnlyResearchRunId(RUN_B)
    assert queries.requested == [OnlyResearchRunId(RUN_A), OnlyResearchRunId(RUN_B)]

    with pytest.raises(OnlyAgentContextError):
        OnlyAgentResearchRunAuthorityReaderV1(_Runs(wrong=True)).load_research_run_verified(  # type: ignore[arg-type]
            _run_reference(RUN_A)
        )
    with pytest.raises(OnlyAgentContextError):
        reader.load_research_run_verified(_run_reference(str(UUID(int=499, version=4))))
    with pytest.raises(OnlyAgentContextError):
        reader.load_research_run_verified(OnlyAgentContextReferenceV1("RESEARCH_RUN", 1, SHA))


def test_schema_reference_closure_derives_typed_locators_without_value_shape_inference() -> None:
    catalog_schema = {
        "type": "string",
        **only_agent_reference_schema_extensions("CATALOG_GENERATION", 1, OnlyAgentReferenceLocatorKind.SHA256),
    }
    run_schema = {
        "type": "string",
        **only_agent_reference_schema_extensions("RESEARCH_RUN", 1, OnlyAgentReferenceLocatorKind.UUID4),
    }
    catalog = only_agent_exact_reference_from_schema(SHA, catalog_schema)
    run = only_agent_exact_reference_from_schema(RUN_A, run_schema)
    assert isinstance(catalog, OnlyAgentExactAuthorityReferenceV2)
    assert isinstance(run, OnlyAgentExactAuthorityReferenceV2)
    validate_agent_strict_schema(catalog_schema)
    validate_agent_strict_schema(run_schema)
    assert validate_agent_strict_value(SHA, catalog_schema, allowed_context_references=(catalog,)) == SHA
    assert validate_agent_strict_value(RUN_A, run_schema, allowed_context_references=(run,)) == RUN_A


@pytest.mark.parametrize(
    ("reference_kind", "locator_kind"),
    (
        ("RESEARCH_RUN", OnlyAgentReferenceLocatorKind.SHA256),
        ("CATALOG_GENERATION", OnlyAgentReferenceLocatorKind.UUID4),
    ),
)
def test_schema_reference_closure_rejects_wrong_authority_locator_pair(
    reference_kind: str, locator_kind: OnlyAgentReferenceLocatorKind
) -> None:
    with pytest.raises(ValueError):
        only_agent_reference_schema_extensions(reference_kind, 1, locator_kind)


def test_tool_occurrences_accept_v2_run_reference_without_changing_outer_v1_contract() -> None:
    run = _run_reference(RUN_A)
    first = OnlyAgentToolCallPlanV1(
        "1" * 64,
        0,
        "7" * 64,
        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        2,
        "8" * 64,
        "research_run_query.v1",
        {"run_id": RUN_A},
        exact_identity_inputs=(run,),
        tool_policy_fingerprint="5" * 64,
    )
    later = OnlyAgentToolCallPlanV1(
        "1" * 64,
        1,
        "7" * 64,
        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        2,
        "8" * 64,
        "research_run_query.v1",
        {"run_id": RUN_A},
        exact_identity_inputs=(run,),
        tool_policy_fingerprint="5" * 64,
    )
    assert first.schema_version == later.schema_version == 1
    assert first.exact_identity_inputs == later.exact_identity_inputs == (run,)
    assert first.tool_call_plan_fingerprint != later.tool_call_plan_fingerprint


def test_complete_typed_reference_structure_participates_in_containing_fact_identity() -> None:
    catalog = OnlyAgentExactAuthorityReferenceV2("CATALOG_GENERATION", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    product = OnlyAgentExactAuthorityReferenceV2("PRODUCT_FACT", 1, OnlyAgentReferenceLocatorKind.SHA256, SHA)
    newer_catalog_schema = OnlyAgentExactAuthorityReferenceV2(
        "CATALOG_GENERATION", 2, OnlyAgentReferenceLocatorKind.SHA256, SHA
    )

    def plan(reference: OnlyAgentExactAuthorityReferenceV2) -> OnlyAgentToolCallPlanV1:
        return OnlyAgentToolCallPlanV1(
            "1" * 64,
            0,
            "7" * 64,
            OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
            2,
            "8" * 64,
            "exact.v1",
            {"id": SHA},
            exact_identity_inputs=(reference,),
            tool_policy_fingerprint="5" * 64,
        )

    identities = {plan(reference).tool_call_plan_fingerprint for reference in (catalog, product, newer_catalog_schema)}
    assert len(identities) == 3


def test_mixed_v1_v2_tool_occurrence_exact_load_preserves_nested_versions(tmp_path) -> None:
    historical, _, _, _ = _historical_values()
    run = _run_reference(RUN_A)
    plan = OnlyAgentToolCallPlanV1(
        "1" * 64,
        0,
        "7" * 64,
        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        2,
        "8" * 64,
        "research_run_query.v1",
        {"run_id": RUN_A, "catalog_generation_fingerprint": SHA},
        exact_identity_inputs=(historical, run),
        tool_policy_fingerprint="5" * 64,
    )
    response = {"revision": 1, "run_id": RUN_A, "state": "RUNNING"}
    result = OnlyAgentToolCallResultV1(
        plan.tool_call_plan_fingerprint,
        OnlyAgentToolCallOutcome.SUCCEEDED,
        OnlyAgentObservedResponseStorageKind.INLINE_CANONICAL_RESPONSE,
        response,
        None,
        only_canonical_fingerprint(response),
        (run,),
    )
    store = OnlyJsonAgentToolOccurrenceStore(tmp_path)
    store.commit_plan(plan)
    store.commit_result(result)
    assert store.load_plan_verified(plan.tool_call_plan_fingerprint) == plan
    assert store.load_result_verified(result.tool_call_result_fingerprint) == result
