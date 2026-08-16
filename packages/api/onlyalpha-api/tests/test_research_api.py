from __future__ import annotations

from fastapi.testclient import TestClient
from onlyalpha_api import create_app

from onlyalpha.research import MAX_PAGE_SIZE
from tests.research.query.support import query_case


def _client(tmp_path):  # type: ignore[no-untyped-def]
    *_, candidate, store, _ = query_case(tmp_path)
    artifact = store.load_verified(candidate.research_result_fingerprint)
    return candidate, store, artifact, TestClient(create_app(store))


def test_three_versioned_get_endpoints_return_exact_read_dtos(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    base = f"/api/v1/research/artifacts/{candidate.research_result_fingerprint}"

    summary = client.get(base)
    assert summary.status_code == 200
    assert summary.json() == {
        "schema_version": 1,
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
        "created_at": "2026-08-16T00:00:00Z",
    }

    catalog = client.get(f"{base}/statistics")
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["schema_version"] == 1
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
    assert [item["ts_event_ns"] for item in points] == [row.ts_event_ns for row in source]
    assert [item["statistic_value"] for item in points] == [
        None if row.statistic_value is None else format(row.statistic_value, "f") for row in source
    ]
    assert all(item["statistic_value"] is None or isinstance(item["statistic_value"], str) for item in points)


def test_series_http_filter_and_pagination_contract(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    source = tuple(row for row in artifact.rows if row.statistics_fingerprint == statistics)
    url = f"/api/v1/research/artifacts/{candidate.research_result_fingerprint}/statistics/{statistics}/series"
    first = client.get(
        url,
        params={
            "from_ts_event_ns": source[1].ts_event_ns,
            "to_ts_event_ns": source[-1].ts_event_ns + 1,
            "limit": 2,
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["has_more"] is (len(source[1:]) > 2)
    if body["has_more"]:
        second = client.get(url, params={"after_ts_event_ns": body["next_after_ts_event_ns"], "limit": 2})
        assert second.status_code == 200
        assert set(item["ts_event_ns"] for item in body["points"]).isdisjoint(
            item["ts_event_ns"] for item in second.json()["points"]
        )


def test_http_errors_are_stable_and_keep_missing_corrupt_distinct(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    base = f"/api/v1/research/artifacts/{candidate.research_result_fingerprint}"
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
        (client.get(f"/api/v1/research/artifacts/{'0' * 64}"), 404, "RESEARCH_ARTIFACT_NOT_FOUND"),
    )
    for response, status, code in cases:
        assert response.status_code == status
        assert response.json()["schema_version"] == 1
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
        "schema_version": 1,
        "code": "RESEARCH_ARTIFACT_CORRUPT",
        "detail": "Research Artifact verification failed",
    }


def test_product_api_is_get_only_and_openapi_is_versioned(tmp_path) -> None:
    candidate, _, _, client = _client(tmp_path)
    base = f"/api/v1/research/artifacts/{candidate.research_result_fingerprint}"
    for method in (client.post, client.put, client.patch, client.delete):
        assert method(base).status_code == 405
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/research/artifacts/{research_result_fingerprint}" in paths
    assert "/api/v1/research/artifacts/{research_result_fingerprint}/statistics" in paths
    assert (
        "/api/v1/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series"
    ) in paths
    assert all(set(operations) == {"get"} for path, operations in paths.items() if path.startswith("/api/v1"))


def test_http_end_to_end_needs_only_the_portable_artifact(tmp_path) -> None:
    candidate, _, artifact, client = _client(tmp_path)
    for name in ("datasets", "calculation-results", "statistics-results", "research-results"):
        (tmp_path / name).rename(tmp_path / f"unavailable-{name}")
    base = f"/api/v1/research/artifacts/{candidate.research_result_fingerprint}"
    summary = client.get(base)
    catalog = client.get(f"{base}/statistics")
    statistics = artifact.manifest.statistics_results[0].statistics_fingerprint
    series = client.get(f"{base}/statistics/{statistics}/series", params={"limit": 2})
    assert summary.status_code == catalog.status_code == series.status_code == 200
    assert summary.json()["research_result_fingerprint"] == candidate.research_result_fingerprint
    assert catalog.json()["statistics"]
    assert series.json()["points"]
