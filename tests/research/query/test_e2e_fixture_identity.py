from __future__ import annotations

from fastapi.testclient import TestClient

from tests.support.research_artifact_http import create_test_artifact_query_app


def test_test_server_fixture_identity_is_explicit_and_excluded_from_openapi() -> None:
    identity = {
        "research_result_fingerprint": "a" * 64,
        "statistics_fingerprint": "b" * 64,
    }
    app = create_test_artifact_query_app(object(), fixture_identity=identity)  # type: ignore[arg-type]
    client = TestClient(app)

    assert client.get("/__onlyalpha_e2e__/fixture").json() == identity
    assert "/__onlyalpha_e2e__/fixture" not in client.get("/openapi.json").json()["paths"]
