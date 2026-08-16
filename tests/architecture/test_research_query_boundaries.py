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


def test_query_is_transport_neutral_and_depends_only_on_artifact_read_contract() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.engine",
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
        "onlyalpha.research.dataset",
        "onlyalpha.research.calculation",
        "onlyalpha.research.evaluation.result_store",
        "onlyalpha.research.result",
        "fastapi",
        "pydantic",
        "uvicorn",
        "pyarrow",
        "pathlib",
    )
    for path in Path("src/onlyalpha/research/query").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_producer_authorities_and_core_do_not_reverse_depend_on_query_or_api() -> None:
    for root in (
        Path("src/onlyalpha/research/dataset"),
        Path("src/onlyalpha/research/calculation"),
        Path("src/onlyalpha/research/evaluation"),
        Path("src/onlyalpha/research/result"),
        Path("src/onlyalpha/research/artifact"),
    ):
        for path in root.glob("*.py"):
            imports = _imports(path)
            assert not any(name.startswith(("onlyalpha.research.query", "onlyalpha_api")) for name in imports), path
    for path in Path("src/onlyalpha").rglob("*.py"):
        assert not any(name.startswith("onlyalpha_api") for name in _imports(path)), path


def test_http_routes_and_schema_only_consume_query_public_contract() -> None:
    adapter_root = Path("packages/api/onlyalpha-api/src/onlyalpha_api/research")
    forbidden = (
        "onlyalpha.research.artifact",
        "onlyalpha.research.dataset",
        "onlyalpha.research.calculation",
        "onlyalpha.research.evaluation",
        "onlyalpha.research.result",
        "pyarrow",
        "pathlib",
    )
    for path in adapter_root.glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)
    routes = (adapter_root / "routes.py").read_text(encoding="utf-8")
    assert not any(token in routes for token in ("open(", "read_text", "read_bytes", "parquet", "manifest"))


def test_only_server_composition_root_constructs_concrete_artifact_store() -> None:
    api_root = Path("packages/api/onlyalpha-api/src/onlyalpha_api")
    consumers = []
    for path in api_root.rglob("*.py"):
        if "OnlyParquetResearchArtifactStore" in path.read_text(encoding="utf-8"):
            consumers.append(path.relative_to(api_root).as_posix())
    assert consumers == ["main.py"]


def test_query_defines_no_durable_authority_catalog_or_semantic_calculation() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/research/query").glob("*.py"))
    forbidden = (
        "QueryResultStore",
        "QueryPlanFingerprint",
        "QueryResultFingerprint",
        "ArtifactCatalog",
        "latest",
        "mean_ic",
        "optimizer",
        "commit(",
        "exists(",
    )
    assert not any(token in source for token in forbidden)
    assert "load_verified" in source


def test_product_api_has_exactly_three_get_routes_and_live_remains_unsupported() -> None:
    routes = (Path("packages/api/onlyalpha-api/src/onlyalpha_api/research/routes.py")).read_text(encoding="utf-8")
    assert routes.count("@router.get(") == 3
    assert not any(token in routes for token in ("@router.post", "@router.put", "@router.patch", "@router.delete"))
    live = OnlyLiveRuntimeFactory().create(None)
    assert OnlyResearchRuntimeFactory().runtime_type == "RESEARCH"
    assert not live.supported and live.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
