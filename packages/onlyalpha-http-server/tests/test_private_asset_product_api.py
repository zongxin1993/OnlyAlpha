from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.private_assets import (
    create_private_asset_router,
    install_private_asset_error_handlers,
)

from onlyalpha.application.private_asset_product import (
    OnlyPrivateAssetProductService,
    OnlyProductAssetSearchProjectionCorrupt,
    OnlyProductAssetSearchProjectionService,
    OnlyProductAssetSearchProjectionUnavailable,
)
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
)
from onlyalpha.quant_assets.private_factor_execution import ONLY_PRIVATE_FACTOR_API_V1


def _factor(description: str = "Momentum") -> OnlyPrivateFactorRevision:
    return OnlyPrivateFactorRevision.from_draft(
        OnlyPrivateFactorDraft(
            factor_id="private.factor.momentum",
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs['close']\n",
            factor_api_version=1,
            factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            input_contract={"close": "DECIMAL"},
            parameter_contract={},
            output_contract={"score": "DECIMAL"},
            description=description,
            economic_rationale="Price persistence",
            category="MOMENTUM",
            tags=("momentum", "price"),
        )
    )


def _strategy() -> OnlyPrivateStrategyRevision:
    positive_close = {
        "kind": "COMPARISON",
        "operator": ">",
        "left": {"kind": "DATASET_FIELD", "field_name": "close"},
        "right": {"kind": "LITERAL", "data_type": "DECIMAL", "value": {"type": "DECIMAL", "value": "0"}},
    }
    return OnlyPrivateStrategyRevision.from_draft(
        OnlyPrivateStrategyDraft(
            strategy_id="private.strategy.momentum",
            semantic_version="1",
            definition={
                "schema_version": 1,
                "universe": {"kind": "SINGLE_INSTRUMENT", "instruments": ["TEST.XSHG"]},
                "market_input": {
                    "schema_version": 1,
                    "data_kind": "BAR",
                    "bar_specification": {"step": 1, "aggregation": "TIME", "price_type": "LAST"},
                    "aggregation_source": "EXTERNAL",
                    "adjustment_type": "RAW",
                    "adjustment_reference": None,
                    "observation_admission": "FINAL_ONLY",
                },
                "calculations": [
                    {
                        "instance_key": "signal",
                        "type_reference": {
                            "kind": "INDICATOR",
                            "type_id": "onlyalpha.indicator.liquidity",
                            "semantic_version": "1",
                        },
                        "parameters": {},
                        "published_outputs": ["value"],
                        "input_bindings": [{"input_name": "close", "source": "bar.close"}],
                        "primary_output": "value",
                    }
                ],
                "factor_revision_dependencies": [],
                "eligibility": positive_close,
                "signals": {
                    "entry": positive_close,
                    "exit": positive_close,
                },
            },
            description="Momentum strategy",
            tags=("momentum",),
        )
    )


class _Authority:
    def __init__(self) -> None:
        self.factor = _factor()
        self.strategy = _strategy()

    def list_current_factor_revisions(self) -> tuple[OnlyPrivateFactorRevision, ...]:
        return (self.factor,)

    def list_current_strategy_revisions(self) -> tuple[OnlyPrivateStrategyRevision, ...]:
        return (self.strategy,)

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision:
        if factor_id != self.factor.factor_id or revision_fingerprint != self.factor.revision_fingerprint:
            raise OnlyPrivateAssetNotFoundError(revision_fingerprint)
        return self.factor

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision:
        if strategy_id != self.strategy.strategy_id or revision_fingerprint != self.strategy.revision_fingerprint:
            raise OnlyPrivateAssetNotFoundError(revision_fingerprint)
        return self.strategy


class _ProjectionStore:
    def __init__(self) -> None:
        self.value = None
        self.corrupt = False
        self.unavailable = False

    def publish(self, projection, built_at):  # type: ignore[no-untyped-def]
        self.value = (projection, built_at)

    def load_current(self):  # type: ignore[no-untyped-def]
        if self.unavailable:
            raise OnlyProductAssetSearchProjectionUnavailable("test unavailable")
        if self.corrupt:
            raise OnlyProductAssetSearchProjectionCorrupt("test corruption")
        return self.value


def _client() -> tuple[TestClient, _Authority, OnlyProductAssetSearchProjectionService]:
    authority = _Authority()
    registry = OnlyPrivateAssetProductService(authority)
    search = OnlyProductAssetSearchProjectionService(
        registry,
        _ProjectionStore(),
        lambda: datetime(2026, 9, 19, tzinfo=UTC),
    )
    app = FastAPI()
    install_private_asset_error_handlers(app)
    app.include_router(create_private_asset_router(registry, search))
    return TestClient(app), authority, search


def test_current_registry_and_search_expose_exact_locators_without_authoritative_content() -> None:
    client, _, search = _client()

    current = client.get("/api/v2/private-assets")
    assert current.status_code == 200
    assert [item["locator"]["private_asset_kind"] for item in current.json()["entries"]] == [
        "FACTOR",
        "STRATEGY",
    ]
    assert "source_text" not in current.text
    assert '"definition"' not in current.text

    unavailable = client.get("/api/v2/private-assets/search", params={"text": "momentum"})
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "PROJECTION_UNAVAILABLE"

    search._store.unavailable = True  # type: ignore[attr-defined]
    unavailable = client.get("/api/v2/private-assets/search", params={"text": "momentum"})
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "PROJECTION_UNAVAILABLE"
    search._store.unavailable = False  # type: ignore[attr-defined]

    search.rebuild()
    matched = client.get(
        "/api/v2/private-assets/search",
        params={"text": "momentum", "kind": "FACTOR", "tag": "price"},
    )
    assert matched.status_code == 200
    assert matched.json()["status"] == "MATCH"
    assert matched.json()["results"][0]["locator"]["private_asset_id"] == "private.factor.momentum"


def test_exact_factor_and_strategy_reads_require_both_revision_and_content_fingerprints() -> None:
    client, authority, _ = _client()
    factor = authority.factor
    strategy = authority.strategy

    factor_read = client.get(
        f"/api/v2/private-assets/factors/{factor.factor_id}/revisions/{factor.revision_fingerprint}",
        params={"content_fingerprint": factor.source_sha256},
    )
    assert factor_read.status_code == 200
    assert factor_read.json()["source_text"] == factor.source_text
    assert factor_read.json()["revision_fingerprint"] == factor.revision_fingerprint

    strategy_read = client.get(
        f"/api/v2/private-assets/strategies/{strategy.strategy_id}/revisions/{strategy.revision_fingerprint}",
        params={"content_fingerprint": strategy.definition_fingerprint},
    )
    assert strategy_read.status_code == 200
    assert strategy_read.json()["definition"] == strategy.to_dict()["definition"]
    assert strategy_read.json()["revision_fingerprint"] == strategy.revision_fingerprint

    assert (
        client.get(
            f"/api/v2/private-assets/factors/{factor.factor_id}/revisions/{factor.revision_fingerprint}"
        ).status_code
        == 422
    )


def test_exact_and_projection_failures_are_typed_and_never_fall_forward() -> None:
    client, authority, search = _client()
    factor = authority.factor

    mismatch = client.get(
        f"/api/v2/private-assets/factors/{factor.factor_id}/revisions/{factor.revision_fingerprint}",
        params={"content_fingerprint": "0" * 64},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "PRIVATE_ASSET_EXACT_READ_MISMATCH"

    missing = client.get(
        f"/api/v2/private-assets/factors/{factor.factor_id}/revisions/{'f' * 64}",
        params={"content_fingerprint": factor.source_sha256},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE"

    search.rebuild()
    search._store.corrupt = True  # type: ignore[attr-defined]
    corrupt = client.get("/api/v2/private-assets/search")
    assert corrupt.status_code == 500
    assert corrupt.json()["error"]["code"] == "PRIVATE_ASSET_SEARCH_PROJECTION_CORRUPT"
