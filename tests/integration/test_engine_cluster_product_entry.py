from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

CONFIG = "examples/clusters/macd/config.yaml"
FAST_CONFIG = "examples/clusters/macd_fast/config.yaml"


def _run(tmp_path: Path, *configs: str):
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("integration-engine"), tmp_path))
    for config in configs:
        engine.add_cluster_from_file(config)
    return engine.run()


def test_cli_equivalent_single_cluster_full_backtest(tmp_path: Path) -> None:
    result = _run(tmp_path, CONFIG)
    assert result.status == "COMPLETED"
    projection = result.cluster_results[0]
    assert projection["data"]["processed_bar_count"] == 720  # type: ignore[index]
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    assert result.manifest_path is not None and result.manifest_path.is_file()


def test_two_clusters_are_isolated_and_share_registry_resources(tmp_path: Path) -> None:
    result = _run(tmp_path, CONFIG, FAST_CONFIG)
    assert result.status == "COMPLETED"
    assert len(result.cluster_results) == 2
    ids = [item["run"]["cluster_ids"][0] for item in result.cluster_results]  # type: ignore[index]
    assert ids == ["macd-demo", "macd-fast-demo"]
    runtime_ids = {item["run"]["runtime_id"] for item in result.cluster_results}  # type: ignore[index]
    assert len(runtime_ids) == 1
    assert all(item["execution"]["order_count"] == len(item["orders"]) for item in result.cluster_results)  # type: ignore[index]
    assert all(item["execution"]["trade_count"] == len(item["trades"]) for item in result.cluster_results)  # type: ignore[index]
    assert all(item["execution"]["order_count"] > 0 for item in result.cluster_results)  # type: ignore[index]
    run_root = result.manifest_path.parent  # type: ignore[union-attr]
    assert (run_root / "clusters/macd-demo/summary.json").is_file()
    assert (run_root / "clusters/macd-fast-demo/summary.json").is_file()


def test_output_path_does_not_change_business_fingerprint(tmp_path: Path) -> None:
    first = _run(tmp_path / "one", CONFIG)
    second = _run(tmp_path / "two", CONFIG)
    assert first.run_id != second.run_id
    assert first.determinism_fingerprint == second.determinism_fingerprint
