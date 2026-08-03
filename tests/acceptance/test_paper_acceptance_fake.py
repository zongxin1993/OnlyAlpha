from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.application import OnlyEngineInspectionService
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.operations.acceptance import OnlyPaperAcceptanceAssertions, OnlyPaperAcceptancePlan

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
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_paper_acceptance.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir()
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    payload["runtime"]["extensions"]["streaming"]["bootstrap_bars"] = 10
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def test_formal_engine_exposes_historical_inspection_and_ordered_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xtdata = _FakeLiveXtData()
    clock = OnlyBacktestClock(datetime(2026, 8, 3, 6, 0, tzinfo=UTC))

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
                "success",
            )
        ),
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("paper-acceptance-fake"), tmp_path / "user_data"))
    engine.add_cluster(_config(tmp_path))
    engine.initialize()
    before = OnlyEngineInspectionService().economic_baseline(engine)
    engine.start()
    snapshot = OnlyEngineInspectionService().capture(engine)[0]
    plan = OnlyPaperAcceptancePlan.load("examples/acceptance/miniqmt_paper_v2.yaml")
    plan = replace(plan, minimum_historical_bars=10)
    passed, _, _, _ = OnlyPaperAcceptanceAssertions().historical(snapshot, plan)
    assert passed
    assert snapshot.bootstrap_suppressed_intent_count > 0
    assert snapshot.order_count == 0
    assert OnlyEngineInspectionService().economic_baseline(engine) == before
    engine.stop()
    engine.close()
    shutdown = OnlyEngineInspectionService().capture(engine)[0]
    passed, _, _, _ = OnlyPaperAcceptanceAssertions().shutdown(shutdown)
    assert passed
    assert not xtdata.subscriptions
