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
    assert "load_warmup" in source
    assert "load_bars" not in source


def test_miniqmt_historical_warmup_uses_a_short_lived_interpreter_process() -> None:
    client = Path(
        "packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/client.py"
    ).read_text(encoding="utf-8")
    worker = Path(
        "packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/worker.py"
    ).read_text(encoding="utf-8")
    core = Path("src/onlyalpha/data/warmup.py").read_text(encoding="utf-8")

    assert "subprocess.Popen" in client
    assert "sys.executable" in client
    assert "ThreadPoolExecutor" not in client
    assert 'import_module("xtquant")' in worker
    assert "xtquant" not in core.lower()


def test_miniqmt_historical_worker_has_no_runtime_or_engine_dependency() -> None:
    root = Path("packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker")
    worker_sources = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    for forbidden in (
        "onlyalpha.runtime",
        "onlyalpha.engine",
        "OnlyEventBus",
        "OnlyCluster",
        "OnlyClock",
    ):
        assert forbidden not in worker_sources
