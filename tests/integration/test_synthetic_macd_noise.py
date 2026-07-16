import json

from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.defaults import only_default_run_service


def _config(seed: int) -> OnlyRunConfig:
    baseline = OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["data_sources"][0]["extensions"]["market_config"] = "synthetic_market_noise.yaml"
    payload["data_sources"][0]["extensions"]["random_seed"] = seed
    return OnlyRunConfig.from_mapping(payload, source_path="examples/configs/backtest/macd/run.yaml")


def test_fixed_seed_noise_product_run_is_stable_and_seed_sensitive() -> None:
    first = only_default_run_service().run(_config(20260715), export=False).determinism_fingerprint
    second = only_default_run_service().run(_config(20260715), export=False).determinism_fingerprint
    third = only_default_run_service().run(_config(20260716), export=False).determinism_fingerprint
    assert first == second
    assert first != third
