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
        "onlyalpha.runtime.live",
        "onlyalpha.data.synthetic",
        "onlyalpha.broker.virtual",
        "onlyalpha.strategy.macd",
        "onlyalpha_plugin_indicators",
    )
    paths = [*Path("src/onlyalpha/config").glob("*.py"), Path("src/onlyalpha/runtime/assembler.py")]
    for path in paths:
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_concrete_implementations_live_below_parent_component_packages() -> None:
    required = (
        "src/onlyalpha/runtime/backtest/runtime.py",
        "src/onlyalpha/runtime/sim/runtime.py",
        "src/onlyalpha/runtime/live/runtime.py",
        "src/onlyalpha/runtime/research/runtime.py",
        "src/onlyalpha/data/synthetic/source.py",
        "plugs/onlyalpha-plugin-broker-virtual/src/onlyalpha_plugin_broker_virtual/gateway.py",
        "plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators/macd.py",
    )
    assert all(Path(path).is_file() for path in required)


def test_core_does_not_import_virtual_broker_plugin() -> None:
    for path in Path("src/onlyalpha").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "onlyalpha_plugin_broker_virtual" not in source, path
        assert "onlyalpha.broker.virtual" not in source, path


def test_root_cli_has_no_product_engine_mutation_capability() -> None:
    assert not Path("src/onlyalpha/cli.py").exists()
    engine = Path("src/onlyalpha/engine/engine.py").read_text(encoding="utf-8")
    assert "add_cluster_from_file" not in engine
    assert "OnlyClusterRunConfig.load(" not in engine
