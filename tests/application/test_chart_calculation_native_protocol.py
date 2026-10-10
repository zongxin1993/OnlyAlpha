from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.application.chart_calculation_native_protocol import (
    ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION,
    OnlyChartCalculationNativeExecutionRequestV1,
    OnlyChartCalculationNativePublicationProfileV1,
    OnlyChartCalculationNativeWorkerHandshakeV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.run.model import OnlyResearchRunId, OnlyResearchRunState
from tests.application.test_chart_calculation_compilation import compilation
from tests.support.chart_calculation_compilation import prepared_input


@pytest.fixture
def frozen(tmp_path: Path):
    return compilation(prepared_input(tmp_path))


def native_request(frozen):
    return OnlyChartCalculationNativeExecutionRequestV1(
        frozen.operation_id,
        OnlyResearchRunId(frozen.runtime_work_id),
        OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000821"),
        OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000822"),
        1,
        1,
        frozen.compilation_fingerprint,
        frozen.runtime_generation_fingerprint,
    )


def handshake():
    return OnlyChartCalculationNativeWorkerHandshakeV1(
        OnlyResearchRuntimeExecutionProvenanceV1("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    )


def test_exact_profile_and_request_roundtrip_is_structural_only(frozen, monkeypatch) -> None:
    request = native_request(frozen)
    assert OnlyChartCalculationNativeExecutionRequestV1.from_dict(request.to_dict()) == request
    request.verify_compilation(frozen)
    assert OnlyChartCalculationNativeWorkerHandshakeV1.from_dict(handshake().to_dict()) == handshake()
    assert request.execution_contract_version == ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION
    assert request.profile.publication == frozen.specification.publication
    assert set(request.to_dict()) == set(OnlyChartCalculationNativeExecutionRequestV1.__dataclass_fields__)
    from onlyalpha.application.chart_calculation_run_admission import only_chart_calculation_queued_run
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
    from onlyalpha.research.run.errors import OnlyResearchRunStateConflictError
    from tests.application.test_chart_calculation_admission import NOW

    run = only_chart_calculation_queued_run(frozen, queued_at=NOW)

    def forbidden(*args, **kwargs):
        raise AssertionError("a structural protocol DTO bypassed the generic Store execution fence")

    monkeypatch.setattr("onlyalpha.persistence.postgres.research_run_store.psycopg.connect", forbidden)
    # A representable Domain successor and complete protocol DTO STILL cannot
    # commit execution through the generic Store or mint an Attempt permission.
    with pytest.raises(OnlyResearchRunStateConflictError, match="fenced Research Execution Store"):
        OnlyPostgresResearchRunStore("dbname=onlyalpha_test").commit_transition(
            run, run.transition(OnlyResearchRunState.RUNNING, at=NOW)
        )


@pytest.mark.parametrize(
    "model", [OnlyChartCalculationNativePublicationProfileV1, OnlyChartCalculationNativeWorkerHandshakeV1]
)
def test_profile_and_handshake_require_every_field(model) -> None:
    value = (
        OnlyChartCalculationNativePublicationProfileV1()
        if model is OnlyChartCalculationNativePublicationProfileV1
        else handshake()
    )
    for name in value.to_dict():
        raw = value.to_dict()
        del raw[name]
        with pytest.raises(ValueError):
            model.from_dict(raw)
        raw = value.to_dict()
        raw[name] = None
        with pytest.raises(ValueError):
            model.from_dict(raw)
    raw = value.to_dict() | {"unexpected": None}
    with pytest.raises(ValueError):
        model.from_dict(raw)


@pytest.mark.parametrize("name", tuple(OnlyChartCalculationNativeExecutionRequestV1.__dataclass_fields__))
@pytest.mark.parametrize("mutation", ["missing", "null"])
def test_request_requires_every_occurrence_and_context_dimension(frozen, name: str, mutation: str) -> None:
    raw = native_request(frozen).to_dict()
    if mutation == "missing":
        del raw[name]
    else:
        raw[name] = None
    with pytest.raises(ValueError):
        OnlyChartCalculationNativeExecutionRequestV1.from_dict(raw)


@pytest.mark.parametrize(
    "name,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("execution_contract_version", "ONLYALPHA_SEARCH_GENERATION_EXECUTION_V1"),
        ("execution_contract_version", "EXECUTE_CHART_CALCULATION_PROJECTION"),
        ("execution_contract_version", "RESOLVE_RESEARCH_CALCULATION_PUBLICATION"),
        ("attempt_number", True),
        ("attempt_number", 0),
        ("run_revision", True),
        ("run_revision", 0),
        ("operation_id", "00000000-0000-0000-0000-000000000000"),
        ("attempt_id", "00000000-0000-1000-8000-000000000821"),
        ("worker_instance_id", "FOREIGN"),
        ("compilation_fingerprint", "A" * 64),
        ("runtime_generation_fingerprint", "unavailable"),
        ("graph", {}),
        ("values", []),
        ("readiness", []),
        ("dsn", "caller-credentials"),
        ("dataset_store_root", "/caller-controlled-root"),
        ("verified_input", {}),
        ("status", "EXECUTED_UNPUBLISHED"),
    ],
)
def test_request_rejects_coercions_wrong_protocol_and_caller_authority(frozen, name: str, value: object) -> None:
    raw = native_request(frozen).to_dict() | {name: value}
    with pytest.raises(ValueError):
        OnlyChartCalculationNativeExecutionRequestV1.from_dict(raw)


@pytest.mark.parametrize(
    "name,value",
    [
        ("schema_version", True),
        ("specification_schema_version", True),
        ("specification_schema_version", 2),
        ("job_plan_schema_version", 1),
        ("result_plan_schema_version", 3),
        ("research_result_schema_version", 3),
        ("artifact_schema_version", 1),
        ("origin_kind", "GENERAL"),
        ("origin_kind", "PRIVATE_STRATEGY"),
        ("publication", {}),
    ],
)
def test_profile_rejects_wrong_origin_or_publication_family(name: str, value: object) -> None:
    raw = OnlyChartCalculationNativePublicationProfileV1().to_dict() | {name: value}
    with pytest.raises(ValueError):
        OnlyChartCalculationNativePublicationProfileV1.from_dict(raw)


@pytest.mark.parametrize("name", tuple(OnlyChartCalculationNativePublicationProfileV1().publication.to_dict()))
def test_nested_publication_dimensions_are_mandatory_and_exact(name: str) -> None:
    raw = OnlyChartCalculationNativePublicationProfileV1().to_dict()
    raw["publication"][name] = True
    with pytest.raises(ValueError):
        OnlyChartCalculationNativePublicationProfileV1.from_dict(raw)


@pytest.mark.parametrize("name", tuple(handshake().runtime_provenance.to_dict()))
def test_handshake_mandatory_runtime_provenance_is_not_a_leaf_hash(name: str) -> None:
    for replacement in (None, True):
        raw = handshake().to_dict()
        raw["runtime_provenance"][name] = replacement
        with pytest.raises(ValueError):
            OnlyChartCalculationNativeWorkerHandshakeV1.from_dict(raw)
    raw = handshake().to_dict()
    del raw["runtime_provenance"][name]
    with pytest.raises(ValueError):
        OnlyChartCalculationNativeWorkerHandshakeV1.from_dict(raw)


@pytest.mark.parametrize("dimension", ["operation", "work", "compilation", "generation", "whole_context"])
def test_complete_different_context_is_not_the_original_relation(frozen, dimension: str) -> None:
    request = native_request(frozen)
    different = replace(
        request,
        **{
            "operation": {"operation_id": OnlyProductCommandId("00000000-0000-4000-8000-000000000823")},
            "work": {"run_id": OnlyResearchRunId("00000000-0000-4000-8000-000000000824")},
            "compilation": {"compilation_fingerprint": "f" * 64},
            "generation": {"runtime_generation_fingerprint": "f" * 64},
            "whole_context": {
                "operation_id": OnlyProductCommandId("00000000-0000-4000-8000-000000000823"),
                "run_id": OnlyResearchRunId("00000000-0000-4000-8000-000000000824"),
                "compilation_fingerprint": "f" * 64,
                "runtime_generation_fingerprint": "f" * 64,
            },
        }[dimension],
    )
    assert OnlyChartCalculationNativeExecutionRequestV1.from_dict(different.to_dict()) == different
    with pytest.raises(ValueError, match="frozen relation differs"):
        different.verify_compilation(frozen)


def test_operation_cannot_replace_reserved_run_and_mutation_is_rechecked(frozen) -> None:
    request = native_request(frozen)
    with pytest.raises(ValueError, match="reserved Run"):
        replace(request, run_id=OnlyResearchRunId(request.operation_id.value))
    object.__setattr__(request, "run_revision", True)
    with pytest.raises(ValueError):
        request.verify_compilation(frozen)


@pytest.mark.parametrize("carrier", ["request", "request_payload", "handshake", "handshake_payload", "e1_projection"])
def test_structural_native_declarations_cannot_issue_source_or_producer_authority(frozen, carrier: str) -> None:
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
    from onlyalpha.research.calculation.execution_provenance import _only_require_research_runtime_execution_context
    from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input

    request = native_request(frozen)
    value = {
        "request": request,
        "request_payload": request.to_dict(),
        "handshake": handshake(),
        "handshake_payload": handshake().to_dict(),
        "e1_projection": {"status": "EXECUTED_UNPUBLISHED", "values": [], "readiness": []},
    }[carrier]
    request.verify_compilation(frozen)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        _only_require_research_runtime_execution_context(value, frozen.graph_fingerprint)
    with pytest.raises(ValueError, match="reader-issued sealed input required"):
        _only_require_verified_sealed_chart_publication_input(
            value, frozen.result_plan_fingerprint, frozen.graph_fingerprint, frozen.runtime_generation_fingerprint
        )


@pytest.mark.parametrize(
    "capability", [ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION, "EXECUTE_CHART_NATIVE_PUBLICATION"]
)
def test_compute_only_search_parsers_reject_native_capability_declarations(capability: str) -> None:
    from onlyalpha.application.search_generation_execution import (
        ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
        OnlyHistoricalGenerationCapabilityUnsupported,
        OnlySearchGenerationExecutionRequestV1,
        OnlySearchGenerationWorkerHandshakeV1,
    )

    common = {
        "schema_version": 1,
        "execution_contract_version": ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
        "runtime_generation_fingerprint": "a" * 64,
    }
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        OnlySearchGenerationExecutionRequestV1.from_dict(common | {"operation_kind": capability, "request_payload": {}})
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        OnlySearchGenerationWorkerHandshakeV1.from_dict(
            common
            | {
                "core_execution_fingerprint": "b" * 64,
                "catalog_generation_fingerprint": "c" * 64,
                "validation_evidence_fingerprint": "d" * 64,
                "supported_capabilities": [capability],
            }
        )
