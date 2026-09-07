import ast
from dataclasses import fields
from pathlib import Path

from onlyalpha.research.search.parameter import OnlyParameterSearchFeedbackDecisionV1


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_parameter_search_has_no_trading_live_or_concrete_market_authority() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.reservation",
        "onlyalpha.transaction",
        "onlyalpha.live",
    )
    for path in Path("src/onlyalpha/research/search/parameter").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_parameter_search_has_no_mutable_optimizer_or_second_scientific_truth() -> None:
    root = Path("src/onlyalpha/research/search/parameter")
    identifiers = {
        node.id.lower()
        for path in root.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name)
    }
    assert not identifiers & {"optuna", "tpe", "bayesian", "ppo", "trialdb", "optimizerstudy"}
    names = {field.name for field in fields(OnlyParameterSearchFeedbackDecisionV1)}
    assert not names & {
        "ic",
        "rank_ic",
        "icir",
        "sharpe",
        "coverage",
        "stability",
        "qualification_decision",
    }


def test_parameter_search_reuses_canonical_graph_sweep_research_and_command_boundaries() -> None:
    imports = set().union(*(_imports(path) for path in Path("src/onlyalpha/research/search/parameter").glob("*.py")))
    assert "onlyalpha.calculation.graph" in imports
    assert "onlyalpha.research.sweep.materialization" in imports
    assert "onlyalpha.research.specification.resolver" in imports
    assert "onlyalpha.research.command.model" in imports
