import ast
from pathlib import Path


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return tuple(result)


def test_strategy_domain_has_no_downstream_or_provider_dependencies() -> None:
    forbidden = (
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.fee",
        "onlyalpha.execution",
        "fastapi",
        "binance",
        "onlyalpha_plugin_",
    )
    for path in Path("src/onlyalpha/strategy").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(forbidden), f"{path}: forbidden Strategy dependency {imported}"


def test_runtime_and_cluster_have_no_dynamic_strategy_authority() -> None:
    roots = (Path("src/onlyalpha/runtime"), Path("src/onlyalpha/cluster"))
    forbidden = (
        "OnlyStrategyCreateRequest",
        "OnlyStrategyFactory",
        "strategy_path",
        "config.strategy.config_path",
    )
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for value in forbidden:
                assert value not in source, f"{path}: legacy Strategy authority {value}"


def test_legacy_strategy_factory_is_absent_and_config_is_fingerprint_only() -> None:
    assert not Path("src/onlyalpha/strategy/factory.py").exists()
    source = Path("src/onlyalpha/config/models.py").read_text(encoding="utf-8")
    assert "class OnlyStrategyReferenceConfig" in source
    assert "class OnlyStrategyImportConfig" not in source
    assert "strategy_path" not in source


def test_candidate_and_web_do_not_reach_trading_strategy_composition() -> None:
    composition = Path("src/onlyalpha/cluster/factory.py").read_text(encoding="utf-8") + Path(
        "src/onlyalpha/strategy/execution.py"
    ).read_text(encoding="utf-8")
    assert "candidate_fingerprint" not in composition
    for root in (Path("src/onlyalpha/api"), Path("src/onlyalpha/application")):
        if root.exists():
            for path in root.rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                assert "OnlyStrategyRevision(" not in source
                assert "OnlyStrategyMarketInputContract(" not in source


def test_backtest_and_sim_share_the_single_cluster_strategy_resolver() -> None:
    cluster = Path("src/onlyalpha/cluster/factory.py").read_text(encoding="utf-8")
    backtest = Path("src/onlyalpha/runtime/backtest/factory.py").read_text(encoding="utf-8")
    sim = Path("src/onlyalpha/runtime/sim/factory.py").read_text(encoding="utf-8")

    assert cluster.count("OnlyStrategyExecutionResolver(") == 1
    assert "components.clusters.create(" in sim
    assert "components.clusters.create(" in backtest
    assert "OnlyStrategyRevision(" not in backtest + sim
