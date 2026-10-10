from __future__ import annotations

import json

import pytest

from onlyalpha.application.chart_calculation_native_protocol import (
    OnlyChartCalculationNativeExecutionRequestV1,
    only_decode_chart_native_request,
)
from onlyalpha.canonical import only_canonical_json
from tests.application.test_chart_calculation_native_protocol import frozen as frozen
from tests.application.test_chart_calculation_native_protocol import native_request


def test_wire_request_roundtrip_is_not_execution_permission(frozen):
    request = native_request(frozen)
    wire = (only_canonical_json(request.to_dict()) + "\n").encode()
    assert only_decode_chart_native_request(wire) == request
    assert type(only_decode_chart_native_request(wire)) is OnlyChartCalculationNativeExecutionRequestV1


@pytest.mark.parametrize("dimension", ["owner", "profile", "publication"])
def test_wire_duplicate_keys_are_rejected_at_every_depth(frozen, dimension):
    raw = only_canonical_json(native_request(frozen).to_dict())
    name = {"owner": "run_id", "profile": "origin_kind", "publication": "calculation_result_schema_version"}[dimension]
    payload = json.loads(raw)
    value = (
        payload[name]
        if dimension == "owner"
        else payload["profile"][name]
        if dimension == "profile"
        else payload["profile"]["publication"][name]
    )
    field = json.dumps(name) + ":" + json.dumps(value)
    assert field in raw
    duplicate = raw.replace(field, field + "," + field, 1)
    with pytest.raises(ValueError, match="duplicate"):
        only_decode_chart_native_request((duplicate + "\n").encode())


@pytest.mark.parametrize(
    "wire", [b"", b"{}", b"{}\n{}\n", b"{}\r\n", b"\xff\n", b"[]\n", b"null\n", b'{"x":NaN}\n', b'{"x":Infinity}\n']
)
def test_wire_rejects_partial_multiple_noncanonical_or_nonobject_frames(wire):
    with pytest.raises(ValueError):
        only_decode_chart_native_request(wire)


def test_wire_limit_is_checked_before_json_decoding(frozen):
    from onlyalpha.application.chart_calculation_native_protocol import ONLYALPHA_CHART_NATIVE_MAX_WIRE_BYTES

    raw = (only_canonical_json(native_request(frozen).to_dict()) + "\n").encode()
    oversized = b" " * ONLYALPHA_CHART_NATIVE_MAX_WIRE_BYTES + raw
    with pytest.raises(ValueError, match="limit"):
        only_decode_chart_native_request(oversized)


@pytest.mark.parametrize("field", ["dsn", "module", "graph", "issued_input", "storage_root"])
def test_wire_cannot_select_configuration_or_carry_issued_capability(frozen, field):
    raw = native_request(frozen).to_dict() | {field: "caller-controlled"}
    with pytest.raises(ValueError):
        only_decode_chart_native_request((only_canonical_json(raw) + "\n").encode())


def receipt_payload(frozen):
    from tests.application.test_chart_calculation_native_protocol import handshake

    provenance = handshake().runtime_provenance.to_dict()
    provenance["runtime_generation_fingerprint"] = frozen.runtime_generation_fingerprint
    return {
        "schema_version": 1,
        "request": native_request(frozen).to_dict(),
        "runtime_provenance": provenance,
        "research_result_plan_fingerprint": frozen.result_plan_fingerprint,
        "calculation_fingerprint": frozen.resolution.job_plan.calculation_fingerprint,
        "calculation_result_fingerprint": "1" * 64,
        "execution_evidence_fingerprint": "2" * 64,
        "research_result_fingerprint": "3" * 64,
        "artifact_content_fingerprint": "4" * 64,
    }


def test_receipt_binds_exact_request_and_frozen_plan_without_minting_seal(frozen):
    from onlyalpha.application.chart_calculation_native_protocol import (
        OnlyChartCalculationNativePublicationReceiptV1,
        only_decode_chart_native_receipt,
    )
    from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input

    raw = receipt_payload(frozen)
    receipt = only_decode_chart_native_receipt((only_canonical_json(raw) + "\n").encode())
    assert OnlyChartCalculationNativePublicationReceiptV1.from_dict(raw) == receipt
    assert receipt.to_dict() == raw
    receipt.verify_compilation(frozen)
    with pytest.raises(ValueError, match="reader-issued sealed input required"):
        _only_require_verified_sealed_chart_publication_input(
            receipt, frozen.result_plan_fingerprint, frozen.graph_fingerprint, frozen.runtime_generation_fingerprint
        )


@pytest.mark.parametrize(
    "dimension", ["runtime_generation_fingerprint", "research_result_plan_fingerprint", "calculation_fingerprint"]
)
def test_receipt_complete_different_identity_cannot_match_original_compilation(frozen, dimension):
    from onlyalpha.application.chart_calculation_native_protocol import OnlyChartCalculationNativePublicationReceiptV1

    raw = receipt_payload(frozen)
    if dimension == "runtime_generation_fingerprint":
        raw["runtime_provenance"][dimension] = "f" * 64
        with pytest.raises(ValueError, match="Generation"):
            OnlyChartCalculationNativePublicationReceiptV1.from_dict(raw)
    else:
        raw[dimension] = "f" * 64
        receipt = OnlyChartCalculationNativePublicationReceiptV1.from_dict(raw)
        with pytest.raises(ValueError, match="frozen"):
            receipt.verify_compilation(frozen)


def test_receipt_requires_all_references_and_rejects_permission_fields(frozen):
    from onlyalpha.application.chart_calculation_native_protocol import OnlyChartCalculationNativePublicationReceiptV1

    for field in receipt_payload(frozen):
        for null in (False, True):
            raw = receipt_payload(frozen)
            if null:
                raw[field] = None
            else:
                del raw[field]
            with pytest.raises(ValueError):
                OnlyChartCalculationNativePublicationReceiptV1.from_dict(raw)
    raw = receipt_payload(frozen) | {"seal": "fake"}
    with pytest.raises(ValueError):
        OnlyChartCalculationNativePublicationReceiptV1.from_dict(raw)
