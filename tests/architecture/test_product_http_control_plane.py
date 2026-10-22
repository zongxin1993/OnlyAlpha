from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server"
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


def test_canonical_run_http_is_explicitly_deferred_without_direct_execution() -> None:
    native = json.loads((ROOT / "contracts/product-api/v2/openapi.json").read_text())
    operations = [
        operation
        for path, methods in native["paths"].items()
        if path.startswith("/api/v2/research/runs")
        for operation in methods.values()
    ]
    assert operations
    assert all(set(operation["responses"]) == {"501"} for operation in operations)
    source = (ROOT / "packages/onlyalpha-http-server/rust/host.rs").read_text()
    assert "OnlyResearchCommandService" not in source
    assert "OnlyResearchRunQueryService" not in source


def test_product_app_cannot_receive_legacy_direct_run_services() -> None:
    assert not APP.exists()
    source = (ROOT / "packages/onlyalpha-http-server/rust/routes.rs").read_text()
    assert "State<Arc<Host>>" in source
    assert "OnlyResearchCommandService" not in source
    assert "OnlyResearchRunQueryService" not in source


def test_one_main_composition_uses_same_started_host_and_forbids_multi_worker() -> None:
    assert not MAIN.exists()
    source = "".join(((ROOT / "packages/onlyalpha-http-server/rust/main.rs").read_text(encoding="utf-8")).split())
    startup = "".join(
        ((ROOT / "packages/onlyalpha-http-server/rust/workstation_startup.rs").read_text(encoding="utf-8")).split()
    )
    assert source.count("Running::open(config,&shutdown)") == 1
    assert source.index("Running::open(config,&shutdown)") < source.index("running.serve(")
    assert startup.count("AuthoritySession::acquire(") == 1
    assert 'flavor="current_thread"' in source
    assert "OnlyEngine(" not in source + startup
    assert "--workers" not in source
    assert "uvicorn" not in source + startup


def test_no_dispatch_failure_fallback_or_direct_mutation_call_exists() -> None:
    source = "".join((ROOT / "packages/onlyalpha-http-server/rust/host.rs").read_text().split())
    deferred = source.index("Some(crate::routes::Operation::Deferred)")
    implemented = source.index("Some(crate::routes::Operation::Implemented)", deferred)
    assert '"PRODUCT_CAPABILITY_NOT_IMPLEMENTED"' in source[deferred:implemented]
    assert "returnErr(" in source[deferred:implemented]
    assert ".submit_research_run(" not in source
    assert ".request_research_run_cancellation(" not in source


def test_standalone_artifact_console_is_no_longer_a_product_surface() -> None:
    assert not (API / "artifact_main.py").exists()
    assert not APP.exists()


def test_core_and_product_intents_remain_http_transport_neutral() -> None:
    forbidden = ("fastapi", "starlette", "onlyalpha_http_server")
    for path in (ROOT / "src/onlyalpha").rglob("*.py"):
        assert not any(name.startswith(forbidden) for name in _imports(path)), path
    product_source = (ROOT / "src/onlyalpha/application/product_boundary.py").read_text(encoding="utf-8")
    assert "BaseModel" not in product_source
    assert "Request" not in product_source
    assert "Response" not in product_source
