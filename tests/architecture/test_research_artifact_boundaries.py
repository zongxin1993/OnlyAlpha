from __future__ import annotations

import ast
import inspect
from pathlib import Path

from onlyalpha.research.artifact import OnlyParquetResearchArtifactStore
from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_research_artifact_depends_only_on_public_research_semantics_and_neutral_helpers() -> None:
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
        "onlyalpha.sim",
        "onlyalpha.backtest",
        "onlyalpha.web",
        "onlyalpha.cli",
        "onlyalpha.artifact",
    )
    for path in Path("src/onlyalpha/research/artifact").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_producer_authorities_do_not_reverse_depend_on_artifact() -> None:
    for root in (Path("src/onlyalpha/research/evaluation"), Path("src/onlyalpha/research/result")):
        for path in root.glob("*.py"):
            assert not any(name.startswith("onlyalpha.research.artifact") for name in _imports(path)), path


def test_portable_store_constructor_and_load_boundary_require_no_upstream_store() -> None:
    constructor = inspect.signature(OnlyParquetResearchArtifactStore)
    load = inspect.signature(OnlyParquetResearchArtifactStore.load_verified)
    assert tuple(constructor.parameters) == ("root", "compression", "row_group_size", "audit_time")
    assert tuple(load.parameters) == ("self", "research_result_fingerprint")


def test_artifact_defines_no_plan_result_or_trading_authority_and_runtimes_remain_unsupported() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/research/artifact").glob("*.py")
    )
    forbidden = (
        "OnlyResearchArtifactPlan",
        "OnlyResearchArtifactResult",
        "ArtifactManager",
        "ExperimentManager",
        "Optimizer",
        "OnlyAccount",
        "OnlyOrder",
        "OnlyPosition",
    )
    assert not any(name in source for name in forbidden)
    assert "load_verified" in source
    assert "artifact_manifest.json" in source and "statistics.parquet" in source
    research = OnlyResearchRuntimeFactory().create(None)
    live = OnlyLiveRuntimeFactory().create(None)
    assert not research.supported and research.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
    assert not live.supported and live.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
