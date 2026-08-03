from pathlib import Path


def test_paper_factory_is_broker_free_and_only_injects_shadow_execution() -> None:
    source = Path("src/onlyalpha/runtime/paper/factory.py").read_text(encoding="utf-8")

    assert "OnlyShadowExecutionService()" in source
    assert "components.brokers.resolve" not in source
    assert "components.brokers.create" not in source
    assert "OnlyBrokerGateway" not in source
    assert "onlyalpha_plugin_miniqmt" not in source


def test_miniqmt_callback_boundary_only_normalizes_and_publishes() -> None:
    source = Path(
        "packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/data_source/live.py"
    ).read_text(encoding="utf-8")

    for forbidden in ("onlyalpha.strategy", "onlyalpha.risk", "onlyalpha.order", "print(", "jsonl"):
        assert forbidden not in source.lower()


def test_paper_runtime_has_no_parallel_business_loop() -> None:
    source = Path("src/onlyalpha/runtime/paper/runtime.py").read_text(encoding="utf-8")

    assert "OnlyStreamingRuntime" in source
    for forbidden in ("def start(", "def wait(", "def stop(", "def on_bar("):
        assert forbidden not in source


def test_streaming_runtime_requires_formal_historical_warmup_before_subscription() -> None:
    source = Path("src/onlyalpha/runtime/streaming/runtime.py").read_text(encoding="utf-8")

    warmup = source.index("self._bootstrap()")
    subscribe = source.index("result = subscribe(self._streaming_subscription)")
    assert warmup < subscribe
    assert "set_subscription_bootstrap_count" not in source
