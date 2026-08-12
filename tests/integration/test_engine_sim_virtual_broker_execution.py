from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerFactory
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.application import OnlyEngineInspectionService
from onlyalpha.broker.execution import OnlyBrokerExecutionService
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.enums import OnlyOrderStatus, OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.sim.runtime import OnlySimRuntime
from onlyalpha.runtime.streaming.phase import OnlyStreamingPhase
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationState
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

pytestmark = pytest.mark.integration

_HELPER = Path("packages/provider/onlyalpha-plugin-miniqmt/tests/helpers/historical_worker.py").resolve()
_INITIAL_TIME = datetime(2026, 8, 4, 1, 36, 17, tzinfo=UTC)


class _FakeLiveXtData:
    def __init__(self) -> None:
        self.subscriptions: list[int] = []
        self.callbacks: list[Callable[[object], None]] = []

    def subscribe_quote(self, *args: object, **kwargs: object) -> int:
        del args
        self.subscriptions.append(1)
        self.callbacks.append(cast(Callable[[object], None], kwargs["callback"]))
        return 1

    def unsubscribe_quote(self, sequence: int) -> None:
        self.subscriptions.remove(sequence)

    def publish_bar(self, bar_end: datetime) -> None:
        row = {
            "time": int(bar_end.timestamp() * 1000),
            "open": "10.00",
            "high": "10.10",
            "low": "9.90",
            "close": "10.05",
            "volume": "100",
        }
        for callback in self.callbacks:
            callback({"000001.SZ": row})


def _config(tmp_path: Path) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_sim_acceptance.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["extensions"]["streaming"]["bootstrap_bars"] = 10
    payload["runtime"]["persistence"] = {
        "backend": "SQLITE",
        "path": "sim-runtime.sqlite3",
        "checkpoint": {"enabled": False},
    }
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True)
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def _engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine_id: str,
) -> tuple[OnlyEngine, _FakeLiveXtData, OnlyBacktestClock, Path]:
    xtdata = _FakeLiveXtData()
    clock = OnlyBacktestClock(_INITIAL_TIME)

    def create(self: OnlyMiniQmtDataSourceFactory, request: object) -> OnlyMiniQmtDataSource:
        del self
        return OnlyMiniQmtDataSource(request, request.plugin_config, xtdata)  # type: ignore[arg-type,attr-defined]

    monkeypatch.setattr(OnlyMiniQmtDataSourceFactory, "create", create)
    monkeypatch.setattr("onlyalpha.runtime.sim.factory.OnlyLiveClock", lambda: clock)
    monkeypatch.setattr(
        OnlyMiniQmtHistoricalIsolatedClient,
        "_default_command",
        staticmethod(
            lambda request_path: (
                sys.executable,
                str(_HELPER),
                "--request",
                str(request_path),
                "--behavior",
                "opening-boundary",
            )
        ),
    )
    user_data = tmp_path / "user_data"
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(engine_id), user_data))
    engine.add_cluster(_config(tmp_path))
    return engine, xtdata, clock, user_data


def _database(user_data: Path, engine_id: str, runtime: OnlySimRuntime) -> Path:
    return (
        OnlyUserDataLayout(user_data).runtime_state_root(
            OnlyEngineId(engine_id),
            OnlyRuntimeId(runtime.runtime_id),
        )
        / "sim-runtime.sqlite3"
    )


def _wait_until(condition: Callable[[], bool], message: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    pytest.fail(message)


def _publish_and_wait_received(
    runtime: OnlySimRuntime,
    xtdata: _FakeLiveXtData,
    clock: OnlyBacktestClock,
    minute: int,
) -> None:
    before = runtime.received_update_count
    boundary = datetime(2026, 8, 4, 1, minute, tzinfo=UTC)
    clock.advance_to(boundary)
    xtdata.publish_bar(boundary)
    _wait_until(
        lambda: runtime.received_update_count > before,
        f"SIM worker did not receive live Bar ending at minute {minute}",
    )


def _sqlite_transaction_state(database: Path) -> tuple[int, int, tuple[str, ...]]:
    with sqlite3.connect(database) as connection:
        count, ready = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(projection_ready), 0) FROM runtime_transactions"
        ).fetchone()
        kinds = tuple(
            row[0]
            for row in connection.execute(
                "SELECT operation_kind FROM runtime_transactions ORDER BY execution_sequence"
            ).fetchall()
        )
    return int(count), int(ready), kinds


def test_engine_sim_virtual_broker_executes_accepted_then_next_bar_trade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_id = "sim-virtual-e2e"
    engine, xtdata, clock, user_data = _engine(tmp_path, monkeypatch, engine_id=engine_id)
    validation = engine.validate()
    assert validation.valid
    assert validation.errors == ()

    engine.initialize()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    database = _database(user_data, engine_id, runtime)
    assert isinstance(runtime, OnlySimRuntime)
    assert runtime.runtime_type == "SIM"
    assert runtime.config.mode is OnlyRuntimeMode.SIM
    assert runtime.broker_gateway is not None
    assert isinstance(runtime.execution_service, OnlyBrokerExecutionService)
    assert runtime.inspection_run_id == f"sim-{runtime.runtime_id}"

    engine.start()
    stopped = False
    try:
        assert runtime.state is OnlyRuntimeState.RUNNING
        assert runtime.streaming_phase is OnlyStreamingPhase.LIVE
        assert runtime.historical_watermarks
        assert runtime.historical_processed_bar_count >= 10
        assert tuple(item.state for item in runtime.plugin_resource_snapshots) == (
            OnlyPluginLifecycleState.RUNNING,
            OnlyPluginLifecycleState.RUNNING,
        )
        assert runtime.order_snapshots == ()
        assert runtime.execution_transaction_query.records(OnlyRuntimeId(runtime.runtime_id)) == ()
        assert xtdata.subscriptions == [1]
        engine.wait(timeout=0.01)
        assert runtime.state is OnlyRuntimeState.RUNNING

        initial_account = runtime.account_manager.list_accounts()[0]
        initial_ledger = runtime.strategy_ledger_manager.list_ledgers()[0]

        _publish_and_wait_received(runtime, xtdata, clock, 37)
        assert runtime.order_snapshots == ()
        _publish_and_wait_received(runtime, xtdata, clock, 38)
        _wait_until(
            lambda: len(runtime.order_snapshots) == 1 and runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED,
            "Bar N order did not reach Broker Accepted projection",
        )

        after_bar_n = OnlyEngineInspectionService().capture(engine)[0]
        order_after_bar_n = runtime.order_snapshots[0]
        accepted_records = runtime.execution_transaction_query.records(OnlyRuntimeId(runtime.runtime_id))
        assert order_after_bar_n.venue_order_id is not None
        assert after_bar_n.live_order_intent_count >= 1
        assert after_bar_n.shadow_suppressed_count == 0
        assert after_bar_n.external_order_id_count == 1
        assert after_bar_n.fill_count == 0
        assert after_bar_n.position_count == 0
        assert after_bar_n.open_reservation_count == 1
        assert len(accepted_records) == 1
        assert accepted_records[0].operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED
        assert accepted_records[0].projection_ready
        assert runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 1

        _publish_and_wait_received(runtime, xtdata, clock, 39)
        _wait_until(
            lambda: (
                runtime.order_snapshots[0].status is OnlyOrderStatus.FILLED
                and runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 2
            ),
            "Bar N+1 did not finish the projected Virtual Broker Trade",
        )

        records = runtime.execution_transaction_query.records(OnlyRuntimeId(runtime.runtime_id))
        assert tuple(item.operation_kind for item in records) == (
            OnlyRuntimeOperationKind.ORDER_ACCEPTED,
            OnlyRuntimeOperationKind.TRADE_FILL,
        )
        assert records[0].execution_sequence < records[1].execution_sequence
        assert all(item.projection_ready for item in records)
        assert runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 2

        order = runtime.order_snapshots[0]
        positions = runtime.position_manager.snapshot_all()
        allocations = runtime.allocation_manager.snapshot_all()
        account = runtime.account_manager.list_accounts()[0]
        ledger = runtime.strategy_ledger_manager.list_ledgers()[0]
        risk_reservation = runtime.risk_service.reservations.snapshot_all()[0]
        account_reservation = runtime.account_reservation_manager.snapshots()[0]
        strategy_reservation = ledger.reservations[0]
        assert order.fill_count == 1
        assert len(positions) == 1
        assert positions[0].total_quantity.value == Decimal("1000")
        assert len(allocations) == 1
        assert allocations[0].total_quantity == positions[0].total_quantity
        assert allocations[0].key.cluster_id == engine.cluster_definitions[0].cluster_id
        assert account.cash.ledger_cash.amount < initial_account.cash.ledger_cash.amount
        assert account.cash.order_reserved_cash.amount == 0
        assert ledger.cash.ledger_cash.amount < initial_ledger.cash.ledger_cash.amount
        assert ledger.performance.trade_count == 1
        assert risk_reservation.state is OnlyRiskReservationState.CONSUMED
        assert account_reservation.state is OnlyAccountReservationState.CONSUMED
        assert strategy_reservation.state is OnlyStrategyCashReservationState.CONSUMED
        assert runtime.fee_application_ledger.records
        assert runtime.settlement_authority.records

        after_trade = OnlyEngineInspectionService().capture(engine)[0]
        assert after_trade.fill_count == 1
        assert after_trade.position_count == 1
        assert after_trade.fee_count > 0
        assert after_trade.settlement_count > 0
        assert _sqlite_transaction_state(database) == (
            2,
            2,
            ("ORDER_ACCEPTED", "TRADE_FILL"),
        )
    finally:
        engine.stop()
        stopped = True
    assert stopped
    assert not xtdata.subscriptions
    assert runtime.order_snapshots[0].status is OnlyOrderStatus.FILLED
    assert runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("1000")
    assert _sqlite_transaction_state(database) == (2, 2, ("ORDER_ACCEPTED", "TRADE_FILL"))
    assert tuple(item.state for item in runtime.plugin_resource_snapshots) == (
        OnlyPluginLifecycleState.STOPPED,
        OnlyPluginLifecycleState.STOPPED,
    )


def test_engine_sim_stop_is_not_a_broker_trading_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_id = "sim-stop-cutoff"
    engine, xtdata, clock, user_data = _engine(tmp_path, monkeypatch, engine_id=engine_id)
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    database = _database(user_data, engine_id, runtime)
    bootstrap_broker_results = len(runtime.broker_results)

    _publish_and_wait_received(runtime, xtdata, clock, 37)
    _publish_and_wait_received(runtime, xtdata, clock, 38)
    _wait_until(
        lambda: len(runtime.order_snapshots) == 1 and runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED,
        "SIM stop fixture did not reach Accepted",
    )
    _wait_until(
        lambda: (
            len(runtime.broker_results) == bootstrap_broker_results + 1
            and runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 1
        ),
        "SIM stop fixture did not finish Accepted processing",
    )
    before_results = len(runtime.broker_results)
    assert _sqlite_transaction_state(database) == (1, 1, ("ORDER_ACCEPTED",))

    engine.stop()

    assert runtime.state is OnlyRuntimeState.CLOSED
    assert runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED
    assert runtime.order_snapshots[0].fill_count == 0
    assert runtime.position_manager.snapshot_all() == ()
    assert len(runtime.broker_results) == before_results
    assert _sqlite_transaction_state(database) == (1, 1, ("ORDER_ACCEPTED",))
    assert not xtdata.subscriptions


def test_engine_sim_requires_a_deterministic_broker_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, _, _ = _engine(tmp_path, monkeypatch, engine_id="sim-driver-required")
    original_create = OnlyVirtualBrokerFactory.create
    created_components: list[OnlyBrokerComponent] = []

    def create_without_driver(
        self: OnlyVirtualBrokerFactory,
        request: OnlyBrokerCreateRequest,
    ) -> OnlyBrokerComponent:
        component = original_create(self, request)
        created_components.append(component)
        return OnlyBrokerComponent(component.gateway, component.resource)

    monkeypatch.setattr(OnlyVirtualBrokerFactory, "create", create_without_driver)

    with pytest.raises(RuntimeError, match="SIM_DETERMINISTIC_BROKER_DRIVER_REQUIRED"):
        engine.initialize()

    assert engine.runtimes == ()
    assert xtdata.subscriptions == []
    assert len(created_components) == 1
    assert created_components[0].resource.state is OnlyPluginLifecycleState.STOPPED
