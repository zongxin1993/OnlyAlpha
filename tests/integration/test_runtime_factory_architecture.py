import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_common_config_and_assembler_do_not_import_concrete_components() -> None:
    forbidden = (
        "onlyalpha.runtime.backtest",
        "onlyalpha.runtime.paper",
        "onlyalpha.runtime.live",
        "onlyalpha.data.synthetic",
        "onlyalpha.broker.virtual",
        "onlyalpha.strategy.macd",
        "onlyalpha.indicator.macd",
    )
    paths = [*Path("src/onlyalpha/config").glob("*.py"), Path("src/onlyalpha/runtime/assembler.py")]
    for path in paths:
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_concrete_implementations_live_below_parent_component_packages() -> None:
    required = (
        "src/onlyalpha/runtime/backtest/runtime.py",
        "src/onlyalpha/runtime/paper/runtime.py",
        "src/onlyalpha/runtime/live/runtime.py",
        "src/onlyalpha/runtime/shadow/runtime.py",
        "src/onlyalpha/runtime/research/runtime.py",
        "src/onlyalpha/data/synthetic/source.py",
        "src/onlyalpha/broker/virtual/gateway.py",
        "src/onlyalpha/indicator/macd/indicator.py",
    )
    assert all(Path(path).is_file() for path in required)


def test_product_entry_uses_only_engine_public_api() -> None:
    source = Path("src/onlyalpha/cli.py").read_text(encoding="utf-8")
    assert "OnlyEngine" in source
    assert "add_cluster_from_file" in source
    assert "only_default_run_service" not in source
    assert "OnlyBacktestRuntime" not in source
    assert ".from_config(" not in source
    assert ".save(" not in source
