from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.resource import OnlyMiniQmtDataSource
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestEvidenceStore,
    OnlyBacktestProfileReference,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestSpecification,
    OnlyBacktestWorkerInstanceId,
    OnlyInMemoryBacktestExecutionStore,
)
from onlyalpha.backtest.worker import (
    OnlyBacktestRuntimeExecutionResult,
    OnlyBacktestWorker,
    OnlyBacktestWorkerOutcomeKind,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.definition import OnlyResearchDefinition
from onlyalpha.runtime.sim.runtime import OnlySimRuntime
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.promotion import (
    OnlyInMemoryStrategyPromotionLedger,
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
    _only_authorize_qualified_promotion,
)
from tests.research.calculation.support import bars
from tests.runtime_generation_support import OnlyTestRuntimeGenerationAuthority
from tests.strategy.test_strategy_freeze import _freeze_case

pytestmark = pytest.mark.integration

_HELPER = Path("plugs/onlyalpha-plugin-miniqmt/tests/helpers/historical_worker.py").resolve()
_OBSERVED_AT = datetime(2026, 8, 4, 1, 36, 17, tzinfo=UTC)


class _ExactMiniQmtFeed:
    def __init__(self, ends: tuple[datetime, ...]) -> None:
        self._ends = ends
        self.callbacks = []

    def download_history_data(self, *args, **kwargs) -> None:
        del args, kwargs

    def get_market_data_ex(self, fields, symbols, period, **kwargs):
        del fields, period, kwargs
        rows = [
            {
                "time": int(end.timestamp() * 1000),
                "open": "10.00",
                "high": "10.10",
                "low": "9.90",
                "close": "10.05",
                "volume": "100",
            }
            for end in self._ends
        ]
        return {symbols[0]: rows}

    def subscribe_quote(self, *args, **kwargs) -> int:
        del args
        self.callbacks.append(kwargs["callback"])
        return len(self.callbacks)

    def unsubscribe_quote(self, sequence: int) -> None:
        del sequence


def _research_bars():
    instrument = OnlyInstrumentId.parse("000001.XSHE")
    return tuple(
        replace(
            bar,
            bar_type=OnlyBarType(instrument, bar.bar_type.specification, bar.bar_type.aggregation_source),
        )
        for bar in bars()[:4]
    )


def _runtime_config(runtime_type: str, strategy_fingerprint: str, tmp_path: Path) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/runtime/miniqmt_sim_acceptance.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["cluster"]["runtime_type"] = runtime_type
    payload["strategy"] = {"fingerprint": strategy_fingerprint}
    if runtime_type == "BACKTEST":
        payload["runtime"]["start_time"] = "2026-08-03T06:57:00Z"
        payload["runtime"]["end_time"] = "2026-08-04T01:37:00Z"
    payload["runtime"]["extensions"]["streaming"]["bootstrap_bars"] = 10
    payload["runtime"]["persistence"] = {"backend": "MEMORY", "checkpoint": {"enabled": False}}
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True, exist_ok=True)
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata)
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def test_research_evidence_freeze_publishes_one_strategy_for_backtest_and_sim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_data = tmp_path / "user_data"
    strategy_asset = only_discover_quant_asset_providers().resolve_strategy_asset(
        "example.strategy.library", "1", "example.strategy.simple_momentum", "1"
    )
    source_definition = OnlyResearchDefinition.from_dict(
        json.loads(strategy_asset.resource_bytes("research-definition.json"))
    )
    service, run, candidate, frozen_store, _catalog = _freeze_case(
        tmp_path / "research-authorities",
        semantic_root=user_data / "research",
        values=_research_bars(),
        source_definition=source_definition,
    )
    frozen = service.freeze(OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "certifier"))
    fingerprint = frozen.strategy_fingerprint
    assert frozen_store.load_verified(fingerprint).strategy_fingerprint.value == fingerprint
    promotion = OnlyStrategyPromotionService(
        frozen_store,
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 9, 3, tzinfo=UTC),
    )
    promotion.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.BACKTEST,
        evidence_fingerprints=tuple(sorted((frozen.freeze_record.record_fingerprint, "f" * 64))),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="example vertical admission",
        actor="operator",
        qualification_authorization=_only_authorize_qualified_promotion("f" * 64),
    )
    assert promotion.current_stage(fingerprint) is OnlyStrategyPromotionStage.BACKTEST

    current_close = _OBSERVED_AT.replace(second=0, microsecond=0)
    previous_close = current_close - timedelta(hours=18, minutes=36)
    exact_ends = tuple(previous_close - timedelta(minutes=offset) for offset in range(2, -1, -1)) + tuple(
        current_close - timedelta(minutes=offset) for offset in range(5, -1, -1)
    )
    feed = _ExactMiniQmtFeed(exact_ends)

    def create(self: OnlyMiniQmtDataSourceFactory, request: object) -> OnlyMiniQmtDataSource:
        del self
        return OnlyMiniQmtDataSource(request, request.plugin_config, feed)  # type: ignore[arg-type,attr-defined]

    monkeypatch.setattr(OnlyMiniQmtDataSourceFactory, "create", create)
    monkeypatch.setattr("onlyalpha.runtime.sim.factory.OnlyLiveClock", lambda: OnlyBacktestClock(_OBSERVED_AT))
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

    decisions: dict[str, list[object]] = {"BACKTEST": [], "SIM": []}
    active_runtime = "BACKTEST"
    original_on_bar = OnlyRevisionStrategyAdapter.on_bar

    def capture(self, bar):
        decision = original_on_bar(self, bar)
        decisions[active_runtime].append(decision)
        return decision

    monkeypatch.setattr(OnlyRevisionStrategyAdapter, "on_bar", capture)

    backtest = OnlyEngine(OnlyEngineConfig(OnlyEngineId("p9-c2-backtest"), user_data))
    backtest.add_cluster(_runtime_config("BACKTEST", fingerprint, tmp_path))
    backtest_result = backtest.run()
    assert backtest_result.status == "COMPLETED"

    revision = frozen_store.load_verified(fingerprint)
    implementation_fingerprints = tuple(
        sorted({item.trading_implementation_fingerprint for item in revision.implementation_bindings})
    )
    profile = OnlyBacktestProfileReference("example", "1")
    specification = OnlyBacktestSpecification(
        fingerprint,
        "b" * 64,
        "c" * 64,
        profile,
        profile,
        profile,
        "CNY",
        "100000",
    )
    resolution = OnlyBacktestAdmissionResolution(
        revision.schema_version,
        fingerprint,
        specification.dataset_binding_fingerprint,
        "d" * 64,
        "e" * 64,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "ONLYALPHA_KERNEL_SEMANTICS@1",
        implementation_fingerprints,
    )
    product_run = OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId("00000000-0000-4000-8000-000000000902"),
        specification=specification,
        admission_resolution=resolution,
        queued_at=_OBSERVED_AT,
    )

    class _Admission:
        def resolve(self, candidate):  # type: ignore[no-untyped-def]
            assert candidate == specification
            assert promotion.current_stage(fingerprint) is OnlyStrategyPromotionStage.BACKTEST
            return resolution

    class _ExecutedBacktest:
        def execute(self, candidate):  # type: ignore[no-untyped-def]
            assert candidate.specification.strategy_fingerprint == fingerprint
            actual = backtest_result.runtime_results[0]
            return OnlyBacktestRuntimeExecutionResult(
                actual.result_fingerprint,
                actual.determinism_fingerprint,
                (("result.json", only_canonical_json(actual.to_dict()).encode(), "application/json"),),
            )

    class _Lease:
        ownership_lost = False

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_):  # type: ignore[no-untyped-def]
            return None

    product_store = OnlyInMemoryBacktestExecutionStore((product_run,), now_utc=lambda: _OBSERVED_AT)
    runtime_generations = OnlyTestRuntimeGenerationAuthority()
    runtime_generations.bind_new_work(product_run.run_id.value)
    evidence_store = OnlyBacktestEvidenceStore(user_data)
    outcome = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=product_store,
        admission=_Admission(),  # type: ignore[arg-type]
        executor=_ExecutedBacktest(),  # type: ignore[arg-type]
        evidence=evidence_store,
        lease_control_factory=lambda *_: _Lease(),  # type: ignore[arg-type]
        runtime_generations=runtime_generations,
        process_generation_fingerprint=runtime_generations.generation_fingerprint,
    ).run_once()
    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.COMPLETED
    assert outcome.run is not None and outcome.run.evidence_fingerprint is not None
    evidence = evidence_store.load_verified(outcome.run.evidence_fingerprint)
    assert evidence.strategy_fingerprint == fingerprint
    assert evidence.result_fingerprint == backtest_result.runtime_results[0].result_fingerprint

    active_runtime = "SIM"
    sim = OnlyEngine(OnlyEngineConfig(OnlyEngineId("p9-c2-sim"), user_data))
    sim.add_cluster(_runtime_config("SIM", fingerprint, tmp_path))
    sim.initialize()
    sim.start()
    try:
        assert isinstance(sim.runtimes[0], OnlySimRuntime)
        assert decisions["SIM"]
    finally:
        sim.stop()
        sim.close()

    assert [item.decision_time.unix_nanos for item in decisions["BACKTEST"]] == [  # type: ignore[attr-defined]
        item.decision_time.unix_nanos
        for item in decisions["SIM"]  # type: ignore[attr-defined]
    ]
    assert decisions["BACKTEST"] == decisions["SIM"]
    assert {item.strategy_fingerprint for item in decisions["BACKTEST"]} == {fingerprint}  # type: ignore[attr-defined]
