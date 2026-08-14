import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_research_sweep_has_no_trading_authority_or_mutable_lifecycle_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.strategy",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.reservation",
        "onlyalpha.execution",
        "onlyalpha.transaction",
    )
    root = Path("src/onlyalpha/research/sweep")
    for path in root.glob("*.py"):
        imports = _imports(path)
        source = path.read_text(encoding="utf-8")
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)
        assert "OnlyResearchCalculationExecutor" not in source
        assert "ResultStore" not in source
        assert "only_canonical_fingerprint" not in source


def test_sweep_defines_no_parallel_semantic_or_durable_authority() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/research/sweep").glob("*.py"))
    forbidden = (
        "SweepCellFingerprint",
        "TrialFingerprint",
        "SweepResultStore",
        "SweepCheckpoint",
        "SweepManager",
        "TrialManager",
        "ThreadPool",
        "ProcessPool",
    )
    assert not any(name in source for name in forbidden)
    assert "OnlyResearchJobExecutor" in source


def test_template_identity_does_not_leak_into_calculation_core() -> None:
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "TemplateNodeId" not in source
        assert "onlyalpha.research.sweep" not in source
