from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.defaults import only_default_run_service


def test_synthetic_macd_is_deterministic_for_100_replays() -> None:
    config = OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml")
    baseline = only_default_run_service().run(config, export=False).determinism_fingerprint
    for _ in range(100):
        assert only_default_run_service().run(config, export=False).determinism_fingerprint == baseline
