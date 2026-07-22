from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from onlyalpha.config import OnlyClusterCapitalConfig, OnlyClusterCapitalMode, OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def _run(tmp_path: Path, *configs: str):
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("integration-engine"), tmp_path))
    for config in configs:
        engine.add_cluster_from_file(config)
    return engine.run()


def _run_multi(tmp_path: Path, paths: tuple[str, str] = (CONFIG, FAST_CONFIG)):
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("integration-engine"), tmp_path))
    for path in paths:
        config = OnlyClusterRunConfig.load(path)
        engine.add_cluster(
            replace(
                config,
                cluster=replace(
                    config.cluster,
                    capital=OnlyClusterCapitalConfig(
                        OnlyClusterCapitalMode.FIXED_CAPITAL,
                        OnlyMoney(Decimal("500000.00"), config.accounts[0].initial_cash.currency),
                    ),
                ),
            )
        )
    return engine.run()


def test_cli_equivalent_single_cluster_full_backtest(tmp_path: Path) -> None:
    result = _run(tmp_path, CONFIG)
    assert result.status == "COMPLETED"
    projection = result.cluster_results[0]
    assert projection["data"]["processed_bar_count"] == 720  # type: ignore[index]
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    assert result.manifest_path is not None and result.manifest_path.is_file()


def test_two_clusters_are_isolated_and_share_registry_resources(tmp_path: Path) -> None:
    result = _run_multi(tmp_path)
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
    assert len(result.runtime_results) == 1
    runtime_result = result.runtime_results[0]
    assert len(runtime_result.cluster_results) == 2  # type: ignore[attr-defined]
    assert runtime_result.reconciliation.status == "MATCHED"  # type: ignore[attr-defined]
    assert sum(item.performance.initial_equity.amount for item in runtime_result.cluster_results) == Decimal(  # type: ignore[attr-defined]
        "1000000.00"
    )
    assert sum(item.performance.final_equity.amount for item in runtime_result.cluster_results) == (  # type: ignore[attr-defined]
        runtime_result.runtime_performance.final_equity.amount  # type: ignore[attr-defined]
    )
    assert {str(item.instrument_id) for item in runtime_result.trades} == {"TESTETF.XSHG"}  # type: ignore[attr-defined]


def test_multi_cluster_registration_order_does_not_change_result(tmp_path: Path) -> None:
    first = _run_multi(tmp_path / "first")
    second = _run_multi(tmp_path / "second", (FAST_CONFIG, CONFIG))

    assert first.status == second.status == "COMPLETED"
    assert first.determinism_fingerprint == second.determinism_fingerprint
    assert [item["run"]["cluster_ids"][0] for item in first.cluster_results] == [  # type: ignore[index]
        item["run"]["cluster_ids"][0]
        for item in second.cluster_results  # type: ignore[index]
    ]


def test_two_clusters_can_both_profit_in_one_shared_runtime(tmp_path: Path) -> None:
    first = OnlyClusterRunConfig.load(CONFIG)
    second = OnlyClusterRunConfig.load(FAST_CONFIG)
    currency = first.accounts[0].initial_cash.currency
    capital = OnlyClusterCapitalConfig(
        OnlyClusterCapitalMode.FIXED_CAPITAL,
        OnlyMoney(Decimal("500000.00"), currency),
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("both-profit-engine"), tmp_path))
    engine.add_cluster(replace(first, cluster=replace(first.cluster, capital=capital)))
    engine.add_cluster(
        replace(
            second,
            cluster=replace(
                second.cluster,
                capital=capital,
                strategy=first.strategy,
                factors=first.factors,
            ),
            strategy=first.strategy,
            factors=first.factors,
        )
    )

    result = engine.run()
    runtime_result = result.runtime_results[0]

    assert result.status == "COMPLETED"
    assert len(result.runtime_results) == 1
    assert all(item.performance.net_pnl.amount > 0 for item in runtime_result.cluster_results)  # type: ignore[attr-defined]
    assert runtime_result.reconciliation.status == "MATCHED"  # type: ignore[attr-defined]


def test_output_path_does_not_change_business_fingerprint(tmp_path: Path) -> None:
    first = _run(tmp_path / "one", CONFIG)
    second = _run(tmp_path / "two", CONFIG)
    assert first.run_id != second.run_id
    assert first.determinism_fingerprint == second.determinism_fingerprint
