import ast
from pathlib import Path


def test_external_macd_fixture_contains_factor_only_and_no_callback_strategy() -> None:
    path = Path("tests/fixtures/external_plugins/onlyalpha_test_plugin/src/onlyalpha_test_plugin/macd_plugin.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "OnlyTestMacdFactor" in classes
    assert all("Strategy" not in name for name in classes)
    source = path.read_text(encoding="utf-8")
    assert "onlyalpha.strategy.base" not in source
    assert ".orders.submit(" not in source
