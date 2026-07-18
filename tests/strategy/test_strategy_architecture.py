import ast
from pathlib import Path

from onlyalpha.strategy.context import OnlyStrategyContext


def test_strategy_context_exposes_factor_view_but_no_indicator_registry_or_manager() -> None:
    attributes = set(OnlyStrategyContext.__dict__)
    assert "factors" in attributes
    assert "orders" in attributes
    assert attributes.isdisjoint({"indicators", "indicator_registry", "runtime", "manager", "broker_gateway"})


def test_macd_strategy_reads_factor_and_does_not_compute_or_create_macd() -> None:
    tree = ast.parse(
        Path(
            "tests/fixtures/external_plugins/onlyalpha_test_plugin/src/onlyalpha_test_plugin/macd_plugin.py"
        ).read_text(encoding="utf-8")
    )
    strategy = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OnlyTestMacdStrategy"
    )
    names = {node.id for node in ast.walk(strategy) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(strategy) if isinstance(node, ast.Attribute)}
    assert "OnlyMacdIndicator" not in names
    assert "create_for_bars" not in attributes
    assert {"factors", "submit"} <= attributes
