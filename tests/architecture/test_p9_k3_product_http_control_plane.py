from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API = ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api"
RUN_ROUTES = API / "research/run_routes.py"
APP = API / "app.py"
MAIN = API / "main.py"


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return frozenset(result)


def test_canonical_run_http_uses_only_product_command_and_query_boundary() -> None:
    source = RUN_ROUTES.read_text(encoding="utf-8")
    imports = _imports(RUN_ROUTES)
    assert "onlyalpha.application.product_boundary" in imports
    assert "onlyalpha.research.command.service" not in imports
    assert "OnlyResearchCommandService" not in source
    assert "OnlyResearchRunQueryService" not in source
    assert source.count("product.commands.dispatch(") == 2
    assert source.count("product.queries.dispatch(") == 2
    for intent in (
        "OnlyCreateResearchRun(",
        "OnlyCancelResearchRun(",
        "OnlyGetResearchRun(",
        "OnlyListResearchRuns(",
    ):
        assert source.count(intent) == 1


def test_product_app_cannot_receive_legacy_direct_run_services() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "product_boundary: OnlyResearchProductBoundary" in source
    assert "create_run_router(product_boundary)" in source
    assert "OnlyResearchCommandService" not in source
    assert "OnlyResearchRunQueryService" not in source


def test_one_main_composition_uses_same_started_host_and_forbids_multi_worker() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert source.count("OnlyAlphaKernelHost(") == 1
    assert source.count("only_compose_research_product_boundary(") == 1
    assert source.index("kernel.start()") < source.index("only_compose_research_product_boundary(")
    assert "admission=kernel" in source
    assert source.index("only_compose_research_product_boundary(") < source.index("create_research_app(")
    assert "workers=" not in source
    assert "--workers" not in source


def test_no_dispatch_failure_fallback_or_direct_mutation_call_exists() -> None:
    source = RUN_ROUTES.read_text(encoding="utf-8")
    assert "except OnlyUnsupportedProduct" not in source
    assert ".submit_research_run(" not in source
    assert ".request_research_run_cancellation(" not in source


def test_artifact_console_is_explicitly_read_only_and_not_a_product_control_plane() -> None:
    source = (API / "artifact_main.py").read_text(encoding="utf-8")
    assert "create_artifact_query_app" in source
    assert "create_research_app" not in source
    assert "OnlyAlphaKernelHost" not in source
    assert "OnlyResearchProductBoundary" not in source


def test_core_and_product_intents_remain_http_transport_neutral() -> None:
    forbidden = ("fastapi", "starlette", "onlyalpha_api")
    for path in (ROOT / "src/onlyalpha").rglob("*.py"):
        assert not any(name.startswith(forbidden) for name in _imports(path)), path
    product_source = (ROOT / "src/onlyalpha/application/product_boundary.py").read_text(encoding="utf-8")
    assert "BaseModel" not in product_source
    assert "Request" not in product_source
    assert "Response" not in product_source
