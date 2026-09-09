from __future__ import annotations

from dataclasses import replace

import pytest

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationExecutionMismatch,
    OnlyHistoricalGenerationProtocolMismatch,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
    OnlySearchGenerationWorkerHandshakeV1,
)

G = "1" * 64


def test_request_and_response_are_canonical_strict_roundtrips() -> None:
    request = OnlySearchGenerationExecutionRequestV1(
        G,
        OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
        {"value": [1, "x"]},
    )
    assert OnlySearchGenerationExecutionRequestV1.from_dict(request.to_dict()) == request
    assert (
        request.request_fingerprint
        == OnlySearchGenerationExecutionRequestV1.from_dict(request.to_dict()).request_fingerprint
    )

    response = OnlySearchGenerationExecutionResponseV1(G, request.operation_kind, {"answer": 3})
    assert OnlySearchGenerationExecutionResponseV1.from_dict(response.to_dict()) == response


@pytest.mark.parametrize("field", ["schema_version", "execution_contract_version"])
def test_contract_version_mismatch_fails_closed(field: str) -> None:
    request = OnlySearchGenerationExecutionRequestV1(
        G,
        OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
        {},
    ).to_dict()
    request[field] = 2 if field == "schema_version" else "UNSUPPORTED"
    with pytest.raises(OnlyHistoricalGenerationProtocolMismatch):
        OnlySearchGenerationExecutionRequestV1.from_dict(request)


def test_unknown_field_and_operation_are_rejected() -> None:
    request = OnlySearchGenerationExecutionRequestV1(
        G,
        OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
        {},
    ).to_dict()
    request["module"] = "os"
    with pytest.raises(OnlyHistoricalGenerationProtocolMismatch):
        OnlySearchGenerationExecutionRequestV1.from_dict(request)
    request.pop("module")
    request["operation_kind"] = "CALL_PYTHON"
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        OnlySearchGenerationExecutionRequestV1.from_dict(request)


def test_runtime_and_result_identity_mismatch_are_rejected() -> None:
    with pytest.raises(OnlyHistoricalGenerationProtocolMismatch):
        OnlySearchGenerationExecutionRequestV1(
            "not-a-generation",
            OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
            {},
        )
    response = OnlySearchGenerationExecutionResponseV1(
        G,
        OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
        {"answer": 3},
    )
    with pytest.raises(OnlyHistoricalGenerationExecutionMismatch):
        replace(response, result_fingerprint="2" * 64)


def test_handshake_capabilities_are_a_closed_allow_list() -> None:
    handshake = OnlySearchGenerationWorkerHandshakeV1(
        G,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        (
            OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
            OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
        ),
    )
    assert OnlySearchGenerationWorkerHandshakeV1.from_dict(handshake.to_dict()) == handshake
    payload = handshake.to_dict()
    payload["supported_capabilities"] = ["EXEC_MODULE"]
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        OnlySearchGenerationWorkerHandshakeV1.from_dict(payload)
