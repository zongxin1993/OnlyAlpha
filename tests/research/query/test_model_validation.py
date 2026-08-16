from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from onlyalpha.research import (
    OnlyResearchNumericDescriptor,
    OnlyResearchQueryError,
    OnlyResearchQueryErrorCode,
    OnlyResearchSeriesReference,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticSeriesQuery,
)
from onlyalpha.research.query.service import _descriptor
from tests.research.query.support import query_case


def test_query_error_contract_rejects_invalid_code_and_empty_detail() -> None:
    with pytest.raises(ValueError):
        OnlyResearchQueryError("INVALID_QUERY", "detail")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchQueryError(OnlyResearchQueryErrorCode.INVALID_QUERY, "")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 2),
        ("research_result_schema_version", 0),
        ("research_result_schema_version", True),
        ("research_result_schema_version", "1"),
        ("artifact_schema_version", 0),
        ("artifact_profile", ""),
        ("statistics_count", -1),
        ("statistics_count", True),
        ("statistics_count", "1"),
        ("row_count", -1),
        ("created_at", datetime(2026, 1, 1)),
        ("created_at", "2026-01-01T00:00:00Z"),
    ),
)
def test_summary_constructor_is_strict(tmp_path, field: str, value: object) -> None:
    *_, candidate, _, service = query_case(tmp_path)
    summary = service.get_artifact_summary(candidate.research_result_fingerprint)
    with pytest.raises((OnlyResearchQueryError, TypeError, ValueError)):
        replace(summary, **{field: value})


@pytest.mark.parametrize("output_name", ("", "has space"))
def test_series_reference_rejects_invalid_output_name(output_name: str) -> None:
    with pytest.raises(ValueError):
        OnlyResearchSeriesReference("a" * 64, "b" * 64, output_name)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("representation", ""),
        ("rounding", ""),
        ("precision", 0),
        ("precision", True),
        ("precision", "38"),
        ("output_quantum", "0.1"),
        ("output_quantum", Decimal("Infinity")),
    ),
)
def test_numeric_descriptor_is_strict(field: str, value: object) -> None:
    numeric = OnlyResearchNumericDescriptor("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
    with pytest.raises(ValueError):
        replace(numeric, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("method", ""),
        ("minimum_observations", 1),
        ("minimum_observations", True),
        ("minimum_observations", "2"),
        ("numeric", None),
    ),
)
def test_statistics_definition_descriptor_is_strict(field: str, value: object) -> None:
    numeric = OnlyResearchNumericDescriptor("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
    definition = OnlyResearchStatisticsDefinitionDescriptor(
        "IC", 2, "PAIRWISE_COMPLETE", "OBSERVED_PAIRWISE", "AVERAGE", "EQUAL", numeric
    )
    with pytest.raises(ValueError):
        replace(definition, **{field: value})


def test_descriptor_catalog_point_and_page_are_strict(tmp_path) -> None:
    *_, candidate, _, service = query_case(tmp_path)
    catalog = service.list_statistics(candidate.research_result_fingerprint)
    first, second = catalog.statistics
    with pytest.raises(ValueError):
        replace(first, statistics_result_schema_version=0)
    with pytest.raises(ValueError):
        replace(first, row_count=-1)
    with pytest.raises(ValueError):
        replace(first, row_count=True)
    with pytest.raises(ValueError):
        replace(catalog, schema_version=2)
    with pytest.raises(ValueError):
        replace(catalog, statistics=[first, second])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(catalog, statistics=(second, first))
    with pytest.raises(ValueError):
        replace(catalog, statistics=(first, first))

    valid = OnlyResearchStatisticPoint(1, Decimal("0.1"), 2, "VALID")
    invalid_points = (
        {"ts_event_ns": True},
        {"ts_event_ns": "1"},
        {"statistic_value": "0.1"},
        {"statistic_value": Decimal("NaN")},
        {"sample_count": -1},
        {"sample_count": True},
        {"sample_count": "2"},
        {"status": ""},
    )
    for fields in invalid_points:
        with pytest.raises(ValueError):
            replace(valid, **fields)

    statistics = first.statistics_fingerprint
    page = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(candidate.research_result_fingerprint, statistics, limit=2)
    )
    with pytest.raises(ValueError):
        replace(page, schema_version=2)
    with pytest.raises(ValueError):
        replace(page, points=list(page.points))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(page, points=(page.points[1], page.points[0]))
    with pytest.raises(ValueError):
        replace(page, points=(page.points[0], page.points[0]))
    with pytest.raises(ValueError):
        replace(page, has_more=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(page, next_after_ts_event_ns=None if page.has_more else page.points[-1].ts_event_ns)


def test_service_defensive_contract_rejects_wrong_request_and_missing_numeric_quantum(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    with pytest.raises(OnlyResearchQueryError) as caught:
        service.get_statistic_series(object())  # type: ignore[arg-type]
    assert caught.value.code is OnlyResearchQueryErrorCode.INVALID_QUERY

    entry = store.load_verified(candidate.research_result_fingerprint).manifest.statistics_results[0]
    numeric_without_quantum = replace(entry.plan.definition.numeric, output_quantum=None)
    object.__setattr__(entry.plan.definition, "numeric", numeric_without_quantum)
    with pytest.raises(ValueError, match="output quantum"):
        _descriptor(entry)
