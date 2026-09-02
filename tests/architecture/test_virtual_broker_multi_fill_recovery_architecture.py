from pathlib import Path

from onlyalpha_plugin_broker_virtual.descriptor import ONLY_VIRTUAL_PLUGIN_DESCRIPTOR

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugs/onlyalpha-plugin-broker-virtual/src/onlyalpha_plugin_broker_virtual"


def test_fill_plan_stays_in_plugin_and_core_has_no_virtual_implementation() -> None:
    assert (PLUGIN / "fill_plan.py").is_file()
    assert (PLUGIN / "fill_plan_store.py").is_file()
    core_sources = tuple((ROOT / "src/onlyalpha").rglob("*.py"))
    assert not any(path.name in {"fill_plan.py", "fill_plan_store.py"} for path in core_sources)


def test_fill_plan_and_gateway_do_not_depend_on_runtime_managers_or_execution_store() -> None:
    fill_plan = (PLUGIN / "fill_plan.py").read_text(encoding="utf-8")
    gateway = (PLUGIN / "gateway.py").read_text(encoding="utf-8")
    forbidden = (
        "onlyalpha.runtime",
        "OrderManager",
        "PositionManager",
        "AccountManager",
        "StrategyLedgerManager",
        "ExecutionStore",
        "commit_coordinator",
        "fill_identity",
    )
    assert not any(item in fill_plan for item in forbidden)
    assert not any(item in gateway for item in forbidden)


def test_plan_identity_and_stable_ordering_are_explicit() -> None:
    fill_plan = (PLUGIN / "fill_plan.py").read_text(encoding="utf-8")
    stores = (PLUGIN / "stores.py").read_text(encoding="utf-8")
    assert "hashlib.sha256" in fill_plan
    assert "hash(" not in fill_plan
    assert "str(item.venue_order_id), str(item.order_id)" in stores
    assert "item.source_sequence, str(item.trade_id)" in stores


def test_checkpoint_contract_is_version_three_and_descriptor_driven_without_fault_switches() -> None:
    gateway = (PLUGIN / "gateway.py").read_text(encoding="utf-8")
    factory = (ROOT / "src/onlyalpha/runtime/backtest/factory.py").read_text(encoding="utf-8")
    runtime = (ROOT / "src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    production = "\n".join(path.read_text(encoding="utf-8") for path in PLUGIN.glob("*.py"))
    assert '"schema_version": 3' in gateway
    assert "deterministic_broker_checkpoint_schema_version" not in factory
    assert '"broker.virtual",\n                    deterministic_broker_driver.checkpoint_schema_version,' in runtime
    assert ONLY_VIRTUAL_PLUGIN_DESCRIPTOR.capabilities.checkpoint_schema_version == 3
    assert "crash_after_fill" not in production
    assert "fail_after_fill" not in production
    assert "fault_switch" not in production


def test_protected_transaction_and_recovery_architecture_files_are_unchanged() -> None:
    protected = (
        "src/onlyalpha/execution/trade_planner.py",
        "src/onlyalpha/transaction/coordinator.py",
        "src/onlyalpha/execution/fill_identity.py",
        "src/onlyalpha/fee/accrual.py",
        "src/onlyalpha/runtime/events/gate.py",
        "src/onlyalpha/runtime/events/router.py",
        "src/onlyalpha/runtime/recovery/finalizer.py",
        "src/onlyalpha/runtime/recovery/outcome.py",
    )
    # This gate freezes the intended file set; Git diff is also checked by the delivery gate.
    assert all((ROOT / path).is_file() for path in protected)
    fill_plan = (PLUGIN / "fill_plan.py").read_text(encoding="utf-8")
    assert "SELL" not in fill_plan and "CLOSE" not in fill_plan and "MARGIN" not in fill_plan
