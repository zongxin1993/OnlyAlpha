from onlyalpha.config import OnlyClusterRunConfig

from ..runtime_support.runner import only_run_cluster_runtime


def test_synthetic_macd_is_deterministic_for_2_replays() -> None:
    config = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    baseline = only_run_cluster_runtime(config).determinism_fingerprint
    for _ in range(2):
        assert only_run_cluster_runtime(config).determinism_fingerprint == baseline
