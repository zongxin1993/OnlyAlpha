from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from onlyalpha_http_server import RESEARCH_API_SCHEMA_VERSION
from onlyalpha_http_server.research.schema import ResearchCandidateGraphDto, ResearchScientificSeriesPageDto
from pydantic import ValidationError

from onlyalpha.research import MAX_PAGE_SIZE, RESEARCH_QUERY_SCHEMA_VERSION
from onlyalpha.research.query import (
    OnlyResearchMarketPoint,
    OnlyResearchScientificSeriesPage,
    OnlyResearchSignalPoint,
    OnlyResearchVariablePoint,
)
from tests.research.artifact.support import scientific_artifact_case
from tests.research.query.support import query_case
from tests.support.research_artifact_http import create_test_artifact_query_app


def _client(tmp_path):  # type: ignore[no-untyped-def]
    *_, candidate, store, _ = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    return candidate, store, artifact, TestClient(create_test_artifact_query_app(store))


def test_scientific_series_transport_preserves_every_typed_point_and_cursor() -> None:
    model = OnlyResearchScientificSeriesPage(
        research_result_fingerprint="a" * 64,
        points=(
            OnlyResearchMarketPoint(
                "BTCUSDT.BINANCE",
                1,
                Decimal("1.0"),
                Decimal("2.0"),
                Decimal("0.5"),
                Decimal("1.5"),
                Decimal("10.0"),
            ),
            OnlyResearchVariablePoint("BTCUSDT.BINANCE", 2, "DECIMAL", "1.25", None, None, None),
            OnlyResearchSignalPoint("BTCUSDT.BINANCE", 3, True),
        ),
        has_more=True,
        next_after_ts_event_ns=3,
    )

    transported = ResearchScientificSeriesPageDto.from_model(model).model_dump()

    assert [item["ts_event_ns"] for item in transported["points"]] == ["1", "2", "3"]
    assert transported["points"][0]["close"] == "1.5"
    assert transported["points"][1]["decimal_value"] == "1.25"
    assert transported["points"][2]["value"] is True
    assert transported["next_after_ts_event_ns"] == "3"


def test_three_versioned_get_endpoints_return_exact_read_dtos(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    base = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}"

    summary = client.get(base)
    assert summary.status_code == 200
    assert summary.json() == {
        "schema_version": RESEARCH_API_SCHEMA_VERSION,
        "research_result_plan_fingerprint": artifact.manifest.research_result_plan_fingerprint,
        "research_result_content_fingerprint": artifact.manifest.research_result_content_fingerprint,
        "research_result_fingerprint": artifact.manifest.research_result_fingerprint,
        "dataset_snapshot_fingerprint": artifact.manifest.dataset_snapshot_fingerprint,
        "artifact_content_fingerprint": artifact.manifest.artifact_content_fingerprint,
        "research_result_schema_version": artifact.manifest.research_result_schema_version,
        "artifact_profile": artifact.manifest.profile,
        "artifact_schema_version": artifact.manifest.schema_version,
        "statistics_count": len(artifact.manifest.statistics_results),
        "row_count": len(artifact.rows),
        "candidate_count": 0,
        "published_series_count": 0,
        "signal_series_count": 0,
        "market_row_count": 0,
        "instrument_ids": [],
        "created_at": "2026-08-16T00:00:00Z",
    }

    catalog = client.get(f"{base}/statistics")
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["schema_version"] == RESEARCH_API_SCHEMA_VERSION
    assert body["research_result_fingerprint"] == candidate.research_result_fingerprint
    assert [item["statistics_fingerprint"] for item in body["statistics"]] == [
        item.statistics_fingerprint for item in artifact.manifest.statistics_results
    ]
    assert body["statistics"][0]["definition"]["numeric"]["output_quantum"] == "0.000000000001"

    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    series = client.get(f"{base}/statistics/{statistics}/series")
    assert series.status_code == 200
    points = series.json()["points"]
    source = tuple(row for row in artifact.rows if row.statistics_fingerprint == statistics)
    assert max(row.ts_event_ns for row in source) > 2**53
    assert [item["ts_event_ns"] for item in points] == [str(row.ts_event_ns) for row in source]
    assert [item["statistic_value"] for item in points] == [
        None if row.statistic_value is None else format(row.statistic_value, "f") for row in source
    ]
    assert all(item["statistic_value"] is None or isinstance(item["statistic_value"], str) for item in points)


def test_series_http_filter_and_pagination_contract(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    source = tuple(row for row in artifact.rows if row.statistics_fingerprint == statistics)
    url = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}/statistics/{statistics}/series"
    first = client.get(
        url,
        params={
            "from_ts_event_ns": str(source[1].ts_event_ns),
            "to_ts_event_ns": str(source[-1].ts_event_ns + 1),
            "limit": 2,
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["has_more"] is (len(source[1:]) > 2)
    if body["has_more"]:
        second = client.get(url, params={"after_ts_event_ns": body["next_after_ts_event_ns"], "limit": 2})
        assert second.status_code == 200
        assert body["next_after_ts_event_ns"] == body["points"][-1]["ts_event_ns"]
        assert set(item["ts_event_ns"] for item in body["points"]).isdisjoint(
            item["ts_event_ns"] for item in second.json()["points"]
        )


def test_http_errors_are_stable_and_keep_missing_corrupt_distinct(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    base = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}"
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    cases = (
        (
            client.get(f"{base}/statistics/{statistics}/series", params={"from_ts_event_ns": 2, "to_ts_event_ns": 1}),
            400,
            "INVALID_TIME_RANGE",
        ),
        (
            client.get(f"{base}/statistics/{statistics}/series", params={"limit": MAX_PAGE_SIZE + 1}),
            400,
            "INVALID_PAGE_LIMIT",
        ),
        (client.get(f"{base}/statistics/{statistics}/series", params={"limit": "bad"}), 400, "INVALID_QUERY"),
        (client.get(f"{base}/statistics/{'f' * 64}/series"), 404, "STATISTICS_NOT_FOUND"),
        (client.get(f"/api/v2/research/artifacts/{'0' * 64}"), 404, "RESEARCH_ARTIFACT_NOT_FOUND"),
    )
    for response, status, code in cases:
        assert response.status_code == status
        assert response.json()["schema_version"] == RESEARCH_API_SCHEMA_VERSION
        assert response.json()["code"] == code

    data = (
        tmp_path
        / "research-artifacts"
        / "research-statistics-v1"
        / "sha256"
        / candidate.research_result_fingerprint[:2]
        / candidate.research_result_fingerprint
        / "statistics.parquet"
    )
    data.write_bytes(b"corrupt")
    corrupt = client.get(base)
    assert corrupt.status_code == 500
    assert corrupt.json() == {
        "schema_version": RESEARCH_API_SCHEMA_VERSION,
        "code": "RESEARCH_ARTIFACT_CORRUPT",
        "detail": "Research Artifact verification failed",
    }


def test_product_api_is_get_only_and_openapi_is_versioned(tmp_path) -> None:
    candidate, _, _, client = _client(tmp_path)
    base = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}"
    for method in (client.post, client.put, client.patch, client.delete):
        assert method(base).status_code == 405
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v2/research/artifacts/{research_result_fingerprint}" in paths
    assert "/api/v2/research/artifacts/{research_result_fingerprint}/statistics" in paths
    assert (
        "/api/v2/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series"
    ) in paths
    assert not any(path.startswith("/api/v1") for path in paths)
    assert all(set(operations) == {"get"} for path, operations in paths.items() if path.startswith("/api/v2"))

    series = paths[
        "/api/v2/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series"
    ]["get"]
    parameters = {item["name"]: item["schema"] for item in series["parameters"]}
    for name in ("from_ts_event_ns", "to_ts_event_ns", "after_ts_event_ns"):
        assert parameters[name]["anyOf"][0]["type"] == "string"
    schemas = schema["components"]["schemas"]
    assert schemas["ResearchStatisticPointDto"]["properties"]["ts_event_ns"]["type"] == "string"
    cursor = schemas["ResearchStatisticSeriesPageDto"]["properties"]["next_after_ts_event_ns"]
    assert cursor["anyOf"] == [{"type": "string"}, {"type": "null"}]
    for path in (
        "/api/v2/research/artifacts/{research_result_fingerprint}/candidates",
        "/api/v2/research/artifacts/{research_result_fingerprint}/variables",
        "/api/v2/research/artifacts/{research_result_fingerprint}/market/series",
        "/api/v2/research/artifacts/{research_result_fingerprint}/candidates/{candidate_fingerprint}/graph",
    ):
        assert path in paths


def test_v1_scientific_query_fails_with_stable_explicit_error(tmp_path) -> None:
    candidate, _, _, client = _client(tmp_path)
    response = client.get(f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}/candidates")
    assert response.status_code == 409
    assert response.json()["code"] == "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE"


def test_candidate_graph_is_an_exact_strict_nested_read_projection(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    identity = candidate.result.manifest.research_result_fingerprint
    artifact = store.load_verified(identity)
    selected = artifact.manifest.plan.candidates[0]
    client = TestClient(create_test_artifact_query_app(store))
    base = f"/api/v2/research/artifacts/{identity}"
    url = f"/api/v2/research/artifacts/{identity}/candidates/{selected.candidate_fingerprint}/graph"

    summary = client.get(base).json()
    assert summary["candidate_count"] == len(artifact.manifest.plan.candidates)
    assert summary["published_series_count"] == len(artifact.manifest.plan.published_series)
    assert summary["signal_series_count"] == len(artifact.manifest.plan.signals)
    assert summary["market_row_count"] == len(artifact.market_rows)
    assert summary["instrument_ids"] == sorted({row.instrument_id for row in artifact.market_rows})
    catalog = client.get(f"{base}/candidates").json()
    candidate_body = next(
        item for item in catalog["candidates"] if item["candidate_fingerprint"] == selected.candidate_fingerprint
    )
    assert candidate_body["assignment_types"] == {
        name: (
            "NULL"
            if value is None
            else "BOOLEAN"
            if isinstance(value, bool)
            else "INTEGER"
            if isinstance(value, int)
            else "DECIMAL"
            if isinstance(value, Decimal)
            else "STRING"
        )
        for name, value in selected.assignment
    }
    assert candidate_body["signal_roles"] == sorted(
        signal.role
        for signal in artifact.manifest.plan.signals
        if signal.candidate_fingerprint == selected.candidate_fingerprint
    )

    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    exact_graph = next(
        item.graph for item in artifact.graphs if item.calculation_fingerprint == selected.calculation_fingerprint
    )
    assert body["graph_fingerprint"] == selected.graph_fingerprint == exact_graph.fingerprint
    assert [item["node_fingerprint"] for item in body["graph"]["nodes"]] == [
        item.fingerprint for item in exact_graph.ordered_nodes
    ]
    definitions = [item["definition"] for item in body["graph"]["nodes"]]
    assert any(item["kind"] == "PREDICATE" for item in definitions)
    assert any(reference["source"] is not None for item in definitions for reference in item["input_bindings"].values())
    scalar_types = {scalar["type"] for item in definitions for scalar in item["parameters"].values()}
    assert {"DECIMAL", "INTEGER"} <= scalar_types
    assert all(
        isinstance(scalar["value"], str)
        for item in definitions
        for scalar in item["parameters"].values()
        if scalar["type"] in {"DECIMAL", "INTEGER"}
    )
    assert any(output["nullable"] for item in definitions for output in item["outputs"])
    graph_schema = client.app.openapi()["components"]["schemas"]["ResearchCalculationGraphDto"]
    assert graph_schema["additionalProperties"] is False
    assert set(graph_schema["required"]) == {"schema_version", "nodes"}

    malformed = deepcopy(body)
    malformed["unexpected"] = True
    with pytest.raises(ValidationError):
        ResearchCandidateGraphDto.model_validate(malformed)
    malformed = deepcopy(body)
    malformed["graph"]["schema_version"] = 2
    with pytest.raises(ValidationError):
        ResearchCandidateGraphDto.model_validate(malformed)
    malformed = deepcopy(body)
    malformed["graph"]["nodes"][0]["node_fingerprint"] = "BAD"
    with pytest.raises(ValidationError):
        ResearchCandidateGraphDto.model_validate(malformed)
    malformed = deepcopy(body)
    malformed["graph"]["nodes"][0]["definition"]["parameters"] = {"period": {"type": "INTEGER", "value": 14}}
    with pytest.raises(ValidationError):
        ResearchCandidateGraphDto.model_validate(malformed)
    malformed = deepcopy(body)
    malformed["graph"]["nodes"][0]["definition"]["input_bindings"]["price"] = {
        "node_fingerprint": "f" * 64,
        "output_name": "close",
        "source": None,
    }
    with pytest.raises(ValidationError):
        ResearchCandidateGraphDto.model_validate(malformed)


def test_http_end_to_end_needs_only_the_portable_artifact(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    for name in ("datasets", "calculation-results", "statistics-results", "research-results"):
        (tmp_path / name).rename(tmp_path / f"unavailable-{name}")
    base = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}"
    summary = client.get(base)
    catalog = client.get(f"{base}/statistics")
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    series = client.get(f"{base}/statistics/{statistics}/series", params={"limit": 2})
    assert summary.status_code == catalog.status_code == series.status_code == 200
    assert summary.json()["research_result_fingerprint"] == candidate.research_result_fingerprint
    assert catalog.json()["statistics"]
    assert series.json()["points"]


def test_nanosecond_transport_round_trips_beyond_javascript_safe_integer(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    exact = 1_780_000_000_000_000_123
    url = f"/api/v2/research/artifacts/{candidate.research_result_fingerprint}/statistics/{statistics}/series"
    response = client.get(url, params={"from_ts_event_ns": str(exact), "to_ts_event_ns": str(exact + 1)})
    assert response.status_code == 200
    assert response.request.url.params["from_ts_event_ns"] == "1780000000000000123"

    invalid = client.get(url, params={"from_ts_event_ns": "01780000000000000123"})
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "INVALID_QUERY"
    assert RESEARCH_QUERY_SCHEMA_VERSION == 1
    assert RESEARCH_API_SCHEMA_VERSION == 2
