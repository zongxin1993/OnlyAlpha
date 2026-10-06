from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.application.catalog_context import only_project_exact_catalog_readiness
from onlyalpha.application.chart_calculation import (
    OnlyChartCalculationCatalogWitnessV1,
    OnlyChartCalculationRequestV1,
    only_normalize_chart_calculation,
)
from onlyalpha.domain.market import OnlyBarSemantic
from tests.application.test_exact_catalog_context import _context, _generation, _readiness_rows

NOW = datetime(2026, 10, 6, tzinfo=UTC)
COMMAND = "00000000-0000-4000-8000-000000000701"
D = 900_000_000_000


def request(parameters: object = None) -> OnlyChartCalculationRequestV1:
    return OnlyChartCalculationRequestV1.from_dict(payload(parameters))


def payload(parameters: object = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_reference": {
            "integration_id": "00000000-0000-4000-8000-000000000702",
            "integration_revision_fingerprint": "a" * 64,
            "expected_type_id": "onlyalpha.data_source.binance",
        },
        "instrument_id": "BTCUSDT.BINANCE",
        "bar_semantic": OnlyBarSemantic.fixed_duration(15).to_dict(),
        "display_range": {"start_ns": str(D * 20000), "end_ns": str(D * 20010)},
        "calculation": {
            "kind": "INDICATOR",
            "type_id": "onlyalpha.indicator.sma",
            "semantic_version": "1",
            "parameters": {} if parameters is None else parameters,
            "output_name": "value",
        },
    }


def witness() -> OnlyChartCalculationCatalogWitnessV1:
    context = _context(_generation())
    readiness = only_project_exact_catalog_readiness(context, _readiness_rows(context))
    return OnlyChartCalculationCatalogWitnessV1.from_projections(context, readiness)


def test_normalization_uses_exact_descriptor_and_explicit_defaults_are_equivalent() -> None:
    frozen = witness()
    omitted = only_normalize_chart_calculation(request(), frozen, NOW)
    explicit = only_normalize_chart_calculation(request({"period": 20, "price_field": "close"}), frozen, NOW)
    assert omitted == explicit
    assert omitted.to_dict()["calculation"]["parameters"] == {"period": 20, "price_field": "CLOSE"}
    assert frozen == OnlyChartCalculationCatalogWitnessV1.from_dict(frozen.to_dict())


@pytest.mark.parametrize(
    "parameters",
    [
        [],
        {"period": True},
        {"period": 1.5},
        {"period": "20"},
        {"price_field": 3},
        {"price_field": "OPEN"},
        {"extra": 1},
        {"period": 0},
        {"period": 673},
    ],
)
def test_invalid_parameters_reject(parameters: object) -> None:
    with pytest.raises(ValueError):
        only_normalize_chart_calculation(request(parameters), witness(), NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("extra", 1),
        ("instrument_id", "BTCUSDT"),
        ("bar_semantic", OnlyBarSemantic.fixed_duration(7).to_dict()),
        ("display_range", {"start_ns": "01", "end_ns": "2"}),
    ],
)
def test_strict_request_rejects_unsupported_shape(field: str, value: object) -> None:
    changed = payload()
    changed[field] = value
    with pytest.raises(ValueError):
        OnlyChartCalculationRequestV1.from_dict(changed)


def test_closed_range_is_checked_against_explicit_server_time() -> None:
    with pytest.raises(ValueError, match="CHART_RANGE_NOT_CLOSED"):
        only_normalize_chart_calculation(request(), witness(), datetime(1970, 1, 1, tzinfo=UTC))


def test_witness_rejects_wrong_projection_relation_and_unsupported_readiness() -> None:
    context = _context(_generation())
    rows = _readiness_rows(context)
    projection = only_project_exact_catalog_readiness(context, rows)
    with pytest.raises(ValueError):
        OnlyChartCalculationCatalogWitnessV1.from_projections(
            context, replace(projection, exact_catalog_context_projection_fingerprint="f" * 64)
        )
    unsupported = tuple(replace(row, readiness_contract_versions=()) for row in rows)
    with pytest.raises(ValueError):
        OnlyChartCalculationCatalogWitnessV1.from_projections(
            context, only_project_exact_catalog_readiness(context, unsupported)
        )


@pytest.mark.parametrize("section", ["schema_version", "context", "readiness", "readiness_contract_version"])
def test_witness_missing_mandatory_proof_fails_closed(section: str) -> None:
    changed = witness().to_dict()
    changed.pop(section)
    with pytest.raises(ValueError):
        OnlyChartCalculationCatalogWitnessV1.from_dict(changed)


def test_persisted_contract_defaults_are_not_replaced_by_current_defaults() -> None:
    from onlyalpha.application.catalog_context import OnlyExactCatalogCalculationCapabilityV1

    frozen = witness()
    encoded = frozen.to_dict()
    context_payload = encoded["context"]
    capabilities = context_payload["ordered_calculation_capabilities"]
    changed_rows = []
    for raw in capabilities:
        if raw["type_id"] == "onlyalpha.indicator.sma" and raw["backend"] == "RESEARCH":
            for parameter in raw["type_descriptor"]["parameters"]:
                if parameter["name"] == "period":
                    parameter["default"] = 21
        changed_rows.append(OnlyExactCatalogCalculationCapabilityV1.from_dict(raw))
    original = _context(_generation())
    changed = replace(original, ordered_calculation_capabilities=tuple(changed_rows))
    different = OnlyChartCalculationCatalogWitnessV1.from_projections(
        changed, only_project_exact_catalog_readiness(changed, _readiness_rows(changed))
    )
    assert only_normalize_chart_calculation(request(), frozen, NOW) != only_normalize_chart_calculation(
        request(), different, NOW
    )
    assert only_normalize_chart_calculation(request(), frozen, NOW) == only_normalize_chart_calculation(
        request({"period": 20}), frozen, NOW
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("kind", "FACTOR"),
        ("semantic_version", "2"),
        ("type_id", "onlyalpha.indicator.ema"),
        ("output_name", "other"),
        ("backend", "TRADING"),
    ],
)
def test_unsupported_calculation_selection_rejects(key: str, value: str) -> None:
    changed = payload()
    changed["calculation"][key] = value
    with pytest.raises(ValueError):
        OnlyChartCalculationRequestV1.from_dict(changed)


def test_intent_identity_excludes_catalog_projection_and_audit_time() -> None:
    first = only_normalize_chart_calculation(request(), witness(), NOW)
    second = only_normalize_chart_calculation(request(), witness(), NOW.replace(year=2027))
    assert first.intent_fingerprint == second.intent_fingerprint
    value = first.to_dict()
    assert set(value) == {
        "schema_version",
        "source_reference",
        "instrument_id",
        "bar_semantic",
        "display_range",
        "calculation",
    }
    changed = payload({"period": 21})
    assert (
        only_normalize_chart_calculation(
            OnlyChartCalculationRequestV1.from_dict(changed), witness(), NOW
        ).intent_fingerprint
        != first.intent_fingerprint
    )
