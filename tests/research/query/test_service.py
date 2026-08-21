from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.research import (
    RESEARCH_QUERY_SCHEMA_VERSION,
    OnlyResearchQueryError,
    OnlyResearchQueryErrorCode,
    OnlyResearchQueryService,
    OnlyResearchScientificSeriesQuery,
    OnlyResearchStatisticSeriesQuery,
)
from tests.research.artifact.support import scientific_artifact_case
from tests.research.query.support import query_case


def test_summary_is_an_exact_immutable_artifact_projection(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    summary = service.get_artifact_summary(candidate.research_result_fingerprint)

    assert summary.schema_version == RESEARCH_QUERY_SCHEMA_VERSION
    assert summary.research_result_plan_fingerprint == artifact.manifest.research_result_plan_fingerprint
    assert summary.research_result_content_fingerprint == artifact.manifest.research_result_content_fingerprint
    assert summary.research_result_fingerprint == candidate.research_result_fingerprint
    assert summary.dataset_snapshot_fingerprint == artifact.manifest.dataset_snapshot_fingerprint
    assert summary.artifact_content_fingerprint == candidate.artifact_content_fingerprint
    assert summary.statistics_count == len(artifact.manifest.statistics_results)
    assert summary.row_count == len(artifact.rows)
    assert summary.created_at == artifact.manifest.created_at
    with pytest.raises(FrozenInstanceError):
        summary.row_count = 0  # type: ignore[misc]


def test_catalog_projects_exact_plans_in_canonical_order(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    catalog = service.list_statistics(candidate.research_result_fingerprint)

    assert catalog.schema_version == RESEARCH_QUERY_SCHEMA_VERSION
    assert tuple(item.statistics_fingerprint for item in catalog.statistics) == tuple(
        item.statistics_fingerprint for item in artifact.manifest.statistics_results
    )
    source = artifact.manifest.statistics_results[0]
    projected = catalog.statistics[0]
    assert projected.statistics_result_fingerprint == source.statistics_result_fingerprint
    assert projected.result_content_fingerprint == source.result_content_fingerprint
    assert projected.feature.calculation_fingerprint == source.plan.feature.calculation_fingerprint
    assert projected.feature.node_fingerprint == source.plan.feature.node_fingerprint
    assert projected.feature.output_name == source.plan.feature.output_name
    assert projected.target.calculation_fingerprint == source.plan.target.calculation_fingerprint
    assert projected.definition.method == source.plan.definition.method.value
    assert projected.definition.minimum_observations == source.plan.definition.minimum_observations
    assert projected.definition.pairing_policy == source.plan.definition.pairing_policy.value
    assert projected.definition.universe_policy == source.plan.definition.universe_policy.value
    assert projected.definition.rank_tie_method == source.plan.definition.rank_tie_method.value
    assert projected.definition.weighting == source.plan.definition.weighting.value
    assert projected.definition.numeric.representation == "DECIMAL"
    assert projected.definition.numeric.precision == 38
    assert projected.definition.numeric.output_quantum == Decimal("0.000000000001")
    assert projected.definition.numeric.rounding == "ROUND_HALF_EVEN"


def test_series_projects_rows_and_all_half_open_filters(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    source = tuple(row for row in artifact.rows if row.statistics_fingerprint == statistics)
    assert len(source) >= 3

    full = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(candidate.research_result_fingerprint, statistics)
    )
    assert tuple(point.ts_event_ns for point in full.points) == tuple(row.ts_event_ns for row in source)
    assert all(
        (point.statistic_value, point.sample_count, point.status)
        == (row.statistic_value, row.sample_count, row.status.value)
        for point, row in zip(full.points, source, strict=True)
    )
    middle = source[1].ts_event_ns
    end = source[-1].ts_event_ns
    from_only = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(candidate.research_result_fingerprint, statistics, from_ts_event_ns=middle)
    )
    to_only = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(candidate.research_result_fingerprint, statistics, to_ts_event_ns=end)
    )
    ranged = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(
            candidate.research_result_fingerprint,
            statistics,
            from_ts_event_ns=middle,
            to_ts_event_ns=end,
        )
    )
    empty = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(
            candidate.research_result_fingerprint,
            statistics,
            from_ts_event_ns=end + 1,
        )
    )
    assert tuple(point.ts_event_ns for point in from_only.points) == tuple(row.ts_event_ns for row in source[1:])
    assert tuple(point.ts_event_ns for point in to_only.points) == tuple(row.ts_event_ns for row in source[:-1])
    assert tuple(point.ts_event_ns for point in ranged.points) == tuple(row.ts_event_ns for row in source[1:-1])
    assert empty.points == ()


def test_cursor_pagination_is_complete_stable_and_terminal(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    expected = tuple(row.ts_event_ns for row in artifact.rows if row.statistics_fingerprint == statistics)
    collected: list[int] = []
    cursor = None
    while True:
        page = service.get_statistic_series(
            OnlyResearchStatisticSeriesQuery(
                candidate.research_result_fingerprint,
                statistics,
                after_ts_event_ns=cursor,
                limit=2,
            )
        )
        collected.extend(point.ts_event_ns for point in page.points)
        if not page.has_more:
            assert page.next_after_ts_event_ns is None
            break
        assert page.next_after_ts_event_ns == page.points[-1].ts_event_ns
        cursor = page.next_after_ts_event_ns
    assert tuple(collected) == expected
    assert len(collected) == len(set(collected))


def test_unknown_statistics_and_missing_artifact_have_distinct_errors(tmp_path) -> None:
    *_, candidate, _, service = query_case(tmp_path)
    with pytest.raises(OnlyResearchQueryError) as unknown:
        service.get_statistic_series(OnlyResearchStatisticSeriesQuery(candidate.research_result_fingerprint, "f" * 64))
    assert unknown.value.code is OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND
    with pytest.raises(OnlyResearchQueryError) as missing:
        service.get_artifact_summary("0" * 64)
    assert missing.value.code is OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_NOT_FOUND


def test_corrupt_artifact_fails_closed_instead_of_becoming_missing_or_empty(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    target = (
        tmp_path
        / "research-artifacts"
        / "research-statistics-v1"
        / "sha256"
        / candidate.research_result_fingerprint[:2]
        / candidate.research_result_fingerprint
        / "statistics.parquet"
    )
    target.write_bytes(b"corrupt")
    with pytest.raises(OnlyResearchQueryError) as caught:
        service.get_artifact_summary(candidate.research_result_fingerprint)
    assert caught.value.code is OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT


def test_query_is_portable_after_all_execution_roots_are_unavailable(tmp_path) -> None:
    *_, candidate, store, service = query_case(tmp_path)
    for name in ("datasets", "calculation-results", "statistics-results", "research-results"):
        path = tmp_path / name
        path.rename(tmp_path / f"unavailable-{name}")
    summary = service.get_artifact_summary(candidate.research_result_fingerprint)
    catalog = service.list_statistics(candidate.research_result_fingerprint)
    series = service.get_statistic_series(
        OnlyResearchStatisticSeriesQuery(
            candidate.research_result_fingerprint,
            catalog.statistics[0].statistics_fingerprint,
        )
    )
    assert summary.research_result_fingerprint == candidate.research_result_fingerprint
    assert catalog.statistics
    assert series.points
    assert store.load_verified(candidate.research_result_fingerprint).rows


def test_scientific_series_and_graph_enforce_exact_artifact_membership(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    service = OnlyResearchQueryService(store)
    identity = candidate.result.manifest.research_result_fingerprint
    artifact = store.load_verified(identity)
    instrument = artifact.market_rows[0].instrument_id
    published = artifact.manifest.plan.published_series[0]
    signal = artifact.manifest.plan.signals[0]

    variable = service.get_variable_series(
        OnlyResearchScientificSeriesQuery(
            identity,
            instrument_id=instrument,
            candidate_fingerprint=published.candidate_fingerprint,
            calculation_fingerprint=published.calculation_fingerprint,
            node_fingerprint=published.node_fingerprint,
            output_name=published.output_name,
        )
    )
    signals = service.get_signal_series(
        OnlyResearchScientificSeriesQuery(
            identity,
            instrument_id=instrument,
            candidate_fingerprint=signal.candidate_fingerprint,
            role=signal.role,
        )
    )
    graph = service.get_candidate_graph(identity, artifact.manifest.plan.candidates[0].candidate_fingerprint)
    assert variable.points
    assert signals.points
    assert graph.graph.fingerprint == artifact.manifest.plan.candidates[0].graph_fingerprint
    assert graph.graph_fingerprint == graph.graph.fingerprint

    invalid_queries = (
        (service.get_market_series, OnlyResearchScientificSeriesQuery(identity)),
        (service.get_variable_series, OnlyResearchScientificSeriesQuery(identity, instrument_id=instrument)),
        (
            service.get_variable_series,
            OnlyResearchScientificSeriesQuery(
                identity,
                instrument_id=instrument,
                candidate_fingerprint=published.candidate_fingerprint,
                calculation_fingerprint="f" * 64,
                node_fingerprint=published.node_fingerprint,
                output_name=published.output_name,
            ),
        ),
        (service.get_signal_series, OnlyResearchScientificSeriesQuery(identity, instrument_id=instrument)),
        (
            service.get_signal_series,
            OnlyResearchScientificSeriesQuery(
                identity,
                instrument_id=instrument,
                candidate_fingerprint=signal.candidate_fingerprint,
                role="UNKNOWN",
            ),
        ),
    )
    for method, query in invalid_queries:
        with pytest.raises(OnlyResearchQueryError):
            method(query)
    with pytest.raises(OnlyResearchQueryError) as missing:
        service.get_candidate_graph(identity, "f" * 64)
    assert missing.value.code is OnlyResearchQueryErrorCode.CANDIDATE_NOT_FOUND
    with pytest.raises(OnlyResearchQueryError):
        service.get_variable_series(object())  # type: ignore[arg-type]


def test_candidate_graph_linkage_mismatch_fails_as_corrupt_artifact(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    identity = candidate.result.manifest.research_result_fingerprint
    artifact = store.load_verified(identity)
    selected = artifact.manifest.plan.candidates[0]
    object.__setattr__(selected, "graph_fingerprint", "f" * 64)

    class Reader:
        def load_verified(self, research_result_fingerprint: str):  # type: ignore[no-untyped-def]
            assert research_result_fingerprint == identity
            return artifact

    with pytest.raises(OnlyResearchQueryError) as caught:
        OnlyResearchQueryService(Reader()).get_candidate_graph(identity, selected.candidate_fingerprint)
    assert caught.value.code is OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT
