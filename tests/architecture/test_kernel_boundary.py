from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelLifecycle, OnlyKernelState
from onlyalpha.runtime.trading.kernel import OnlyTradingKernel
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
KERNEL_ROOT = ROOT / "src/onlyalpha/kernel"


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
        assert not any(name.startswith(forbidden) for name in imported_modules_for_path(path, ROOT)), path


def test_product_kernel_does_not_import_domain_authorities_or_trading_kernel() -> None:
    forbidden = (
        "onlyalpha.engine",
        "onlyalpha.research",
        "onlyalpha.strategy",
        "onlyalpha.persistence",
        "onlyalpha.runtime",
    )
    for path in KERNEL_ROOT.glob("*.py"):
        assert not any(name.startswith(forbidden) for name in imported_modules_for_path(path, ROOT)), path


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
    native = ROOT / "packages/backend/src"
    source = "".join(((native / "main.rs").read_text(encoding="utf-8")).split())
    startup = "".join(((native / "bootstrap/workstation_startup.rs").read_text(encoding="utf-8")).split())
    storage = "".join(((native / "bootstrap/startup.rs").read_text(encoding="utf-8")).split())
    assert not (ROOT / "packages/backend/src/onlyalpha_http_server/main.py").exists()
    assert "Running::open(config,&shutdown)" in source
    assert source.index("Running::open(config,&shutdown)") < source.index("running.serve(")
    assert "inputs.verify(" in startup
    assert "letresolver=Resolver::new(" in startup
    assert startup.index("letresolver=Resolver::new(") < startup.index("AuthoritySession::acquire(")
    assert ".inspect(client,max_rows)" in storage
    assert "deployment::verify_binding(client,&self.namespace)" in storage
    for text in (source, startup, storage):
        assert "OnlyPostgresMigrationAuthority" not in text
        assert ".migrate(" not in text
