from scripts.openapi_contract import render_document


def test_canonical_product_openapi_contains_deterministic_read_only_integration_routes() -> None:
    first = render_document()
    second = render_document()

    assert first == second
    assert set(first["paths"]["/api/v2/integration-types"]) == {"get"}
    assert set(first["paths"]["/api/v2/integration-types/{type_id}"]) == {"get"}
    for path in ("/api/v2/integration-types", "/api/v2/integration-types/{type_id}"):
        assert "422" not in first["paths"][path]["get"]["responses"]
