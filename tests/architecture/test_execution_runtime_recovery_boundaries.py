import ast
from pathlib import Path
from typing import get_type_hints

from onlyalpha.execution import OnlyExecutionRecoveryService
from onlyalpha.runtime.runtime import OnlyRuntimeServices


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }


def test_runtime_services_owns_recovery_and_initialize_start_have_strict_order() -> None:
    hints = get_type_hints(OnlyRuntimeServices)
    assert hints["execution_recovery_service"] is OnlyExecutionRecoveryService
    source = Path("src/onlyalpha/runtime/runtime.py").read_text(encoding="utf-8")
    initialize = source[source.index("    def initialize(self)") : source.index("    def start(self)")]
    start = source[source.index("    def start(self)") : source.index("    def pause(self)")]
    assert initialize.index("OnlyRuntimeState.RECOVERING") < initialize.index("_recover_runtime()")
    assert initialize.index("_recover_runtime()") < initialize.index("OnlyRuntimeState.READY")
    assert start.index("_drain_execution_outbox") < start.index("cluster_manager.start_all")
    assert "except OnlyRuntimeRecoveryError" in initialize
    assert "OnlyRuntimeState.FAILED" in initialize


def test_recovery_and_projection_dependencies_do_not_cross_runtime_manager_or_planner_boundaries() -> None:
    recovery = _imports("src/onlyalpha/transaction/recovery.py")
    coordinator = _imports("src/onlyalpha/transaction/coordinator.py")
    targets = _imports("src/onlyalpha/execution/projection_targets.py")
    assert not any(name.endswith(".manager") or ".runtime" in name for name in recovery)
    assert not any("planner" in name for name in recovery)
    assert not any(".runtime" in name for name in coordinator)
    assert not any(name.endswith("transaction_store") for name in targets)


def test_production_has_no_recovery_fault_switch_or_persistent_applied_ledger() -> None:
    production = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    applied = Path("src/onlyalpha/transaction/applied_projection.py").read_text(encoding="utf-8")
    assert "fail_after_position" not in production
    assert "fail_before" not in production
    assert "OnlySqliteAppliedProjectionLedger" not in production
    assert "sqlite" not in applied.lower()
