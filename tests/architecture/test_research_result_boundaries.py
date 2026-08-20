from __future__ import annotations

import ast
from pathlib import Path

from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_research_result_depends_only_on_research_public_authorities_and_neutral_helpers() -> None:
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
        "onlyalpha.settlement",
        "onlyalpha.web",
        "onlyalpha.cli",
        "onlyalpha.research.sweep",
    )
    root = Path("src/onlyalpha/research/result")
    for path in root.glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_research_result_defines_no_parallel_data_or_trading_authority() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/research/result").glob("*.py"))
    forbidden = (
        "ResearchResultManager",
        "ExperimentManager",
        "Optimizer",
        "SweepOutcome",
        "data.parquet",
        "OnlyResearchStatisticRow",
        "ScientificEvidenceStore",
        "CandidateStore",
        "SignalStore",
        "GraphStore",
    )
    assert not any(name in source for name in forbidden)
    assert "load_verified" in source
    assert "statistics_result_fingerprint" in source


def test_research_is_activated_and_live_remains_unsupported_after_p7_11() -> None:
    live = OnlyLiveRuntimeFactory().create(None)
    assert OnlyResearchRuntimeFactory().runtime_type == "RESEARCH"
    assert not live.supported and live.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
