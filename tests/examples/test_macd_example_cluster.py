import ast
from pathlib import Path

from tests.runtime_support.macd_plugin import OnlyTestMacdStrategy


def test_macd_strategy_source_uses_only_strategy_context_capabilities() -> None:
    path = Path("tests/runtime_support/macd_plugin.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strategy = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OnlyTestMacdStrategy"
    )
    forbidden = {
        "order_manager",
        "position_manager",
        "strategy_ledger_manager",
        "account_manager",
        "event_bus",
        "broker_gateway",
        "execution_processor",
    }
    attributes = {node.attr for node in ast.walk(strategy) if isinstance(node, ast.Attribute)}
    assert attributes.isdisjoint(forbidden)
    assert "list_open" in attributes
    assert "submit" in attributes
    assert OnlyTestMacdStrategy.__mro__[1].__name__ == "OnlyStrategy"
    assert "indicators" not in attributes
