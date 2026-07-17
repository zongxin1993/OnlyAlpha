import ast
from pathlib import Path

from onlyalpha_examples.strategies.macd import OnlyMacdStrategy


def test_macd_strategy_source_uses_only_strategy_context_capabilities() -> None:
    path = Path("plugins/onlyalpha_examples/src/onlyalpha_examples/strategies/macd/strategy.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {
        "order_manager",
        "position_manager",
        "strategy_ledger_manager",
        "account_manager",
        "event_bus",
        "broker_gateway",
        "execution_processor",
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert attributes.isdisjoint(forbidden)
    assert "list_open" in attributes
    assert "submit" in attributes
    assert OnlyMacdStrategy.__mro__[1].__name__ == "OnlyStrategy"
    assert "indicators" not in attributes
