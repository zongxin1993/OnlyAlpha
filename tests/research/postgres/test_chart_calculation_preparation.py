from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import psycopg
import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationRequestV1
from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationPreparationService
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.research.dataset.market_data_materializer import OnlySealedMarketDataDatasetMaterializer
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from tests.application.test_chart_calculation_admission import NOW, D, payload, witness
from tests.application.test_market_data_product import BASE, INSTRUMENT, _reference, _service
from tests.research.postgres.test_chart_calculation_admission import admit, store

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
WORKER = OnlyProductCommandId("00000000-0000-4000-8000-000000000711")
OTHER = OnlyProductCommandId("00000000-0000-4000-8000-000000000712")
GENERATION = "b" * 64


def test_claim_lease_restart_and_fencing(postgres_dsn: str) -> None:
    operation = admit(store(postgres_dsn)).operation
    adapter = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    first = adapter.claim(operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    assert first.runtime_work_id == operation.reserved_run_id.value
    assert first.revision == first.fence == 1
    assert adapter.load_verified(operation) == first
    with pytest.raises(ValueError, match="CHART_PREPARATION_BUSY"):
        adapter.claim(operation, OTHER, GENERATION, lease_duration=timedelta(minutes=2))
    renewed = adapter.heartbeat(operation, first, lease_duration=timedelta(minutes=2))
    assert renewed.revision == 2 and renewed.fence == first.fence
    restarted = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    assert restarted.load_verified(operation) == renewed
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        restarted.claim(operation, WORKER, "c" * 64, lease_duration=timedelta(minutes=2))


def test_parallel_claim_has_one_owner(postgres_dsn: str) -> None:
    operation = admit(store(postgres_dsn)).operation
    adapter = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait()
        try:
            return adapter.claim(operation, worker, GENERATION, lease_duration=timedelta(minutes=2)).worker_id
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(claim, (WORKER, OTHER)))
    assert results.count("CHART_PREPARATION_BUSY") == 1
    assert sum(isinstance(item, OnlyProductCommandId) for item in results) == 1


def test_preparation_history_cannot_be_rewritten(postgres_dsn: str) -> None:
    operation = admit(store(postgres_dsn)).operation
    adapter = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    first = adapter.claim(operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    failed = adapter.fail(operation, first, "CHART_SEALED_COVERAGE_UNAVAILABLE")
    assert failed.state == "FAILED" and failed.revision == 2
    for command in (
        "DELETE FROM chart_calculation_preparation_fact",
        "UPDATE chart_calculation_preparation_fact SET fence = fence + 1",
        "TRUNCATE chart_calculation_preparation_fact",
    ):
        with pytest.raises(psycopg.Error):
            with psycopg.connect(postgres_dsn) as connection:
                connection.execute(command)
    assert adapter.claim(operation, OTHER, GENERATION, lease_duration=timedelta(minutes=2)) == failed


def prepared_system(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, period: int = 20, acquire: bool = True
):
    admission = store(postgres_dsn)
    market = _service(tmp_path / "market", native_minutes=(1, 15))
    market.service._clock = OnlyBacktestClock(BASE + timedelta(hours=8))
    reference = _reference(market.revision_fingerprint)
    start = OnlyTimestamp.from_datetime(BASE).unix_nanos
    end = start + (period + 3) * D
    selected = market.service.plan_selection(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start,
        end_ns=end,
        bar_semantic=OnlyBarSemantic.fixed_duration(15),
    )
    if acquire:
        market.service.acquire_bars(
            reference,
            instrument_id=str(INSTRUMENT),
            start_ns=start,
            end_ns=end,
            bar_semantic=OnlyBarSemantic.fixed_duration(15),
        )
    raw = payload({"period": period})
    raw["source_reference"] = {
        "integration_id": reference.integration_id,
        "integration_revision_fingerprint": reference.integration_revision_fingerprint,
        "expected_type_id": reference.expected_type_id,
    }
    raw["instrument_id"] = str(INSTRUMENT)
    raw["display_range"] = {"start_ns": str(start + (period - 1) * D), "end_ns": str(end)}
    operation = admission.admit_or_replay(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000721"),
        OnlyChartCalculationRequestV1.from_dict(raw),
        witness(),
        accepted_at=NOW,
    ).operation
    adapter = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    clock = [NOW]
    monkeypatch.setattr(adapter, "_now", lambda connection: clock[0])
    runtime = Mock(spec=OnlyRuntimeGenerationWorkAuthority)
    bindings = {}

    def load_binding(work):
        if work not in bindings:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
        return bindings[work]

    def bind_exact(work, generation, **kwargs):
        existing = bindings.get(work)
        if existing is not None and existing.runtime_generation_fingerprint != generation:
            raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
        binding = existing or SimpleNamespace(work_id=work, runtime_generation_fingerprint=generation, active=True)
        bindings[work] = binding
        return binding

    def require_work(work, generation):
        binding = load_binding(work)
        if not binding.active or binding.runtime_generation_fingerprint != generation:
            raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")
        return runtime.require_runtime_generation(generation)

    runtime.require_work_binding.side_effect = load_binding
    runtime.require_work_generation.side_effect = require_work
    catalog = operation.catalog_witness.to_dict()["context"]["catalog_generation_fingerprint"]
    runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint=GENERATION, catalog_generation_fingerprint=catalog
    )
    runtime.require_new_work_generation.return_value = runtime.require_runtime_generation.return_value

    def release(work, **kwargs):
        binding = load_binding(work)
        bindings[work] = SimpleNamespace(
            work_id=binding.work_id, runtime_generation_fingerprint=binding.runtime_generation_fingerprint, active=False
        )
        return bindings[work]

    runtime.release_work.side_effect = release
    runtime.bind_work_exact.side_effect = bind_exact
    dataset = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "dataset")
    materializer = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(market.catalog, market.service._facts), dataset, dataset, lambda: NOW
    )
    service = OnlyChartCalculationPreparationService(
        store=adapter,
        runtime_generations=cast(OnlyRuntimeGenerationWorkAuthority, runtime),
        market_data=market.service,
        catalog=market.catalog,
        facts=market.service._facts,
        materializer=materializer,
    )
    return SimpleNamespace(
        operation=operation,
        adapter=adapter,
        clock=clock,
        runtime=runtime,
        dataset=dataset,
        materializer=materializer,
        service=service,
        market=market,
        selected=selected,
        bindings=bindings,
    )


def publish_revision(system, revision_id):
    from dataclasses import replace
    from decimal import Decimal

    from onlyalpha.data.evidence import OnlyRawProviderObservation
    from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
    from onlyalpha.domain.value import OnlyPrice
    from onlyalpha.market_data.durable import OnlyMarketDataIngress, OnlyMarketDataWal, OnlyRevisionCommitService

    query = OnlyHistoricalMarketDataQueryService(system.market.catalog, system.market.service._facts)
    parent, parent_seal = query.resolve_with_seal(revision_id)
    facts = query.read_exact(revision_id, parent.scope)
    wal = OnlyMarketDataWal(
        system.market.wal_root.parent / ("replacement-" + parent.fingerprint), capacity_bytes=2_000_000, now=lambda: NOW
    )
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="test-data",
        normalizer_version="1.0.0",
        ingest_clock_ns=lambda: 5,
        bar_construction=parent.scope.bar_construction,
    )
    ingress.begin_segment("replacement-" + parent.fingerprint)
    for index, fact in enumerate(facts):
        update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
        assert isinstance(update.payload, OnlyBarUpdate)
        if index == len(facts) - 1:
            bar = replace(
                update.payload.bar, high=OnlyPrice(Decimal("999.00"), 2), close=OnlyPrice(Decimal("999.00"), 2)
            )
            update = replace(update, payload=OnlyBarUpdate(bar))
        ingress.record(
            OnlyRawProviderObservation(
                source_id=parent.scope.source_id,
                capture_session_id="correction",
                provider="TEST",
                venue="TEST",
                market=parent.scope.market,
                stream="/klines",
                provider_event_type="correction",
                ts_receive_ns=update.ts_init.unix_nanos,
                payload=str(index).encode(),
                provenance="REPAIR",
            ),
            update,
        )
    segment = ingress.seal()
    records = wal.read_sealed(segment.segment_id)
    system.market.service._facts.write_segment(segment, records)
    _, newer, _ = OnlyRevisionCommitService(
        system.market.service._facts,
        system.market.catalog,
        now=lambda: parent_seal.sealed_at + timedelta(microseconds=1),
    ).commit(
        segment,
        parent.scope,
        {segment.segment_id: records},
        parent_revision_id=revision_id,
        reason="CORRECTION",
    )
    assert newer.scope == parent.scope
    return newer


def prepare(system, worker=WORKER):
    return system.service.prepare(
        system.operation, worker_id=worker, runtime_generation_fingerprint=GENERATION, occurred_at=NOW
    )


@pytest.mark.parametrize("period", [1, 20])
def test_exact_native_input_pin_and_verified_lineage(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period: int
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, period=period)
    committed = system.dataset.commit

    def require_committed_pin(snapshot, partitions):
        assert system.adapter.load_verified(system.operation).input_pin is not None
        return committed(snapshot, partitions)

    monkeypatch.setattr(system.dataset, "commit", require_committed_pin)
    fetched = system.market.provider.bar_fetches
    result = prepare(system)
    assert result.state == "INPUT_READY"
    pin = result.input_pin
    assert result.input_selection_fingerprint == pin.fingerprint
    assert pin.scope == system.selected.scope
    evidence = pin.to_dict()["evidence"]
    assert evidence["revision"]["revision_id"] == pin.revision_id
    assert evidence["manifest"]["fingerprint"] in evidence["manifest"]["manifest_id"]
    assert evidence["seal"]["revision_fingerprint"] == evidence["revision"]["fingerprint"]
    assert evidence["physical_proofs"] and "SEGMENT_HASH_VERIFIED" in evidence["seal"]["checks"]
    assert pin.scope.bar_construction.plan.resolved_recipe is not None
    assert system.dataset.load_verified_table(result.dataset_snapshot_fingerprint).snapshot.row_count == period + 3
    lineage = system.dataset.load_materialization(result.dataset_materialization_id)
    assert lineage.dataset_snapshot_fingerprint == result.dataset_snapshot_fingerprint
    assert lineage.market_data_revision_bindings[0].revision_id == pin.revision_id
    system.runtime.bind_work_exact.assert_called_with(
        system.operation.reserved_run_id.value, GENERATION, actor="chart-input-preparation", occurred_at=NOW
    )
    assert system.market.provider.bar_fetches == fetched
    assert prepare(system) == result
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM chart_calculation_preparation_fact WHERE kind = %s", ("PIN",)
            ).fetchone()[0]
            == 1
        )


def test_missing_exact_coverage_fails_without_acquisition_or_snapshot(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    result = prepare(system)
    assert result.state == "FAILED" and result.failure_code == "CHART_SEALED_COVERAGE_UNAVAILABLE"
    assert system.market.provider.bar_fetches == system.market.catalog.mutations == 0
    assert not system.market.wal_root.exists() and not (tmp_path / "dataset").exists()
    binding = system.runtime.require_work_binding(system.operation.reserved_run_id.value)
    assert binding.active is False
    assert prepare(system) == result


@pytest.mark.parametrize("state", ("READY", "DRAINING"))
def test_fresh_preparation_rejects_nonactive_generation_before_claim(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    system.runtime.require_new_work_generation.side_effect = ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK")
    with pytest.raises(ValueError, match="CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) is None
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()
    # A rejected generation has not frozen or poisoned this occurrence.
    system.runtime.require_new_work_generation.side_effect = None
    assert prepare(system).failure_code == "CHART_SEALED_COVERAGE_UNAVAILABLE"


def test_activation_change_between_claim_and_bind_fails_without_fall_forward(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    system.runtime.require_new_work_generation.side_effect = (
        system.runtime.require_runtime_generation.return_value,
        ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"),
    )
    result = prepare(system)
    assert result.state == "FAILED" and result.failure_code == "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
    assert result.runtime_generation_fingerprint == GENERATION
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()
    assert not system.bindings and system.market.catalog.mutations == 0
    system.runtime.require_new_work_generation.side_effect = AssertionError("terminal replay read activation")
    assert prepare(system) == result


def test_claim_without_binding_fails_durably_after_activation_change(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.require_new_work_generation.side_effect = ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK")
    result = prepare(system)
    assert result.failure_code == "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
    assert system.adapter.load_verified(system.operation) == result
    system.runtime.bind_work_exact.assert_not_called()


@pytest.mark.parametrize("lost_response", (False, True))
def test_failed_fact_precedes_release_and_unknown_response_converges(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_response: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    original = system.runtime.release_work.side_effect

    def unavailable(work, **kwargs):
        assert system.adapter.load_verified(system.operation).state == "FAILED"
        if lost_response:
            original(work, **kwargs)
        raise OSError("release response lost")

    system.runtime.release_work.side_effect = unavailable
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE"):
        prepare(system)
    failed = system.adapter.load_verified(system.operation)
    assert failed.state == "FAILED" and failed.failure_code == "CHART_SEALED_COVERAGE_UNAVAILABLE"
    system.runtime.release_work.side_effect = original
    system.runtime.require_new_work_generation.side_effect = AssertionError("terminal replay read activation")
    system.runtime.require_runtime_generation.side_effect = AssertionError(
        "terminal replay read Catalog/retired generation"
    )
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("terminal selected Market Data"))
    )
    monkeypatch.setattr(
        system.materializer, "materialize_with_lineage", Mock(side_effect=AssertionError("terminal wrote Dataset"))
    )
    assert prepare(system, OTHER) == failed
    assert not system.runtime.require_work_binding(system.operation.reserved_run_id.value).active
    assert prepare(system) == failed
    assert system.adapter.load_verified(system.operation).revision == failed.revision


def test_exact_active_binding_recovery_ignores_current_activation(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.bind_work_exact(
        system.operation.reserved_run_id.value, GENERATION, actor="recovery", occurred_at=NOW
    )
    system.runtime.bind_work_exact.reset_mock()
    system.runtime.require_new_work_generation.side_effect = AssertionError("bound recovery read activation")
    result = prepare(system)
    assert result.state == "INPUT_READY"
    assert system.runtime.require_work_binding(system.operation.reserved_run_id.value).active
    assert prepare(system) == result
    system.runtime.release_work.assert_not_called()
    system.runtime.bind_work_exact.assert_not_called()


@pytest.mark.parametrize("ready", (False, True))
def test_nonterminal_or_input_ready_inactive_binding_fails_closed(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    if ready:
        previous = prepare(system)
    else:
        previous = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
        system.runtime.bind_work_exact(
            system.operation.reserved_run_id.value, GENERATION, actor="recovery", occurred_at=NOW
        )
    system.runtime.release_work(system.operation.reserved_run_id.value, actor="operator", occurred_at=NOW)
    system.runtime.bind_work_exact.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_INACTIVE"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.bind_work_exact.assert_not_called()


def test_failed_work_release_allows_real_generation_retirement_and_terminal_replay(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
    from tests.runtime_support.generation_support import only_ready_test_generation

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "generation-authority")
    seed = only_ready_test_generation(registry, "a", NOW)
    manifest = replace(
        registry.load_manifest(seed),
        catalog_generation_fingerprint=system.operation.catalog_witness.to_dict()["context"][
            "catalog_generation_fingerprint"
        ],
    )
    registry.prepare(manifest, actor="test", occurred_at=NOW)
    registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="test", occurred_at=NOW)
    generation = manifest.runtime_generation_fingerprint
    registry.activate_for_new_work(expected_current=None, target=generation, actor="test", occurred_at=NOW)
    system.service._runtime = registry
    failed = system.service.prepare(
        system.operation,
        worker_id=WORKER,
        runtime_generation_fingerprint=generation,
        occurred_at=NOW,
    )
    assert failed.state == "FAILED"
    assert registry.require_work_binding(system.operation.reserved_run_id.value).active is False
    registry.activate_for_new_work(expected_current=generation, target=seed, actor="test", occurred_at=NOW)
    registry.retire(generation, actor="test", occurred_at=NOW)
    restarted = OnlyRuntimeGenerationRegistry(tmp_path / "generation-authority")
    system.service._runtime = restarted
    assert (
        system.service.prepare(
            system.operation,
            worker_id=OTHER,
            runtime_generation_fingerprint=generation,
            occurred_at=NOW,
        )
        == failed
    )


@pytest.mark.parametrize("terminal", (False, True))
@pytest.mark.parametrize(
    "field,value", (("work_id", OTHER.value), ("runtime_generation_fingerprint", "c" * 64), ("active", None))
)
def test_conflicting_binding_never_changes_preparation_or_releases_other_work(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool, field: str, value: object
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    if terminal:
        previous = prepare(system)
    else:
        previous = None
        system.runtime.bind_work_exact(
            system.operation.reserved_run_id.value, GENERATION, actor="test", occurred_at=NOW
        )
    binding = system.bindings[system.operation.reserved_run_id.value]
    setattr(binding, field, value)
    system.runtime.bind_work_exact.reset_mock()
    system.runtime.release_work.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()


def test_input_ready_missing_binding_requires_intervention_not_rebinding(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    previous = prepare(system)
    system.bindings.clear()
    system.runtime.bind_work_exact.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.bind_work_exact.assert_not_called()


@pytest.mark.parametrize("stage", ["snapshot", "lineage", "ready"])
def test_crash_reentry_remains_on_pinned_revision(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    owner = system.dataset if stage != "ready" else system.adapter
    name = "commit" if stage == "snapshot" else "commit_materialization" if stage == "lineage" else "input_ready"
    original = getattr(owner, name)

    def crash(*args, **kwargs):
        if stage != "ready":
            original(*args, **kwargs)
        raise RuntimeError("injected process loss")

    monkeypatch.setattr(owner, name, crash)
    with pytest.raises(RuntimeError, match="injected process loss"):
        prepare(system)
    old = system.adapter.load_verified(system.operation)
    assert old.input_pin is not None and old.state == "MATERIALIZING_INPUT"
    newer = publish_revision(system, old.input_pin.revision_id)
    assert newer.revision_id != old.input_pin.revision_id
    monkeypatch.setattr(owner, name, original)
    system.clock[0] += timedelta(minutes=3)
    restarted = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    monkeypatch.setattr(restarted, "_now", lambda connection: system.clock[0])
    system.adapter = restarted
    system.service = OnlyChartCalculationPreparationService(
        store=restarted,
        runtime_generations=cast(OnlyRuntimeGenerationWorkAuthority, system.runtime),
        market_data=system.market.service,
        catalog=system.market.catalog,
        facts=system.market.service._facts,
        materializer=OnlySealedMarketDataDatasetMaterializer(
            OnlyHistoricalMarketDataQueryService(system.market.catalog, system.market.service._facts),
            system.dataset,
            system.dataset,
            lambda: NOW,
        ),
    )

    def no_reselection(*args, **kwargs):
        raise AssertionError("recovery selected current source or latest Revision")

    monkeypatch.setattr(system.market.service, "plan_selection", no_reselection)
    result = prepare(system, OTHER)
    assert result.state == "INPUT_READY" and result.fence == old.fence + 1
    assert result.input_pin == old.input_pin
    with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
        system.adapter.fail(system.operation, old, "CHART_DATASET_MATERIALIZATION_FAILED")
    assert (
        system.dataset.load_materialization(result.dataset_materialization_id)
        .market_data_revision_bindings[0]
        .revision_id
        == old.input_pin.revision_id
    )


def test_wrong_catalog_generation_and_wrong_work_binding_fail_closed(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    manifest = system.runtime.require_runtime_generation.return_value
    manifest.catalog_generation_fingerprint = "f" * 64
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) is None
    manifest.catalog_generation_fingerprint = system.operation.catalog_witness.to_dict()["context"][
        "catalog_generation_fingerprint"
    ]
    system.runtime.bind_work_exact.side_effect = lambda *a, **kw: SimpleNamespace(
        work_id=system.operation.reserved_run_id.value, runtime_generation_fingerprint="f" * 64, active=True
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert not (tmp_path / "dataset").exists()


def test_expired_worker_loses_pin_race_to_newer_revision(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    observed = Event()
    resume = Event()
    original = system.service._evidence
    first = True

    def block_after_first_observation(revision_id, scope):
        nonlocal first
        evidence = original(revision_id, scope)
        if first:
            first = False
            observed.set()
            assert resume.wait(20)
        return evidence

    monkeypatch.setattr(system.service, "_evidence", block_after_first_observation)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(prepare, system)
        assert observed.wait(20)
        revision = system.market.catalog.latest_sealed_revision(system.selected.scope)
        newer = publish_revision(system, revision.revision_id)
        system.clock[0] += timedelta(minutes=3)
        winner = prepare(system, OTHER)
        resume.set()
        with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
            old.result(timeout=20)
    assert winner.input_pin.revision_id == newer.revision_id
    assert system.adapter.load_verified(system.operation) == winner
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM chart_calculation_preparation_fact WHERE kind = 'PIN'").fetchone()[
                0
            ]
            == 1
        )


def test_expired_lease_cannot_heartbeat_or_publish_even_before_reclaim(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    first = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.clock[0] += timedelta(minutes=2)
    with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
        system.adapter.heartbeat(system.operation, first, lease_duration=timedelta(minutes=2))
    with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
        system.adapter.fail(system.operation, first, "CHART_DATASET_MATERIALIZATION_FAILED")
    assert prepare(system, OTHER).fence == first.fence + 1


def test_physical_corruption_never_becomes_input_pin_or_snapshot(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)

    def broken(*args, **kwargs):
        raise RuntimeError("MARKET_DATA_PHYSICAL_PROOF_UNPROVABLE")

    monkeypatch.setattr(system.market.service._facts, "read_segment_facts", broken)
    with pytest.raises(RuntimeError, match="MARKET_DATA_PHYSICAL_PROOF_UNPROVABLE"):
        prepare(system)
    assert system.adapter.load_verified(system.operation).input_pin is None
    assert not (tmp_path / "dataset").exists()


def test_pin_owner_and_seal_mutations_reject(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationInputPinV1
    from onlyalpha.canonical import only_canonical_json

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    pin = prepare(system).input_pin
    changed = pin.to_dict()
    changed["runtime_work_id"] = system.operation.operation_id.value
    wrong_owner = OnlyChartCalculationInputPinV1(only_canonical_json(changed))
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        wrong_owner.verify_operation(system.operation, GENERATION)
    changed = pin.to_dict()
    changed["evidence"]["seal"]["checks"].remove("SEGMENT_HASH_VERIFIED")
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        OnlyChartCalculationInputPinV1(only_canonical_json(changed))


def test_rejected_generation_does_not_poison_exact_retry(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    catalog = system.operation.catalog_witness.to_dict()["context"]["catalog_generation_fingerprint"]

    def manifest(generation):
        if generation == "c" * 64:
            return SimpleNamespace(runtime_generation_fingerprint=generation, catalog_generation_fingerprint="f" * 64)
        return SimpleNamespace(runtime_generation_fingerprint=generation, catalog_generation_fingerprint=catalog)

    system.runtime.require_runtime_generation.side_effect = manifest
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        system.service.prepare(
            system.operation, worker_id=WORKER, runtime_generation_fingerprint="c" * 64, occurred_at=NOW
        )
    assert system.adapter.load_verified(system.operation) is None
    assert prepare(system).state == "INPUT_READY"


@pytest.mark.parametrize("active,generation", [(True, "c" * 64), (False, GENERATION)])
def test_conflicting_or_released_existing_work_binding_never_creates_claim(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool, generation: str
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    system.runtime.require_work_binding.side_effect = None
    system.runtime.require_work_binding.return_value = SimpleNamespace(
        work_id=system.operation.reserved_run_id.value, runtime_generation_fingerprint=generation, active=active
    )
    with pytest.raises(
        ValueError, match="CHART_RUNTIME_BINDING_CONFLICT" if active else "CHART_RUNTIME_BINDING_INACTIVE"
    ):
        prepare(system)
    assert system.adapter.load_verified(system.operation) is None
    assert not (tmp_path / "dataset").exists()


@pytest.mark.parametrize("terminal", (False, True))
@pytest.mark.parametrize("response", (None, object()))
def test_malformed_whole_binding_response_never_proves_unbound(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool, response: object
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    previous = prepare(system) if terminal else None
    system.runtime.require_work_binding.side_effect = None
    system.runtime.require_work_binding.return_value = response
    system.runtime.bind_work_exact.reset_mock()
    system.runtime.release_work.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()
