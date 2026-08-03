from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.cli import main
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.observation import OnlyObservationSource
from onlyalpha.plugin.errors import OnlyPluginLifecycleError
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.streaming.phase import OnlyStreamingPhase

pytestmark = pytest.mark.integration

_HELPER = Path("packages/provider/onlyalpha-plugin-miniqmt/tests/helpers/historical_worker.py").resolve()


class _FakeLiveXtData:
    def __init__(self) -> None:
        self.subscriptions: list[int] = []

    def subscribe_quote(self, *args: object, **kwargs: object) -> int:
        del args, kwargs
        self.subscriptions.append(1)
        return 1

    def unsubscribe_quote(self, sequence: int) -> None:
        self.subscriptions.remove(sequence)


def _config(tmp_path: Path) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_paper_macd.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["extensions"]["streaming"].update(
        {
            "bootstrap_bars": 10,
            "historical_compatibility_profile": "miniqmt-history-v1",
            "historical_timeout_seconds": 5,
        }
    )
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True)
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


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
    assert (
        main(
            [
                "snapshot",
                "--config",
                "examples/configs/miniqmt_paper_macd.yaml",
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
