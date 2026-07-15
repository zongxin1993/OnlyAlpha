from onlyalpha.backtest import OnlyBacktestConfig
from onlyalpha.runtime import OnlyBacktestRuntime


def test_synthetic_macd_is_deterministic_for_100_replays() -> None:
    config = OnlyBacktestConfig.load("examples/backtest_macd/config.yaml")
    baseline = OnlyBacktestRuntime.from_config(config).run().determinism_fingerprint
    for _ in range(100):
        assert OnlyBacktestRuntime.from_config(config).run().determinism_fingerprint == baseline
