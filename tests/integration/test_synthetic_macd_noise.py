from dataclasses import replace

from onlyalpha.backtest import OnlyBacktestConfig
from onlyalpha.data.synthetic import OnlySyntheticNoiseModel
from onlyalpha.runtime import OnlyBacktestRuntime


def test_fixed_seed_noise_product_run_is_stable_and_seed_sensitive() -> None:
    config = OnlyBacktestConfig.load("examples/backtest_macd/config.yaml")
    instrument_config = replace(
        config.synthetic_source.instruments[0],
        noise_model=OnlySyntheticNoiseModel(True, 2),
    )
    noisy = replace(config, synthetic_source=replace(config.synthetic_source, instruments=(instrument_config,)))
    first = OnlyBacktestRuntime.from_config(noisy).run().determinism_fingerprint
    second = OnlyBacktestRuntime.from_config(noisy).run().determinism_fingerprint
    changed = replace(noisy, synthetic_source=replace(noisy.synthetic_source, random_seed=20260716))
    third = OnlyBacktestRuntime.from_config(changed).run().determinism_fingerprint
    assert first == second
    assert first != third
