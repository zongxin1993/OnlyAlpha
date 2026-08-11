from __future__ import annotations

import ast
from pathlib import Path

import pytest

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.context import OnlyRuntimeContext
from onlyalpha.runtime.runtime import OnlyRuntime, OnlyRuntimeAssemblyConfig
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime

pytestmark = pytest.mark.architecture

_SOURCE_ROOT = Path(__file__).parents[2] / "src" / "onlyalpha"
_RUNTIME_ROOT = _SOURCE_ROOT / "runtime"
_ECONOMIC_PACKAGES = (
    "fee",
    "market",
    "position",
    "risk",
    "order",
    "execution",
    "settlement",
    "account",
    "strategy_ledger",
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _references_runtime_mode(path: Path) -> bool:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Name) and node.id == "OnlyRuntimeMode":
            return True
        if isinstance(node, ast.ImportFrom) and any(alias.name == "OnlyRuntimeMode" for alias in node.names):
            return True
    return False


def _is_config_mode_access(node: ast.AST) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr != "mode":
        return False
    owner = node.value
    return (isinstance(owner, ast.Attribute) and owner.attr == "config") or (
        isinstance(owner, ast.Name) and owner.id in {"config", "runtime_config"}
    )


def test_strategy_context_exposes_no_runtime_product_identity() -> None:
    fields = OnlyRuntimeContext.__dataclass_fields__
    assert {"mode", "runtime_mode", "runtime_type"}.isdisjoint(fields)
    for alias in ("is_backtest", "is_live", "is_sim", "is_paper"):
        assert not hasattr(OnlyRuntimeContext, alias)
    assert not _references_runtime_mode(_RUNTIME_ROOT / "context.py")


def test_trading_facade_does_not_read_runtime_product_identity() -> None:
    path = _RUNTIME_ROOT / "trading_facade.py"
    tree = _tree(path)
    assert not _references_runtime_mode(path)
    assert not any(_is_config_mode_access(node) for node in ast.walk(tree))


def test_trading_economic_packages_do_not_reference_runtime_mode() -> None:
    paths = [path for package in _ECONOMIC_PACKAGES for path in (_SOURCE_ROOT / package).rglob("*.py")]
    paths.extend((_RUNTIME_ROOT / "trading").rglob("*.py"))
    offenders = [path.relative_to(_SOURCE_ROOT) for path in paths if _references_runtime_mode(path)]
    assert offenders == []


def test_runtime_assembly_and_concrete_runtimes_retain_product_identity() -> None:
    assert "mode" in OnlyRuntimeAssemblyConfig.__dataclass_fields__
    assert OnlyBacktestRuntime._supported_modes == frozenset({OnlyRuntimeMode.BACKTEST})
    assert OnlyStreamingRuntime._supported_modes == frozenset({OnlyRuntimeMode.PAPER, OnlyRuntimeMode.LIVE})


def test_operational_runtime_guard_accepts_supported_product_and_rejects_wrong_product() -> None:
    accepted = OnlyBacktestRuntime.__new__(OnlyBacktestRuntime)
    OnlyRuntime.__init__(
        accepted,
        OnlyRuntimeAssemblyConfig("engine", "accepted", OnlyRuntimeMode.BACKTEST),
    )

    rejected = OnlyBacktestRuntime.__new__(OnlyBacktestRuntime)
    with pytest.raises(ValueError, match="does not support PAPER mode"):
        OnlyRuntime.__init__(
            rejected,
            OnlyRuntimeAssemblyConfig("engine", "rejected", OnlyRuntimeMode.PAPER),
        )

    streaming = OnlyStreamingRuntime.__new__(OnlyStreamingRuntime)
    OnlyRuntime.__init__(
        streaming,
        OnlyRuntimeAssemblyConfig("engine", "streaming", OnlyRuntimeMode.PAPER),
    )

    wrong_streaming = OnlyStreamingRuntime.__new__(OnlyStreamingRuntime)
    with pytest.raises(ValueError, match="does not support BACKTEST mode"):
        OnlyRuntime.__init__(
            wrong_streaming,
            OnlyRuntimeAssemblyConfig("engine", "wrong-streaming", OnlyRuntimeMode.BACKTEST),
        )
