from onlyalpha.config import OnlyClusterRunConfig

from ..runtime_runner import only_run_cluster_runtime


def test_synthetic_macd_is_deterministic_for_100_replays() -> None:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    baseline = only_run_cluster_runtime(config).determinism_fingerprint
    for _ in range(10):
        assert only_run_cluster_runtime(config).determinism_fingerprint == baseline
