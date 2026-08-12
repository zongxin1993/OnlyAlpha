from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
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
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.domain.enums import OnlyOrderStatus, OnlyRuntimeMode
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
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


def _publish_closed_gap_trigger(runtime: OnlySimRuntime, clock: OnlyBacktestClock, minute: int) -> None:
    bar_type = next(iter(runtime.historical_watermarks)).bar_type
    template = runtime._latest_bars[(str(bar_type.instrument_id), bar_type)]  # type: ignore[attr-defined]
    end = datetime(2026, 8, 4, 1, minute, tzinfo=UTC)
    bar = replace(
        template,
        bar_start=end.replace(minute=minute - 1),
        bar_end=end,
        ts_event=end,
        ts_init=end,
        is_closed=True,
    )
    stamp = OnlyTimestamp.from_datetime(end)
    runtime._services.market_data_inbound.put(  # type: ignore[attr-defined]
        OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"fixture-live-gap-{minute}"),
            OnlyRuntimeId(runtime.runtime_id),
            runtime._driver.source.source_id,  # type: ignore[attr-defined,union-attr]
            OnlyDataSequence(10_000 + minute),
            runtime._streaming_data_version,  # type: ignore[attr-defined]
            bar.instrument_id,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            stamp,
            stamp,
        )
    )
    clock.advance_to(end)


def _recovery_stream(
    runtime: OnlySimRuntime,
    request: OnlyHistoricalBarRequest,
    *,
    omit_minute: int | None = None,
) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
    bar_type = next(iter(runtime.historical_watermarks)).bar_type
    template = runtime._latest_bars[(str(bar_type.instrument_id), bar_type)]  # type: ignore[attr-defined]
    records: list[OnlyMarketDataInboundUpdate] = []
    first_end = request.data_range.start_time.replace(second=0, microsecond=0)
    if first_end <= request.data_range.start_time:
        first_end = first_end.replace(minute=first_end.minute + 1)
    end = first_end
    sequence = 0
    while end < request.data_range.end_time:
        minute = end.minute
        if minute == omit_minute:
            end = end.replace(minute=end.minute + 1)
            continue
        sequence += 1
        bar = replace(
            template,
            bar_start=end.replace(minute=minute - 1),
            bar_end=end,
            ts_event=end,
            ts_init=end,
            is_closed=True,
        )
        stamp = OnlyTimestamp.from_datetime(end)
        records.append(
            OnlyMarketDataInboundUpdate(
                OnlyMarketDataUpdateId(f"fixture-recovery-{minute}"),
                OnlyRuntimeId(runtime.runtime_id),
                runtime._driver.source.source_id,  # type: ignore[attr-defined,union-attr]
                OnlyDataSequence(sequence),
                runtime._streaming_data_version,  # type: ignore[attr-defined]
                bar.instrument_id,
                OnlyMarketDataType.BAR,
                OnlyBarUpdate(bar),
                stamp,
                stamp,
            )
        )
        end = end.replace(minute=end.minute + 1)
    return OnlyHistoricalDataStream(tuple(records), request.batch_size)


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
        processing_count = len(runtime.processing_results)
        closed_bar_count = runtime.closed_external_bar_count

        _publish_and_wait_received(runtime, xtdata, clock, 37)
        assert runtime.order_snapshots == ()
        _publish_and_wait_received(runtime, xtdata, clock, 38)
        _wait_until(
            lambda: (
                len(runtime.order_snapshots) == 1
                and runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED
                and runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 1
            ),
            "Bar N order did not reach Broker Accepted Projection Ready",
        )
        _wait_until(
            lambda: len(runtime.processing_results) == processing_count + 1,
            "live Bar processing result was not committed exactly once",
        )
        assert len(runtime.processing_results) == processing_count + 1
        assert runtime.closed_external_bar_count == closed_bar_count + 1

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


def test_engine_sim_gap_recovers_history_then_reconciles_trigger_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_id = "sim-gap-recovery"
    engine, xtdata, clock, user_data = _engine(tmp_path, monkeypatch, engine_id=engine_id)
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    runtime._stale_after_seconds = 600  # type: ignore[attr-defined]
    database = _database(user_data, engine_id, runtime)
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    monkeypatch.setattr(source, "load_bars", lambda request: _recovery_stream(runtime, request))
    try:
        _publish_and_wait_received(runtime, xtdata, clock, 37)
        _publish_and_wait_received(runtime, xtdata, clock, 38)
        _wait_until(
            lambda: (
                len(runtime.order_snapshots) == 1
                and runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED
                and runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 1
            ),
            "pre-gap Order did not reach Accepted Projection Ready",
        )
        _wait_until(
            lambda: (
                runtime.health().last_closed_bar_end
                == OnlyTimestamp.from_datetime(datetime(2026, 8, 4, 1, 37, tzinfo=UTC))
            ),
            "pre-gap confirmed frontier did not reach 01:37",
        )
        _wait_until(
            lambda: any(
                result.status is OnlyMarketDataProcessingStatus.APPLIED and str(result.update_id) == "miniqmt-live-13"
                for result in runtime.processing_results
            ),
            "pre-gap Worker callback did not complete",
        )
        assert _sqlite_transaction_state(database) == (1, 1, ("ORDER_ACCEPTED",))
        before = runtime.streaming_phase_snapshot
        _publish_closed_gap_trigger(runtime, clock, 42)
        assert (
            runtime.wait_for_streaming_phase(
                OnlyStreamingPhase.LIVE,
                after_revision=before.revision,
                timeout=10,
            )
            is not None
        )
        assert runtime.recovery_generation == 1

        audit = runtime.market_data_audit_store.records()
        trigger_statuses = tuple(item.status for item in audit if str(item.update_id) == "fixture-live-gap-42")
        assert trigger_statuses == (
            OnlyMarketDataProcessingStatus.GAP_DETECTED,
            OnlyMarketDataProcessingStatus.APPLIED,
        )
        recovery_statuses = tuple(
            item.status for item in audit if str(item.update_id).startswith(f"recovery-{runtime.runtime_id}-1-")
        )
        assert recovery_statuses == (OnlyMarketDataProcessingStatus.APPLIED,) * 4
        audit_ids = tuple(str(item.update_id) for item in audit)
        assert sum(item.startswith("fixture-recovery-") for item in audit_ids) == 0
        assert sum(item.startswith(f"recovery-{runtime.runtime_id}-1-") for item in audit_ids) == 4
        assert runtime.recovery_failure is None
        assert runtime.recovery_plan is None
        _wait_until(
            lambda: runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 2,
            "recovered Bar Trade did not reach Projection Ready",
        )
        assert len(runtime.order_snapshots) == 1
        assert runtime.order_snapshots[0].status is OnlyOrderStatus.FILLED
        assert runtime.order_snapshots[0].fill_count == 1
        assert len(runtime.position_manager.snapshot_all()) == 1
        assert len(runtime.allocation_manager.snapshot_all()) == 1
        assert runtime.ready_execution_query.ready_count(OnlyRuntimeId(runtime.runtime_id)) == 2
        assert _sqlite_transaction_state(database) == (2, 2, ("ORDER_ACCEPTED", "TRADE_FILL"))
    finally:
        engine.stop()


def test_engine_sim_incomplete_gap_recovery_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, clock, _ = _engine(tmp_path, monkeypatch, engine_id="sim-gap-incomplete")
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    runtime._stale_after_seconds = 600  # type: ignore[attr-defined]
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        source,
        "load_bars",
        lambda request: _recovery_stream(runtime, request, omit_minute=40),
    )
    try:
        _publish_and_wait_received(runtime, xtdata, clock, 37)
        _publish_and_wait_received(runtime, xtdata, clock, 38)
        _wait_until(
            lambda: (
                runtime.health().last_closed_bar_end
                == OnlyTimestamp.from_datetime(datetime(2026, 8, 4, 1, 37, tzinfo=UTC))
            ),
            "pre-gap confirmed frontier did not reach 01:37",
        )
        _wait_until(
            lambda: any(str(result.update_id) == "miniqmt-live-13" for result in runtime.processing_results),
            "pre-gap Worker callback did not complete",
        )
        _publish_closed_gap_trigger(runtime, clock, 42)
        _wait_until(
            lambda: runtime.streaming_phase is OnlyStreamingPhase.FAILED,
            "incomplete historical coverage did not fail closed",
        )

        assert runtime.state is OnlyRuntimeState.FAILED
        assert runtime.recovery_failure == "historical recovery coverage is incomplete"
        trigger_statuses = tuple(
            item.status
            for item in runtime.market_data_audit_store.records()
            if str(item.update_id) == "fixture-live-gap-42"
        )
        assert trigger_statuses == (OnlyMarketDataProcessingStatus.GAP_DETECTED,)
        assert not any(
            str(item.update_id).startswith(f"recovery-{runtime.runtime_id}-")
            for item in runtime.market_data_audit_store.records()
        )
    finally:
        engine.stop()


def test_engine_sim_stop_during_blocked_recovery_discards_late_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, clock, user_data = _engine(tmp_path, monkeypatch, engine_id="sim-stop-recovery")
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    runtime._stale_after_seconds = 600  # type: ignore[attr-defined]
    database = _database(user_data, "sim-stop-recovery", runtime)
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    entered = Event()
    release = Event()

    def blocked(request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        entered.set()
        assert release.wait(3)
        return _recovery_stream(runtime, request)

    monkeypatch.setattr(source, "load_bars", blocked)
    _publish_and_wait_received(runtime, xtdata, clock, 37)
    _publish_and_wait_received(runtime, xtdata, clock, 38)
    _wait_until(
        lambda: (
            runtime.health().last_closed_bar_end == OnlyTimestamp.from_datetime(datetime(2026, 8, 4, 1, 37, tzinfo=UTC))
        ),
        "pre-gap confirmed frontier did not reach 01:37",
    )
    _wait_until(
        lambda: any(str(result.update_id) == "miniqmt-live-13" for result in runtime.processing_results),
        "pre-gap Worker callback did not complete",
    )
    before = runtime.streaming_phase_snapshot
    _publish_closed_gap_trigger(runtime, clock, 42)
    assert entered.wait(3)
    before_results = len(runtime.processing_results)
    before_transactions = _sqlite_transaction_state(database)

    stop_failure: list[BaseException] = []

    def stop_engine() -> None:
        try:
            engine.stop()
        except BaseException as exc:
            stop_failure.append(exc)

    stopper = Thread(target=stop_engine)
    stopper.start()
    assert (
        runtime.wait_for_streaming_phase(
            OnlyStreamingPhase.STOPPING,
            after_revision=before.revision,
            timeout=10,
        )
        is not None
    )
    release.set()
    stopper.join(timeout=3)

    assert not stopper.is_alive()
    assert stop_failure == []
    assert runtime.streaming_phase is OnlyStreamingPhase.STOPPED
    assert len(runtime.processing_results) == before_results
    assert _sqlite_transaction_state(database) == before_transactions


def test_engine_sim_stop_during_buffered_suffix_catch_up_prevents_late_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, clock, _ = _engine(tmp_path, monkeypatch, engine_id="sim-stop-catch-up")
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    runtime._stale_after_seconds = 600  # type: ignore[attr-defined]
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    entered = Event()
    release = Event()
    original = runtime._process_buffered_updates  # type: ignore[attr-defined]

    def blocked(updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        entered.set()
        assert release.wait(10)
        original(updates)

    monkeypatch.setattr(source, "load_bars", lambda request: _recovery_stream(runtime, request))
    monkeypatch.setattr(runtime, "_process_buffered_updates", blocked)
    _publish_and_wait_received(runtime, xtdata, clock, 37)
    _publish_and_wait_received(runtime, xtdata, clock, 38)
    _wait_until(
        lambda: any(str(result.update_id) == "miniqmt-live-13" for result in runtime.processing_results),
        "pre-gap Worker callback did not complete",
    )
    _publish_closed_gap_trigger(runtime, clock, 42)
    assert entered.wait(10)
    before_results = len(runtime.processing_results)

    stopper = Thread(target=lambda: engine.stop())
    stopper.start()
    assert runtime.wait_for_streaming_phase(OnlyStreamingPhase.STOPPING, timeout=10) is not None
    release.set()
    stopper.join(10)

    assert not stopper.is_alive()
    assert runtime.streaming_phase is OnlyStreamingPhase.STOPPED
    assert len(runtime.processing_results) == before_results


def test_engine_sim_disconnect_reconnects_repairs_history_then_restores_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, clock, _ = _engine(tmp_path, monkeypatch, engine_id="sim-reconnect")
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    monkeypatch.setattr(source, "load_bars", lambda request: _recovery_stream(runtime, request))
    try:
        _publish_and_wait_received(runtime, xtdata, clock, 37)
        _publish_and_wait_received(runtime, xtdata, clock, 38)
        _wait_until(
            lambda: any(str(result.update_id) == "miniqmt-live-13" for result in runtime.processing_results),
            "pre-disconnect Worker callback did not complete",
        )
        before = runtime.streaming_phase_snapshot
        source.disconnect()
        clock.advance_to(datetime(2026, 8, 4, 1, 42, tzinfo=UTC))

        assert (
            runtime.wait_for_streaming_phase(
                OnlyStreamingPhase.LIVE,
                after_revision=before.revision,
                timeout=10,
            )
            is not None
        )
        assert runtime.recovery_generation == 1

        assert runtime.recovery_failure is None
        assert runtime.subscription_active
        assert runtime.health().source_connected
        assert len(xtdata.subscriptions) == 1
        assert (
            tuple(
                item.status
                for item in runtime.market_data_audit_store.records()
                if str(item.update_id).startswith(f"recovery-{runtime.runtime_id}-1-")
            )
            == (OnlyMarketDataProcessingStatus.APPLIED,) * 5
        )
    finally:
        engine.stop()


def test_engine_sim_reconnect_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, xtdata, clock, _ = _engine(tmp_path, monkeypatch, engine_id="sim-reconnect-failure")
    engine.initialize()
    engine.start()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    source = cast(OnlyMiniQmtDataSource, runtime._driver.source)  # type: ignore[attr-defined]
    source.disconnect()
    monkeypatch.setattr(source, "connect", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    clock.advance_to(datetime(2026, 8, 4, 1, 42, tzinfo=UTC))
    try:
        _wait_until(
            lambda: runtime.streaming_phase is OnlyStreamingPhase.FAILED,
            "reconnect failure did not fail closed",
        )
        assert runtime.state is OnlyRuntimeState.FAILED
        assert runtime.recovery_failure == "streaming DataSource reconnect failed"
        assert runtime.recovery_generation == 0
    finally:
        engine.stop()


def test_engine_sim_streaming_phase_permission_matrix_blocks_retroactive_orders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _, _, _ = _engine(tmp_path, monkeypatch, engine_id="sim-phase-permission")
    engine.initialize()
    runtime = cast(OnlySimRuntime, engine.runtimes[0])
    request = cast(OnlyOrderRequest, object())
    try:
        expected = {
            OnlyStreamingPhase.BOOTSTRAP: "ORDER_INTENT_SUPPRESSED_DURING_BOOTSTRAP",
            OnlyStreamingPhase.CATCH_UP: "ORDER_INTENT_SUPPRESSED_DURING_CATCH_UP",
            OnlyStreamingPhase.DEGRADED: "ORDER_INTENT_SUPPRESSED_DURING_DEGRADED",
            OnlyStreamingPhase.RECOVERING: "ORDER_INTENT_SUPPRESSED_DURING_RECOVERY",
        }
        for phase, error in expected.items():
            runtime._transition_streaming_phase(phase)  # type: ignore[attr-defined]
            result = runtime._intercept_order_submit(request)  # type: ignore[attr-defined]
            assert result is not None
            assert not result.created
            assert not result.submitted
            assert result.error == error
        runtime._transition_streaming_phase(OnlyStreamingPhase.LIVE)  # type: ignore[attr-defined]
        assert runtime._intercept_order_submit(request) is None  # type: ignore[attr-defined]
    finally:
        engine.stop()


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
