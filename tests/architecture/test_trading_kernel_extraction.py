from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntime
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime
from onlyalpha.runtime.trading.config import OnlyTradingKernelConfig

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).parents[2] / "src" / "onlyalpha" / "runtime"


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return frozenset(names)


def test_streaming_package_has_no_backtest_dependency() -> None:
    imports = {imported for path in (_ROOT / "streaming").glob("*.py") for imported in _imports(path)}
    assert not {name for name in imports if name.startswith("onlyalpha.runtime.backtest")}
    assert OnlyBacktestRuntime not in inspect.getmro(OnlyStreamingRuntime)


def test_trading_kernel_has_no_concrete_runtime_or_mode_dependency() -> None:
    forbidden_packages = (
        "onlyalpha.runtime.backtest",
        "onlyalpha.runtime.paper",
        "onlyalpha.runtime.streaming",
        "onlyalpha.runtime.live",
        "onlyalpha.runtime.sim",
    )
    forbidden_names = {"OnlyRuntimeMode", "BACKTEST", "PAPER", "SIM", "LIVE"}
    for path in (_ROOT / "trading").glob("*.py"):
        assert not any(name.startswith(forbidden_packages) for name in _imports(path)), path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        production_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert forbidden_names.isdisjoint(production_names), path


def test_kernel_config_is_runtime_neutral() -> None:
    assert "mode" not in OnlyTradingKernelConfig.__dataclass_fields__


def test_shared_position_authority_policy_is_runtime_neutral() -> None:
    source = (_ROOT.parent / "position" / "authority.py").read_text(encoding="utf-8")
    assert "OnlyRuntimeMode" not in source
    assert "runtime_mode" not in source


def test_base_runtime_does_not_construct_trading_authorities() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(OnlyRuntime.__init__)))
    constructed = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not constructed.intersection(
        {
            "OnlyPositionManager",
            "OnlyPositionAllocationManager",
            "OnlyPositionReservationManager",
            "OnlyAccountManager",
            "OnlyAccountReservationManager",
            "OnlyStrategyLedgerManager",
            "OnlySettlementAuthority",
            "OnlyMarginManager",
            "OnlyFeeApplicationLedger",
        }
    )


def test_streaming_driver_does_not_import_trading_authorities() -> None:
    imports = _imports(_ROOT / "streaming" / "driver.py")
    forbidden = ("onlyalpha.account", "onlyalpha.position", "onlyalpha.risk", "onlyalpha.transaction")
    assert not any(name.startswith(forbidden) for name in imports)
