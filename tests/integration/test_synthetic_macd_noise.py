import json

from onlyalpha.config import OnlyClusterRunConfig
from tests.runtime_runner import only_run_cluster_runtime


def _config(seed: int) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["data_sources"][0]["extensions"]["market_config"] = "synthetic_market_noise.yaml"
    payload["data_sources"][0]["extensions"]["random_seed"] = seed
    return OnlyClusterRunConfig.from_mapping(payload, source_path="tests/fixtures/legacy_macd/cluster.json")


def test_fixed_seed_noise_product_run_is_stable_and_seed_sensitive() -> None:
    first = only_run_cluster_runtime(_config(20260715)).determinism_fingerprint
    second = only_run_cluster_runtime(_config(20260715)).determinism_fingerprint
    third = only_run_cluster_runtime(_config(20260716)).determinism_fingerprint
    assert first == second
    assert first != third
