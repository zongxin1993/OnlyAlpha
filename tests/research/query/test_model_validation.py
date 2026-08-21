from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from onlyalpha.research import (
    RESEARCH_QUERY_SCHEMA_VERSION,
    OnlyResearchCandidateCatalog,
    OnlyResearchCandidateGraph,
    OnlyResearchMarketPoint,
    OnlyResearchNumericDescriptor,
    OnlyResearchPublishedSeriesCatalog,
    OnlyResearchQueryError,
    OnlyResearchQueryErrorCode,
    OnlyResearchScientificSeriesPage,
    OnlyResearchScientificSeriesQuery,
    OnlyResearchSeriesReference,
    OnlyResearchSignalPoint,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticSeriesQuery,
    OnlyResearchVariablePoint,
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
        ("candidate_count", -1),
        ("published_series_count", True),
        ("signal_series_count", "1"),
        ("market_row_count", -1),
        ("instrument_ids", ("B", "A")),
        ("instrument_ids", ("A", "A")),
        ("instrument_ids", ("",)),
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


def test_scientific_catalogs_and_pages_are_strict(tmp_path) -> None:
    from onlyalpha.research import OnlyResearchQueryService
    from tests.research.artifact.support import scientific_artifact_case

    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    service = OnlyResearchQueryService(store)
    identity = candidate.result.manifest.research_result_fingerprint
    candidates = service.list_candidates(identity)
    series = service.list_published_series(identity)
    summary = service.get_artifact_summary(identity)
    instrument = store.load_verified(identity).market_rows[0].instrument_id
    page = service.get_market_series(OnlyResearchScientificSeriesQuery(identity, instrument_id=instrument, limit=2))

    assert isinstance(candidates, OnlyResearchCandidateCatalog)
    assert isinstance(series, OnlyResearchPublishedSeriesCatalog)
    assert summary.instrument_ids == tuple(
        sorted({row.instrument_id for row in store.load_verified(identity).market_rows})
    )
    assert candidates.candidates[0].signal_roles == tuple(sorted(candidates.candidates[0].signal_roles))
    assert dict(candidates.candidates[0].assignment_types) == {
        name: (
            "BOOLEAN"
            if isinstance(value, bool)
            else "INTEGER"
            if isinstance(value, int)
            else "DECIMAL"
            if isinstance(value, Decimal)
            else "NULL"
            if value is None
            else "STRING"
        )
        for name, value in candidates.candidates[0].assignment
    }
    with pytest.raises((ValueError, OnlyResearchQueryError)):
        replace(candidates, research_result_fingerprint="bad")
    with pytest.raises(ValueError):
        replace(candidates, candidates=(candidates.candidates[0], candidates.candidates[0]))
    with pytest.raises(ValueError):
        replace(candidates.candidates[0], signal_roles=("ENTRY_SIGNAL", "ENTRY_SIGNAL"))
    with pytest.raises(ValueError):
        replace(candidates.candidates[0], signal_roles=("ENTRY_GUESSED",))
    with pytest.raises(ValueError):
        replace(series, series=tuple(reversed(series.series)))
    with pytest.raises(ValueError):
        replace(page, points=(page.points[0], page.points[0]))
    with pytest.raises(ValueError):
        replace(page, has_more=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(page, next_after_ts_event_ns=None if page.has_more else page.points[-1].ts_event_ns)


def test_scientific_read_models_reject_noncanonical_or_mistyped_values(tmp_path) -> None:
    from onlyalpha.research import OnlyResearchQueryService
    from tests.research.artifact.support import scientific_artifact_case

    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    service = OnlyResearchQueryService(store)
    identity = candidate.result.manifest.research_result_fingerprint
    artifact = store.load_verified(identity)
    descriptor = service.list_candidates(identity).candidates[0]
    published = service.list_published_series(identity)
    series = published.series[0]
    instrument = artifact.market_rows[0].instrument_id
    market_page = service.get_market_series(OnlyResearchScientificSeriesQuery(identity, instrument_id=instrument))
    graph = service.get_candidate_graph(identity, descriptor.candidate_fingerprint)

    invalid_candidates = (
        {"candidate_calculation_id": ""},
        {"assignment": [("x", 1)]},
        {"assignment_types": (("unknown", "INTEGER"),)},
        {"assignment_types": tuple((name, "STRING") for name, _ in descriptor.assignment)},
        {"statistics_fingerprints": ("a" * 64, "a" * 64)},
    )
    for fields in invalid_candidates:
        with pytest.raises(ValueError):
            replace(descriptor, **fields)
    with pytest.raises(ValueError):
        replace(service.list_candidates(identity), schema_version=RESEARCH_QUERY_SCHEMA_VERSION + 1)

    with pytest.raises(ValueError):
        replace(series, output_name="has space")
    with pytest.raises(ValueError):
        replace(series, value_kind="FLOAT")
    with pytest.raises(ValueError):
        replace(published, schema_version=RESEARCH_QUERY_SCHEMA_VERSION + 1)
    with pytest.raises(ValueError):
        replace(published, series=[series])  # type: ignore[arg-type]

    market = market_page.points[0]
    assert isinstance(market, OnlyResearchMarketPoint)
    with pytest.raises(ValueError):
        replace(market, close=Decimal("NaN"))
    with pytest.raises(ValueError):
        OnlyResearchVariablePoint("", 1, "DECIMAL", "1", None, None, None)
    with pytest.raises(ValueError):
        OnlyResearchVariablePoint(instrument, 1, "FLOAT", None, None, None, None)
    with pytest.raises(ValueError):
        OnlyResearchSignalPoint(instrument, True, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchSignalPoint(instrument, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(market_page, schema_version=RESEARCH_QUERY_SCHEMA_VERSION + 1)
    with pytest.raises(ValueError):
        OnlyResearchScientificSeriesPage(identity, (object(),), False, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(graph, schema_version=RESEARCH_QUERY_SCHEMA_VERSION + 1)
    with pytest.raises(ValueError):
        OnlyResearchCandidateGraph(identity, descriptor.candidate_fingerprint, "a" * 64, "b" * 64, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Graph identity"):
        replace(graph, graph_fingerprint="f" * 64)


def test_scientific_series_query_rejects_invalid_identity_range_and_limit() -> None:
    identity = "a" * 64
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchScientificSeriesQuery(identity, candidate_fingerprint="bad")
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchScientificSeriesQuery(identity, from_ts_event_ns=2, to_ts_event_ns=2)
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchScientificSeriesQuery(identity, limit=True)  # type: ignore[arg-type]
