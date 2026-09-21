from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_integration_openapi_surface_is_exact_and_secret_safe() -> None:
    document = json.loads((ROOT / "contracts/product-api/v2/openapi.json").read_text(encoding="utf-8"))
    paths = {
        path: set(item) & {"get", "post", "put", "delete"}
        for path, item in document["paths"].items()
        if path.startswith("/api/v2/integrations")
    }

    assert paths == {
        "/api/v2/integrations": {"get", "post"},
        "/api/v2/integrations/{integration_id}": {"get"},
        "/api/v2/integrations/{integration_id}/draft": {"get", "put"},
        "/api/v2/integrations/{integration_id}/draft/contract-reset": {"post"},
        "/api/v2/integrations/{integration_id}/draft/secrets/{field_id}": {"delete", "put"},
        "/api/v2/integrations/{integration_id}/lifecycle": {"put"},
        "/api/v2/integrations/{integration_id}/operational-status": {"get"},
        "/api/v2/integrations/{integration_id}/probe": {"post"},
        "/api/v2/integrations/{integration_id}/probe-attempts": {"get"},
        "/api/v2/integrations/{integration_id}/probe-attempts/{probe_attempt_id}": {"get"},
        "/api/v2/integrations/{integration_id}/revisions": {"get", "post"},
        "/api/v2/integrations/{integration_id}/revisions/{revision_fingerprint}": {"get"},
    }
    for path, methods in paths.items():
        for method in methods:
            operation = document["paths"][path][method]
            assert "422" not in operation["responses"]
            assert {"400", "404", "409", "500", "503"} <= set(operation["responses"])
            if method in {"post", "put", "delete"} and not path.endswith("/probe"):
                headers = {
                    parameter["name"]: parameter
                    for parameter in operation.get("parameters", [])
                    if parameter["in"] == "header"
                }
                assert headers["Idempotency-Key"]["required"] is True

    probe_parameters = document["paths"]["/api/v2/integrations/{integration_id}/probe"]["post"].get("parameters", [])
    assert "Idempotency-Key" not in {parameter["name"] for parameter in probe_parameters}

    secret = document["components"]["schemas"]["IntegrationSecretSetRequestDto"]["properties"]["secret"]
    assert secret == {
        "format": "password",
        "title": "Secret",
        "type": "string",
        "writeOnly": True,
    }
