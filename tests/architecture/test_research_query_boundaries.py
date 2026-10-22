from __future__ import annotations

import ast
import json
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
        "onlyalpha.research.evaluation.execution",
        "onlyalpha.research.evaluation.factor_pair.execution",
        "onlyalpha.research.evaluation.factor_pair.result_store",
        "onlyalpha.research.evaluation.summary.execution",
        "onlyalpha.research.evaluation.summary.result_store",
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
            assert not any(
                name.startswith(("onlyalpha.research.query", "onlyalpha_http_server")) for name in imports
            ), path
    for path in Path("src/onlyalpha").rglob("*.py"):
        assert not any(name.startswith("onlyalpha_http_server") for name in _imports(path)), path


def test_retired_research_transport_cannot_read_artifacts_or_own_wire_schema() -> None:
    adapter_root = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/research")
    assert not tuple(adapter_root.rglob("*.py"))
    native = json.loads(Path("contracts/product-api/v2/openapi.json").read_text())
    operations = [
        operation
        for path, methods in native["paths"].items()
        if path.startswith("/api/v2/research/artifacts/")
        for operation in methods.values()
    ]
    assert len(operations) == 9
    assert all(set(operation["responses"]) == {"501"} for operation in operations)


def test_retired_research_server_constructs_no_artifact_profile_reader() -> None:
    api_root = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server")
    assert not tuple(api_root.rglob("*.py"))
    assert not any(
        "OnlyResearchArtifactProfileReader" in path.read_text()
        for path in Path("packages/onlyalpha-http-server/rust").glob("*.rs")
    )


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
        "resolve_metric",
        "meets_threshold",
        "qualify(",
        "float(",
    )
    assert not any(token in source for token in forbidden)
    assert "load_verified" in source


def test_product_api_research_reads_and_live_remain_explicitly_unsupported() -> None:
    native = json.loads(Path("contracts/product-api/v2/openapi.json").read_text())
    for path, methods in native["paths"].items():
        if path.startswith("/api/v2/research/artifacts/"):
            assert set(methods) == {"get"}
            assert set(methods["get"]["responses"]) == {"501"}
    live = OnlyLiveRuntimeFactory().create(None)
    assert OnlyResearchRuntimeFactory().runtime_type == "RESEARCH"
    assert not live.supported and live.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
