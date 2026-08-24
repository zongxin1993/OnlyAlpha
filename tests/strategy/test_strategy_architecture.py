import ast
from pathlib import Path


def test_callback_strategy_authoring_surface_is_absent() -> None:
    for path in (
        Path("src/onlyalpha/strategy/base.py"),
        Path("src/onlyalpha/strategy/config.py"),
        Path("src/onlyalpha/strategy/context.py"),
    ):
        assert not path.exists()
    public = Path("src/onlyalpha/strategy/__init__.py").read_text(encoding="utf-8")
    assert "OnlyStrategyContext" not in public
    assert "OnlyStrategyConfig" not in public
    assert "from onlyalpha.strategy.base import OnlyStrategy" not in public


def test_revision_adapter_contains_lifecycle_plumbing_without_order_capabilities() -> None:
    path = Path("src/onlyalpha/strategy/adapter.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [item.name for item in classes] == ["OnlyRevisionStrategyAdapter"]
    source = path.read_text(encoding="utf-8")
    for forbidden in ("orders", "positions", "accounts", "risk", "broker", "OnlyStrategyContext"):
        assert forbidden not in source
