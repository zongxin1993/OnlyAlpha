from dataclasses import fields
from pathlib import Path

from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.config import OnlyRunConfig
from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription
from onlyalpha.strategy.base import OnlyStrategy


def test_removed_legacy_strategy_indicator_ownership_paths_do_not_return() -> None:
    assert not Path("src/onlyalpha/strategy/macd.py").exists()
    assert not Path("src/onlyalpha/strategies/macd.py").exists()
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/onlyalpha").rglob("*.py")
        if "indicator/macd" not in str(path)
    )
    assert "OnlyStrategyBuildResult" not in production
    assert "MACD_EXAMPLE" not in production
    assert "OnlyMacdExampleCluster" not in production
    assert "OnlyMacdStrategyFactory" not in production


def test_bar_subscription_has_no_indicator_ids_and_runtime_factory_is_algorithm_agnostic() -> None:
    assert {item.name for item in fields(OnlyClusterBarSubscription)} == {"cluster", "subscription"}
    source = Path("src/onlyalpha/runtime/backtest/factory.py").read_text(encoding="utf-8")
    assert "OnlyMacd" not in source
    assert "OnlyRsi" not in source
    assert "register_indicator" not in source


def test_config_and_product_model_are_cluster_strategy_factor_indicator() -> None:
    config = OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml")
    assert len(config.clusters) == 1
    cluster = config.clusters[0]
    assert cluster.strategy.strategy_path.endswith(":OnlyMacdStrategy")
    assert len(cluster.factors) == 1
    assert cluster.factors[0].factor_path.endswith(":OnlyMacdSignalFactor")
    assert [str(item.indicator_type) for item in cluster.factors[0].indicators] == ["MACD"]
    assert not issubclass(type(cluster.strategy), OnlyCluster)
    assert not issubclass(OnlyStrategy, OnlyCluster)
