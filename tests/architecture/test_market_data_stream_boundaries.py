from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_websocket_adapter_has_no_binance_or_persistence_logic() -> None:
    route = (ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/market_data/stream_routes.py").read_text(
        encoding="utf-8"
    )
    assert "onlyalpha_plugin_binance" not in route
    assert "OnlyMarketDataWal" not in route


def test_browser_stream_uses_only_product_websocket_and_cursor_truth() -> None:
    client = (ROOT / "packages/onlyalpha-web-console/src/api/marketData/stream.ts").read_text(encoding="utf-8")
    assert "/api/v2/market-data/stream" in client
    assert "binance.com" not in client
    generated = (ROOT / "packages/onlyalpha-web-console/src/api/marketData/stream.generated.ts").read_text(
        encoding="utf-8"
    )
    subscribe = generated.split("export const marketDataStreamSubscribeSchema =", 1)[1].split(
        "export const marketDataStreamEventSchema", 1
    )[0]
    assert "resume_after_sequence" in subscribe and "resume_plan_fingerprint" in subscribe
    assert all(field not in subscribe for field in ("open:", "high:", "low:", "close:", "volume:"))


def test_shipping_browser_has_no_provider_network_or_synthetic_chart_path() -> None:
    web = ROOT / "packages/onlyalpha-web-console/src"
    for path in web.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name or "test" in path.relative_to(web).parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert not any(
            token in source
            for token in (
                "api.binance.com",
                "stream.binance.com",
                "data-api.binance.vision",
                "@binance/",
                "binance-api-node",
                "buildPlaceholderBars",
                "buildPlaceholderOverlay",
                "syntheticInstruments",
            )
        ), path
    workspace = (web / "features/workspace/WorkspacePage.tsx").read_text(encoding="utf-8")
    assert "placeholderBars" not in workspace
    assert "indicatorCatalog" not in workspace and "factorCatalog" not in workspace


def test_forming_preview_is_not_a_canonical_market_fact() -> None:
    models = (ROOT / "src/onlyalpha/data/models.py").read_text(encoding="utf-8")
    ingress = (ROOT / "src/onlyalpha/market_data/durable/ingress.py").read_text(encoding="utf-8")
    assert "class OnlyRealtimeBarPreviewV1" in models
    assert "OnlyRealtimeBarPreviewV1" not in ingress


def test_real_time_bar_path_has_typed_specification_without_period_whitelist() -> None:
    product = (ROOT / "src/onlyalpha/application/market_data_product.py").read_text(encoding="utf-8")
    stream = (ROOT / "src/onlyalpha/application/market_data_stream.py").read_text(encoding="utf-8")
    aggregator = (ROOT / "src/onlyalpha/market_data/aggregation/time_bar.py").read_text(encoding="utf-8")
    workspace = (ROOT / "packages/onlyalpha-web-console/src/features/workspace/useMarketDataChart.ts").read_text(
        encoding="utf-8"
    )
    assert "SUPPORTED_BAR_SPECIFICATION" not in product
    assert "bar_semantic: OnlyBarSemantic" in product
    assert "bar_semantic: OnlyBarSemantic" in stream
    assert "{3, 5, 15}" not in aggregator
    assert "Timeframe" not in workspace
    assert "bar_semantic: barSemantic" in workspace
