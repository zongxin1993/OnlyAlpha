from __future__ import annotations

import ast
from pathlib import Path

import pytest

from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelLifecycle, OnlyKernelState
from onlyalpha.runtime.trading.kernel import OnlyTradingKernel

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
KERNEL_ROOT = ROOT / "src/onlyalpha/kernel"


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return frozenset(result)


def test_product_kernel_boundary_is_minimal_and_transport_neutral() -> None:
    assert {path.name for path in KERNEL_ROOT.glob("*.py")} == {
        "__init__.py",
        "command.py",
        "host.py",
        "lifecycle.py",
        "query.py",
    }
    forbidden = ("fastapi", "starlette", "pydantic", "uvicorn", "onlyalpha_http_server")
    for path in KERNEL_ROOT.glob("*.py"):
        assert not any(name.startswith(forbidden) for name in _imports(path)), path


def test_product_kernel_does_not_import_domain_authorities_or_trading_kernel() -> None:
    forbidden = (
        "onlyalpha.engine",
        "onlyalpha.research",
        "onlyalpha.strategy",
        "onlyalpha.persistence",
        "onlyalpha.runtime",
    )
    for path in KERNEL_ROOT.glob("*.py"):
        assert not any(name.startswith(forbidden) for name in _imports(path)), path


def test_product_kernel_and_trading_semantic_kernel_are_distinct() -> None:
    assert OnlyAlphaKernelHost is not OnlyTradingKernel
    assert not issubclass(OnlyAlphaKernelHost, OnlyTradingKernel)
    assert not issubclass(OnlyTradingKernel, OnlyAlphaKernelHost)
    assert (ROOT / "src/onlyalpha/runtime/trading/kernel.py").is_file()


def test_lifecycle_has_no_public_arbitrary_state_writer() -> None:
    lifecycle = OnlyKernelLifecycle()
    assert lifecycle.state is OnlyKernelState.CREATED
    assert "state" not in vars(lifecycle)
    assert not hasattr(OnlyKernelLifecycle.state, "fset") or OnlyKernelLifecycle.state.fset is None


def test_api_startup_owns_host_and_only_read_only_schema_verification() -> None:
    source = (ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py").read_text(encoding="utf-8")
    assert "OnlyAlphaKernelHost(" in source
    assert "OnlyPostgresSchemaVerifier(" in source
    assert "OnlyPostgresMigrationAuthority" not in source
    assert ".migrate(" not in source
    assert "OnlyKernelResearchReadinessProjection(kernel, verification.evidence)" in source
    assert (
        "registry_check=lambda: _verify_product_registries(calculations, market_products, catalog, resources)" in source
    )
    assert source.index("kernel.start()") < source.index("uvicorn.run(")
    assert source.index("kernel = OnlyAlphaKernelHost(") < source.index("kernel.start()")
    app_source = (ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/app.py").read_text(encoding="utf-8")
    assert "readiness_probe: OnlyKernelResearchReadinessProjection" in app_source
    assert "readiness_probe: OnlyResearchServiceReadinessProbe" not in app_source
