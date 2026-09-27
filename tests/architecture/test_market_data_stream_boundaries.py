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
    subscribe = client.split("marketDataStreamSubscribeSchema", 1)[1].split("});", 1)[0]
    assert "resume_after_sequence" in subscribe
    assert all(field not in subscribe for field in ("open:", "high:", "low:", "close:", "volume:"))


def test_forming_preview_is_not_a_canonical_market_fact() -> None:
    models = (ROOT / "src/onlyalpha/data/models.py").read_text(encoding="utf-8")
    ingress = (ROOT / "src/onlyalpha/market_data/durable/ingress.py").read_text(encoding="utf-8")
    assert "class OnlyRealtimeBarPreviewV1" in models
    assert "OnlyRealtimeBarPreviewV1" not in ingress
