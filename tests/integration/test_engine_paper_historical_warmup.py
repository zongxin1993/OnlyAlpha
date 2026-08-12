from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
import yaml
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.application import OnlyEngineInspectionService
from onlyalpha.cli import main
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
)
from onlyalpha.observation import OnlyObservationSource
from onlyalpha.plugin.errors import OnlyPluginLifecycleError
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.streaming.phase import OnlyStreamingPhase

pytestmark = pytest.mark.integration

_HELPER = Path("packages/provider/onlyalpha-plugin-miniqmt/tests/helpers/historical_worker.py").resolve()


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
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_paper_macd.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["extensions"]["streaming"].update(
        {
            "bootstrap_bars": 10,
            "historical_compatibility_profile": "miniqmt-history-v2",
            "historical_timeout_seconds": 5,
        }
    )
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True)
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def _acceptance_config(tmp_path: Path) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_paper_acceptance.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["extensions"]["streaming"]["bootstrap_bars"] = 10
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True)
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def _write_cli_config(tmp_path: Path, config: OnlyClusterRunConfig) -> Path:
    path = tmp_path / "miniqmt_paper_test.yaml"
    path.write_text(yaml.safe_dump(dict(config.normalized_payload), sort_keys=False), encoding="utf-8")
    return path


def _patch_source_factory(
    monkeypatch: pytest.MonkeyPatch,
    xtdata: _FakeLiveXtData,
    now: datetime = datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
) -> None:
    def create(self: OnlyMiniQmtDataSourceFactory, request: object) -> OnlyMiniQmtDataSource:
        del self
        config = request.plugin_config  # type: ignore[attr-defined]
        return OnlyMiniQmtDataSource(request, config, xtdata)  # type: ignore[arg-type]

    monkeypatch.setattr(OnlyMiniQmtDataSourceFactory, "create", create)
    monkeypatch.setattr(
        "onlyalpha.runtime.paper.factory.OnlyLiveClock",
        lambda: OnlyBacktestClock(now),
    )


@pytest.mark.parametrize(
    "now",
    (
        datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        datetime(2026, 8, 3, 4, 44, tzinfo=UTC),
        datetime(2026, 8, 3, 8, 0, tzinfo=UTC),
        datetime(2026, 8, 8, 2, 0, tzinfo=UTC),
    ),
    ids=("pre-open", "open", "break", "post-close", "closed-day"),
)
def test_paper_factory_assembles_at_any_market_session_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, now: datetime
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata, now)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(f"paper-any-time-{now.timestamp()}"), tmp_path / "user_data"))
    engine.add_cluster(_config(tmp_path))
    engine.initialize()
    assert engine.runtimes
    engine.stop()


def test_custom_reconciliation_policy_is_selected_by_paper_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata)
    config = _config(tmp_path)
    payload = json.loads(json.dumps(dict(config.normalized_payload)))
    payload["accounts"][0]["fee_reconciliation_policy"] = {  # type: ignore[index]
        "policy_id": "CUSTOM_STRICT",
        "policy_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=config.source_path)
    currency = config.accounts[0].initial_cash.currency
    policy = OnlyFeeReconciliationPolicy.create(
        policy_id="CUSTOM_STRICT",
        policy_version="1",
        currency=currency,
        materiality_threshold=OnlyMoney(Decimal("0.00"), currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.BLOCK,
    )
    services = only_default_engine_services()
    services.assembler.components.fee_reconciliation_policies.register(policy)
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId("paper-reconciliation-policy-custom"), tmp_path / "user_data"),
        services=services,
    )
    engine.add_cluster(config)

    engine.initialize()
    try:
        assert engine.runtimes[0].config.fee_reconciliation_policy is policy
    finally:
        engine.stop()


def test_missing_reconciliation_policy_fails_paper_factory_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata)
    config = _config(tmp_path)
    payload = json.loads(json.dumps(dict(config.normalized_payload)))
    payload["accounts"][0]["fee_reconciliation_policy"] = {  # type: ignore[index]
        "policy_id": "NOT_INSTALLED",
        "policy_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=config.source_path)
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId("paper-reconciliation-policy-missing"), tmp_path / "user_data"),
        services=only_default_engine_services(),
    )
    before = engine.snapshot()
    with pytest.raises(ValueError, match="FEE_RECONCILIATION_POLICY_NOT_INSTALLED"):
        engine.add_cluster(config)
    assert engine.snapshot() == before


def test_engine_replays_isolated_warmup_and_establishes_watermark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata)
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
                "success",
            )
        ),
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("paper-warmup-success"), tmp_path / "user_data"))
    engine.add_cluster(_config(tmp_path))
    engine.initialize()

    engine.start()

    runtime = engine.runtimes[0]
    assert runtime.state is OnlyRuntimeState.RUNNING
    assert runtime.inspection_run_id == f"paper-{runtime.runtime_id}"  # type: ignore[attr-defined]
    assert runtime.last_historical_bar_end is not None  # type: ignore[attr-defined]
    assert len(runtime.historical_warmup_results[0].bars) >= 10  # type: ignore[attr-defined]
    assert len(runtime.processing_results) >= 10  # type: ignore[attr-defined]
    assert runtime.streaming_phase is OnlyStreamingPhase.LIVE  # type: ignore[attr-defined]
    assert runtime.historical_watermarks  # type: ignore[attr-defined]
    observations = runtime.latest_observation_store.list_runtime(runtime.config.runtime_id)  # type: ignore[attr-defined]
    assert observations
    assert observations[0].runtime_state is OnlyRuntimeState.RUNNING
    assert observations[0].observation_source is OnlyObservationSource.HISTORICAL_BOOTSTRAP
    assert runtime.order_snapshots == ()  # type: ignore[attr-defined]
    assert xtdata.subscriptions == [1]
    engine.stop()
    assert not xtdata.subscriptions
    jsonl = tmp_path / "user_data" / "observations" / "paper-macd.jsonl"
    assert jsonl.is_file()


def test_open_bootstrap_rejects_opening_auction_bar_and_watermarks_last_processed_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata, datetime(2026, 8, 4, 1, 36, 17, tzinfo=UTC))
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
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("paper-open-boundary"), tmp_path / "user_data"))
    engine.add_cluster(_config(tmp_path))
    engine.initialize()

    engine.start()

    runtime = engine.runtimes[0]
    snapshot = runtime.historical_watermarks[0]  # type: ignore[attr-defined]
    assert runtime.historical_replay_attempted_count == 13  # type: ignore[attr-defined]
    assert runtime.historical_processed_bar_count == 12  # type: ignore[attr-defined]
    assert runtime.historical_rejected_bar_count == 1  # type: ignore[attr-defined]
    assert runtime.historical_first_rejection_reason == "HISTORICAL_BAR_OUTSIDE_CALENDAR_SESSION"  # type: ignore[attr-defined]
    assert runtime.historical_last_processed_bar_end == snapshot.last_bar_end  # type: ignore[attr-defined]
    assert snapshot.last_bar_end == runtime.historical_requested_end  # type: ignore[attr-defined]
    observations = runtime.latest_observation_store.list_runtime(runtime.config.runtime_id)  # type: ignore[attr-defined]
    assert observations
    assert observations[0].latest_bar_end == snapshot.last_bar_end
    engine.stop()


def test_formal_engine_fake_live_advances_six_external_and_two_derived_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xtdata = _FakeLiveXtData()
    initial = datetime(2026, 8, 4, 1, 36, 17, tzinfo=UTC)
    clock = OnlyBacktestClock(initial)

    def create(self: OnlyMiniQmtDataSourceFactory, request: object) -> OnlyMiniQmtDataSource:
        del self
        return OnlyMiniQmtDataSource(request, request.plugin_config, xtdata)  # type: ignore[arg-type,attr-defined]

    monkeypatch.setattr(OnlyMiniQmtDataSourceFactory, "create", create)
    monkeypatch.setattr("onlyalpha.runtime.paper.factory.OnlyLiveClock", lambda: clock)
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
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("paper-fake-live"), tmp_path / "user_data"))
    engine.add_cluster(_acceptance_config(tmp_path))
    engine.initialize()
    engine.start()
    stopped = False
    try:
        inspection = OnlyEngineInspectionService()
        before = inspection.capture(engine)[0]

        for minute in range(37, 45):
            boundary = datetime(2026, 8, 4, 1, minute, tzinfo=UTC)
            clock.advance_to(boundary)
            xtdata.publish_bar(boundary)
            time.sleep(0.02)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            after = inspection.capture(engine)[0]
            if (
                after.closed_external_bar_count - before.closed_external_bar_count >= 6
                and after.derived_internal_bar_count - before.derived_internal_bar_count >= 2
                and after.live_observation_count - before.live_observation_count >= 6
            ):
                break
            time.sleep(0.02)
        else:
            pytest.fail("formal fake live path did not reach the frozen Bar targets")

        assert after.live_order_intent_count - before.live_order_intent_count >= 1
        assert after.shadow_suppressed_count - before.shadow_suppressed_count >= 1
        assert after.reservation_created_count - before.reservation_created_count >= 1
        assert after.reservation_released_count - before.reservation_released_count >= 1
        assert after.open_reservation_count == 0
        assert after.external_order_id_count == 0
        assert after.fill_count == 0
        assert after.position_count == 0
        assert after.pending_live_bar_count == 1
        pending_identity_end = datetime(2026, 8, 4, 1, 44, tzinfo=UTC)
        assert after.latest_observations[0].latest_bar_end.to_datetime() < pending_identity_end

        engine.stop()
        stopped = True
        after_stop = inspection.capture(engine)[0]
        assert after_stop.closed_external_bar_count == after.closed_external_bar_count
        assert after_stop.live_observation_count == after.live_observation_count
        assert after_stop.latest_observations[0].latest_bar_end == after.latest_observations[0].latest_bar_end
    finally:
        if not stopped:
            engine.stop()


def test_engine_worker_abort_fails_before_live_subscription(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata)
    monkeypatch.setattr(
        OnlyMiniQmtHistoricalIsolatedClient,
        "_default_command",
        staticmethod(lambda _: (sys.executable, "-c", "import os; os.abort()")),
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("paper-warmup-abort"), tmp_path / "user_data"))
    engine.add_cluster(_config(tmp_path))
    engine.initialize()

    with pytest.raises(OnlyPluginLifecycleError, match="WORKER_ABORTED"):
        engine.start()

    runtime = engine.runtimes[0]
    assert runtime.state is OnlyRuntimeState.FAILED
    assert runtime.historical_warmup_results[0].status == "WORKER_ABORTED"  # type: ignore[attr-defined]
    assert not xtdata.subscriptions
    engine.stop()


def test_snapshot_cli_publishes_historical_node_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    xtdata = _FakeLiveXtData()
    _patch_source_factory(monkeypatch, xtdata, datetime(2026, 8, 3, 4, 44, tzinfo=UTC))
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
                "success",
            )
        ),
    )
    config = _config(tmp_path)
    config_path = _write_cli_config(tmp_path, config)
    userdata_path = Path(str(config.normalized_payload["data_sources"][0]["extensions"]["userdata_mini_path"]))  # type: ignore[index]
    assert userdata_path.is_relative_to(tmp_path)
    assert (
        main(
            [
                "snapshot",
                "--config",
                str(config_path),
                "--user-data",
                str(tmp_path / "user_data"),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"snapshots"' in output
    assert "HISTORICAL_BOOTSTRAP" in output
    assert '"market_session_state": "BREAK"' in output
    assert '"data_state": "IDLE"' in output
    assert not xtdata.subscriptions
