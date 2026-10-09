from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
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
from onlyalpha.application.runtime_generation import (
    OnlyRuntimeGenerationWorkAuthority,
    OnlyRuntimeWorkAdmissionClosureEvidence,
    OnlyRuntimeWorkBindingEvidence,
)
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


def test_missing_accepted_binding_never_mutates_either_authority(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    work = system.operation.reserved_run_id.value
    system.runtime.bind_new_work_exact(
        work, GENERATION, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
    )
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        system.runtime.require_work_binding_evidence(work)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, claim, reference)
    system.bindings.clear()
    system.runtime.bind_new_work_exact.reset_mock()
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("missing binding read Market"))
    )
    monkeypatch.setattr(
        system.materializer,
        "materialize_with_lineage",
        Mock(side_effect=AssertionError("missing binding wrote Dataset")),
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    system.runtime.bind_new_work_exact.assert_not_called()
    system.runtime.require_new_work_generation.assert_not_called()
    assert system.bindings == {}
    assert system.adapter.load_verified(system.operation) == bound


def test_prebind_failure_cannot_follow_a_persisted_binding_reference(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.bind_new_work_exact(
        system.operation.reserved_run_id.value,
        GENERATION,
        owner="CHART_CALCULATION_INPUT",
        actor="chart",
        occurred_at=NOW,
    )
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        system.runtime.require_work_binding_evidence(system.operation.reserved_run_id.value)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, claim, reference)
    with pytest.raises(ValueError):
        system.adapter.begin_failure(system.operation, bound, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE")
    assert system.adapter.load_verified(system.operation) == bound


def test_postbind_failure_requires_persisted_binding_reference_without_appending_fact(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    with pytest.raises(ValueError):
        system.adapter.begin_failure(system.operation, claim, "CHART_SEALED_COVERAGE_UNAVAILABLE")
    assert system.adapter.load_verified(system.operation) == claim


def chart_runtime_registry(system, root):
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
    from tests.runtime_support.generation_support import only_ready_test_generation

    registry = OnlyRuntimeGenerationRegistry(root)
    other = only_ready_test_generation(registry, "a", NOW)
    manifest = replace(
        registry.load_manifest(other),
        catalog_generation_fingerprint=system.operation.catalog_witness.to_dict()["context"][
            "catalog_generation_fingerprint"
        ],
    )
    registry.prepare(manifest, actor="test", occurred_at=NOW)
    registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="test", occurred_at=NOW)
    registry.activate_for_new_work(
        expected_current=None, target=manifest.runtime_generation_fingerprint, actor="test", occurred_at=NOW
    )
    return registry, manifest.runtime_generation_fingerprint, other


@pytest.mark.parametrize("decided", (False, True))
def test_persisted_reference_rejects_wrong_runtime_root_without_mutation(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decided: bool
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    original, generation, _ = chart_runtime_registry(system, tmp_path / "original-authority")
    claim = system.adapter.claim(system.operation, WORKER, generation, lease_duration=timedelta(minutes=2))
    work = system.operation.reserved_run_id.value
    original.bind_new_work_exact(work, generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW)
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        original.require_work_binding_evidence(work)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, claim, reference)
    if decided:
        bound = system.adapter.begin_failure(system.operation, bound, "CHART_SEALED_COVERAGE_UNAVAILABLE")
    system.clock[0] += timedelta(minutes=3)
    wrong, same_generation, _ = chart_runtime_registry(system, tmp_path / "wrong-authority")
    assert same_generation == generation
    system.service._runtime = wrong
    ledger = (wrong.root / "generation-events.jsonl").read_bytes()
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("missing binding selected Market"))
    )
    monkeypatch.setattr(
        system.service._query, "resolve_latest", Mock(side_effect=AssertionError("missing binding queried Revision"))
    )
    monkeypatch.setattr(
        system.materializer,
        "materialize_with_lineage",
        Mock(side_effect=AssertionError("missing binding wrote Dataset")),
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        system.service.prepare(
            system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
        )
    assert (wrong.root / "generation-events.jsonl").read_bytes() == ledger
    assert system.adapter.load_verified(system.operation) == bound


def test_prebind_failure_finishes_after_exact_generation_retirement(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    registry, generation, other = chart_runtime_registry(system, tmp_path / "runtime")
    system.adapter.claim(system.operation, WORKER, generation, lease_duration=timedelta(minutes=2))
    registry.activate_for_new_work(expected_current=generation, target=other, actor="operator", occurred_at=NOW)
    registry.retire(generation, actor="operator", occurred_at=NOW)
    system.service._runtime = registry
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("retired failure read Market"))
    )
    monkeypatch.setattr(
        system.materializer,
        "materialize_with_lineage",
        Mock(side_effect=AssertionError("retired failure wrote Dataset")),
    )
    failed = system.service.prepare(
        system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
    )
    assert failed.state == "FAILED" and failed.failure_code == "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
    assert failed.runtime_binding_reference is None and failed.runtime_closure_reference is not None
    system.service._runtime = OnlyRuntimeGenerationRegistry(registry.root)
    system.service._store = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    assert (
        system.service.prepare(
            system.operation, worker_id=OTHER, runtime_generation_fingerprint=generation, occurred_at=NOW
        )
        == failed
    )


def test_current_claim_reference_never_allows_rebinding_after_stale_initial_read(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    initial = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    work = system.operation.reserved_run_id.value
    system.runtime.bind_new_work_exact(
        work, GENERATION, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
    )
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        system.runtime.require_work_binding_evidence(work)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, initial, reference)
    system.bindings.clear()
    system.runtime.bind_new_work_exact.reset_mock()
    # Only the initial read is stale; claim returns the authoritative RUNTIME_BOUND relation.
    monkeypatch.setattr(system.adapter, "load_verified", Mock(return_value=initial))
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    system.runtime.bind_new_work_exact.assert_not_called()
    assert system.bindings == {}
    assert OnlyPostgresChartCalculationPreparationStore(postgres_dsn).load_verified(system.operation) == bound


def test_claimed_historical_exact_binding_is_never_adopted(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.bind_work_exact(system.operation.reserved_run_id.value, GENERATION, actor="foreign", occurred_at=NOW)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == claim
    system.runtime.release_work.assert_not_called()


def test_input_path_requires_persisted_original_binding_reference(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    original = system.market.service.plan_selection

    def selected(*args, **kwargs):
        persisted = system.adapter.load_verified(system.operation)
        assert persisted.runtime_binding_reference is not None
        proof = system.runtime.require_work_binding_evidence(system.operation.reserved_run_id.value)
        persisted.runtime_binding_reference.verifies(proof, require_active=True)
        return original(*args, **kwargs)

    monkeypatch.setattr(system.market.service, "plan_selection", selected)
    ready = prepare(system)
    assert ready.runtime_binding_reference is not None
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM chart_calculation_preparation_fact WHERE kind = 'RUNTIME_BOUND'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "field,value", (("binding_event_fingerprint", "f" * 64), ("binding_sequence", 2), ("binding_actor", "other"))
)
def test_binding_substitution_after_durable_reference_fails_closed(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    ready = prepare(system)
    assert ready.runtime_binding_reference is not None
    setattr(system.bindings[system.operation.reserved_run_id.value], field, value)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)


def test_prebind_failure_proves_runtime_closure_before_failed_fact(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.require_new_work_generation.side_effect = ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK")
    original = system.adapter.fail

    def fail(operation, claim, code, **kwargs):
        proof = system.runtime.require_work_admission_closure_evidence(operation.reserved_run_id.value)
        assert proof.closure_reason == code
        return original(operation, claim, code, **kwargs)

    monkeypatch.setattr(system.adapter, "fail", fail)
    failed = prepare(system)
    assert failed.runtime_closure_reference is not None
    with pytest.raises(ValueError, match="RUNTIME_WORK_ADMISSION_CLOSED"):
        system.runtime.bind_new_work_exact(
            system.operation.reserved_run_id.value,
            GENERATION,
            owner="CHART_CALCULATION_INPUT",
            actor="stale",
            occurred_at=NOW,
        )


def test_stale_fence_after_runtime_bind_cannot_select_market_input(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    original = system.runtime.bind_new_work_exact.side_effect

    def late_bind(*args, **kwargs):
        result = original(*args, **kwargs)
        system.clock[0] += timedelta(minutes=3)
        system.adapter.claim(system.operation, OTHER, GENERATION, lease_duration=timedelta(minutes=2))
        return result

    system.runtime.bind_new_work_exact.side_effect = late_bind
    selection = Mock(wraps=system.market.service.plan_selection)
    monkeypatch.setattr(system.market.service, "plan_selection", selection)
    with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
        prepare(system)
    selection.assert_not_called()
    assert not (tmp_path / "dataset").exists()
    assert system.runtime.require_work_binding(system.operation.reserved_run_id.value).active


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
    decided = adapter.begin_failure(operation, first, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE")
    closure = OnlyRuntimeWorkAdmissionClosureEvidence(
        operation.reserved_run_id.value,
        GENERATION,
        "CHART_CALCULATION_INPUT",
        "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
        "test",
        "9" * 64,
        1,
    )
    failed = adapter.fail(operation, decided, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", closure_reference=closure)
    assert failed.state == "FAILED" and failed.revision == 3
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
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    period: int = 20,
    acquire: bool = True,
    catalog_witness=None,
    price_field="CLOSE",
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
    raw = payload({"period": period, "price_field": price_field})
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
        witness() if catalog_witness is None else catalog_witness,
        accepted_at=NOW,
    ).operation
    adapter = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    clock = [NOW]
    monkeypatch.setattr(adapter, "_now", lambda connection: clock[0])
    runtime = Mock(spec=OnlyRuntimeGenerationWorkAuthority)
    bindings = {}
    closures = {}

    def load_binding(work):
        if work not in bindings:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
        return bindings[work]

    def bind_exact(work, generation, **kwargs):
        if work in closures and work not in bindings:
            raise ValueError("RUNTIME_WORK_ADMISSION_CLOSED")
        existing = bindings.get(work)
        if existing is not None and existing.runtime_generation_fingerprint != generation:
            raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
        binding = existing or SimpleNamespace(
            work_id=work,
            runtime_generation_fingerprint=generation,
            active=True,
            binding_kind="EXACT",
            binding_owner=None,
            binding_actor=kwargs.get("actor", "test"),
            binding_event_fingerprint="d" * 64,
            binding_sequence=1,
        )
        bindings[work] = binding
        return binding

    def require_work(work, generation):
        binding = load_binding(work)
        if not binding.active or binding.runtime_generation_fingerprint != generation:
            raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")
        return runtime.require_runtime_generation(generation)

    runtime.require_work_binding.side_effect = load_binding

    def load_evidence(work):
        binding = load_binding(work)
        try:
            return OnlyRuntimeWorkBindingEvidence(**vars(binding))
        except (ValueError, TypeError):
            return binding  # Simulate a malformed Authority response, not certified absence.

    runtime.require_work_binding_evidence.side_effect = load_evidence
    runtime.require_work_generation.side_effect = require_work
    catalog = operation.catalog_witness.to_dict()["context"]["catalog_generation_fingerprint"]
    runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint=GENERATION, catalog_generation_fingerprint=catalog
    )
    runtime.require_new_work_generation.return_value = runtime.require_runtime_generation.return_value
    runtime.require_historical_generation.return_value = runtime.require_runtime_generation.return_value
    runtime.hold_work_binding_evidence.side_effect = lambda work: nullcontext(load_evidence(work))

    def release(work, **kwargs):
        binding = load_binding(work)
        bindings[work] = SimpleNamespace(**{**vars(binding), "active": False})
        return bindings[work]

    runtime.release_work.side_effect = release
    runtime.bind_work_exact.side_effect = bind_exact
    active_generation = [GENERATION]

    def bind_new_exact(work, generation, **kwargs):
        if work in closures:
            raise ValueError("RUNTIME_WORK_ADMISSION_CLOSED")
        existing = bindings.get(work)
        if existing is not None:
            if (
                existing.runtime_generation_fingerprint != generation
                or not existing.active
                or existing.binding_kind != "NEW_WORK"
                or existing.binding_owner != kwargs["owner"]
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            return existing
        if generation != active_generation[0]:
            raise ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK")
        binding = SimpleNamespace(
            work_id=work,
            runtime_generation_fingerprint=generation,
            active=True,
            binding_kind="NEW_WORK",
            binding_owner=kwargs["owner"],
            binding_actor=kwargs["actor"],
            binding_event_fingerprint="e" * 64,
            binding_sequence=1,
        )
        bindings[work] = binding
        return binding

    runtime.bind_new_work_exact = Mock(side_effect=bind_new_exact)

    def load_closure(work):
        if work not in closures:
            raise ValueError("RUNTIME_WORK_ADMISSION_NOT_CLOSED")
        return closures[work]

    def close(work, generation, *, owner, closure_reason, actor, **kwargs):
        if work in closures:
            evidence = closures[work]
            if (evidence.runtime_generation_fingerprint, evidence.binding_owner, evidence.closure_reason) != (
                generation,
                owner,
                closure_reason,
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            return evidence
        if work in bindings:
            evidence = load_evidence(work)
            if (
                evidence.runtime_generation_fingerprint != generation
                or evidence.binding_kind != "NEW_WORK"
                or evidence.binding_owner != owner
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            runtime.release_work(work, actor=actor, **kwargs)
        evidence = OnlyRuntimeWorkAdmissionClosureEvidence(work, generation, owner, closure_reason, actor, "9" * 64, 2)
        closures[work] = evidence
        return evidence

    runtime.close_new_work_exact.side_effect = close
    runtime.require_work_admission_closure_evidence.side_effect = load_closure
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
        closures=closures,
        active_generation=active_generation,
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
    system.runtime.bind_new_work_exact.assert_called_with(
        system.operation.reserved_run_id.value,
        GENERATION,
        owner="CHART_CALCULATION_INPUT",
        actor="chart-input-preparation",
        occurred_at=NOW,
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
def test_failure_decision_precedes_release_and_unknown_response_converges(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_response: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    original = system.runtime.release_work.side_effect

    def unavailable(work, **kwargs):
        decision = system.adapter.load_verified(system.operation)
        assert (
            decision.state == "MATERIALIZING_INPUT" and decision.failure_decision == "CHART_SEALED_COVERAGE_UNAVAILABLE"
        )
        assert decision.runtime_binding_reference is not None
        if lost_response:
            original(work, **kwargs)
        raise OSError("release response lost")

    system.runtime.release_work.side_effect = unavailable
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE"):
        prepare(system)
    decision = system.adapter.load_verified(system.operation)
    assert decision.state == "MATERIALIZING_INPUT" and decision.failure_decision == "CHART_SEALED_COVERAGE_UNAVAILABLE"
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
    system.clock[0] += timedelta(minutes=3)
    failed = prepare(system, OTHER)
    assert failed.state == "FAILED" and failed.runtime_closure_reference is not None
    assert not system.runtime.require_work_binding(system.operation.reserved_run_id.value).active
    assert prepare(system) == failed
    assert system.adapter.load_verified(system.operation).revision == failed.revision


def test_exact_active_binding_recovery_ignores_current_activation(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    system.runtime.bind_new_work_exact(
        system.operation.reserved_run_id.value,
        GENERATION,
        owner="CHART_CALCULATION_INPUT",
        actor="recovery",
        occurred_at=NOW,
    )
    system.runtime.bind_work_exact.reset_mock()
    system.runtime.bind_new_work_exact.reset_mock()
    system.runtime.require_new_work_generation.side_effect = AssertionError("bound recovery read activation")
    result = prepare(system)
    assert result.state == "INPUT_READY"
    assert system.runtime.require_work_binding(system.operation.reserved_run_id.value).active
    assert prepare(system) == result
    system.runtime.release_work.assert_not_called()
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.bind_new_work_exact.assert_not_called()


@pytest.mark.parametrize("ready", (False, True))
def test_nonterminal_or_input_ready_inactive_binding_fails_closed(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    if ready:
        previous = prepare(system)
    else:
        previous = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
        system.runtime.bind_new_work_exact(
            system.operation.reserved_run_id.value,
            GENERATION,
            owner="CHART_CALCULATION_INPUT",
            actor="recovery",
            occurred_at=NOW,
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
        system.adapter.begin_failure(system.operation, old, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE")
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
    system.runtime.bind_new_work_exact.side_effect = lambda *a, **kw: SimpleNamespace(
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
        system.adapter.begin_failure(system.operation, first, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE")
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
    system.runtime.require_work_binding_evidence.side_effect = None
    system.runtime.require_work_binding_evidence.return_value = SimpleNamespace(
        work_id=system.operation.reserved_run_id.value, runtime_generation_fingerprint=generation, active=active
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
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
    system.runtime.require_work_binding_evidence.side_effect = None
    system.runtime.require_work_binding_evidence.return_value = response
    system.runtime.bind_work_exact.reset_mock()
    system.runtime.release_work.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()


@pytest.mark.parametrize("active", (True, False))
def test_binding_without_preparation_is_never_adopted_or_released(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    system.bindings[system.operation.reserved_run_id.value] = SimpleNamespace(
        work_id=system.operation.reserved_run_id.value,
        runtime_generation_fingerprint=GENERATION,
        active=active,
    )
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("orphan touched Market"))
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) is None
    system.runtime.bind_new_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()


@pytest.mark.parametrize("active", (True, False))
def test_prebind_failure_rejects_later_binding_without_releasing_foreign_work(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    failed = system.service._fail(system.operation, claim, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", NOW)
    assert prepare(system) == failed
    system.bindings[system.operation.reserved_run_id.value] = SimpleNamespace(
        work_id=system.operation.reserved_run_id.value,
        runtime_generation_fingerprint=GENERATION,
        active=active,
    )
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == failed
    system.runtime.release_work.assert_not_called()


def test_postbind_failure_never_accepts_missing_historical_binding(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    failed = prepare(system)
    system.bindings.clear()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == failed


def test_activation_switch_after_precheck_cannot_admit_old_generation(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)

    def early_check(generation):
        system.active_generation[0] = "c" * 64
        return system.runtime.require_runtime_generation.return_value

    system.runtime.require_new_work_generation.side_effect = early_check
    result = prepare(system)
    assert result.failure_code == "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
    assert system.bindings == {}
    system.runtime.bind_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()


def test_claimed_unbound_recovery_uses_atomic_new_work_admission(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    result = prepare(system)
    assert result.state == "INPUT_READY"
    system.runtime.bind_new_work_exact.assert_called_once_with(
        system.operation.reserved_run_id.value,
        GENERATION,
        owner="CHART_CALCULATION_INPUT",
        actor="chart-input-preparation",
        occurred_at=NOW,
    )
    system.runtime.bind_work_exact.assert_not_called()


@pytest.mark.parametrize("bound", (False, True))
def test_unknown_failure_decision_cannot_authorize_binding_release(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: bool
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    if bound:
        system.runtime.bind_work_exact(
            system.operation.reserved_run_id.value, GENERATION, actor="test", occurred_at=NOW
        )
    with pytest.raises(ValueError, match="CHART_PREPARATION_FAILURE_CODE_INVALID"):
        system.adapter.begin_failure(system.operation, claim, "CHART_UNCLASSIFIED_FAILURE")
    assert system.adapter.load_verified(system.operation) == claim
    system.runtime.release_work.assert_not_called()


@pytest.mark.parametrize("terminal", (False, True))
@pytest.mark.parametrize("kind,owner", (("EXACT", None), ("NEW_WORK", "OTHER_FAMILY")))
def test_foreign_binding_family_cannot_be_adopted_or_released(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool, kind: str, owner: str | None
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    if terminal:
        previous = prepare(system)
    else:
        previous = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
        system.runtime.bind_work_exact(
            system.operation.reserved_run_id.value, GENERATION, actor="foreign", occurred_at=NOW
        )
    binding = system.bindings[system.operation.reserved_run_id.value]
    binding.binding_kind, binding.binding_owner = kind, owner
    system.runtime.release_work.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == previous
    system.runtime.release_work.assert_not_called()


def test_terminal_closure_blocks_stale_bind_and_allows_retirement(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
    from tests.runtime_support.generation_support import only_ready_test_generation

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "runtime")
    other = only_ready_test_generation(registry, "a", NOW)
    manifest = replace(
        registry.load_manifest(other),
        catalog_generation_fingerprint=system.operation.catalog_witness.to_dict()["context"][
            "catalog_generation_fingerprint"
        ],
    )
    registry.prepare(manifest, actor="test", occurred_at=NOW)
    registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="test", occurred_at=NOW)
    generation = manifest.runtime_generation_fingerprint
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    system.service._runtime = registry
    original = OnlyRuntimeGenerationRegistry.bind_new_work_exact

    def stale_bind(self, *args, **kwargs):
        system.clock[0] += timedelta(minutes=3)
        registry.activate_for_new_work(expected_current=generation, target=other, actor="operator", occurred_at=NOW)
        winner = system.adapter.claim(system.operation, OTHER, generation, lease_duration=timedelta(minutes=2))
        system.service._fail(system.operation, winner, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", NOW)
        registry.activate_for_new_work(expected_current=other, target=generation, actor="operator", occurred_at=NOW)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "bind_new_work_exact", stale_bind)
    selection = Mock(side_effect=AssertionError("stale worker read Market"))
    monkeypatch.setattr(system.market.service, "plan_selection", selection)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        system.service.prepare(
            system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
        )
    failed = system.adapter.load_verified(system.operation)
    assert failed.failure_code == "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
    proof = registry.require_work_admission_closure_evidence(system.operation.reserved_run_id.value)
    assert proof.binding_owner == "CHART_CALCULATION_INPUT"
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_UNBOUND"):
        registry.require_work_binding_evidence(system.operation.reserved_run_id.value)
    selection.assert_not_called()
    assert not (tmp_path / "dataset").exists()
    registry.activate_for_new_work(expected_current=generation, target=other, actor="operator", occurred_at=NOW)
    registry.retire(generation, actor="operator", occurred_at=NOW)
    system.service._runtime = OnlyRuntimeGenerationRegistry(tmp_path / "runtime")
    assert (
        system.service.prepare(
            system.operation, worker_id=OTHER, runtime_generation_fingerprint=generation, occurred_at=NOW
        )
        == failed
    )


def test_crash_after_binding_before_claim_recheck_recovers_owned_work(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    original = system.runtime.bind_new_work_exact.side_effect

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("process loss after append")

    system.runtime.bind_new_work_exact.side_effect = crash
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        prepare(system)
    system.runtime.bind_new_work_exact.side_effect = original
    system.runtime.require_new_work_generation.side_effect = AssertionError("bound retry read activation")
    system.clock[0] += timedelta(minutes=3)
    assert prepare(system, OTHER).state == "INPUT_READY"
    system.runtime.release_work.assert_not_called()


@pytest.mark.parametrize(
    "field,value", (("binding_event_fingerprint", "f" * 64), ("binding_sequence", 2), ("binding_actor", "other"))
)
def test_terminal_release_reread_must_preserve_original_event_evidence(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    original = system.runtime.release_work.side_effect

    def changed_release(work, **kwargs):
        result = original(work, **kwargs)
        setattr(system.bindings[work], field, value)
        return result

    system.runtime.release_work.side_effect = changed_release
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation).state == "FAILED"


def test_fence_loss_after_binding_replays_winners_input_ready_without_stale_reads(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    original = system.runtime.bind_new_work_exact.side_effect
    selection = Mock(wraps=system.market.service.plan_selection)
    monkeypatch.setattr(system.market.service, "plan_selection", selection)
    winner = []

    def bind_then_complete(*args, **kwargs):
        result = original(*args, **kwargs)
        system.clock[0] += timedelta(minutes=3)
        winner.append(prepare(system, OTHER))
        return result

    system.runtime.bind_new_work_exact.side_effect = bind_then_complete
    assert prepare(system) == winner[0]
    assert winner[0].state == "INPUT_READY"
    assert selection.call_count == 1
    system.runtime.release_work.assert_not_called()


def test_current_fence_must_persist_binding_before_pin_or_ready(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    pin = Mock()
    with pytest.raises(ValueError, match="CHART_PREPARATION_RELATION_CORRUPT"):
        system.adapter.commit_pin(system.operation, claim, pin)
    pin.verify_operation.assert_not_called()
    with pytest.raises(ValueError, match="CHART_PREPARATION_RELATION_CORRUPT"):
        system.adapter.input_ready(
            system.operation,
            claim,
            snapshot_fingerprint="a" * 64,
            materialization_id="dataset-materialization:" + "a" * 64,
        )
    work = system.operation.reserved_run_id.value
    system.runtime.bind_new_work_exact(
        work, GENERATION, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
    )
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        system.runtime.require_work_binding_evidence(work)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, claim, reference)
    assert bound.fence == claim.fence and bound.revision == claim.revision + 1
    assert system.adapter.commit_runtime_binding(system.operation, bound, reference) == bound


@pytest.mark.parametrize("cut", ("decision", "release", "closure"))
def test_durable_failure_decision_recovers_every_closure_cut_without_input_reads(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    if cut == "decision":
        original = system.adapter.begin_failure

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("process loss after decision commit")

        monkeypatch.setattr(system.adapter, "begin_failure", crash)
    elif cut == "release":
        original_release = system.runtime.release_work.side_effect

        def crash_release(*args, **kwargs):
            original_release(*args, **kwargs)
            raise OSError("process loss after release commit")

        system.runtime.release_work.side_effect = crash_release
    else:
        original_close = system.runtime.close_new_work_exact.side_effect

        def crash_close(*args, **kwargs):
            original_close(*args, **kwargs)
            raise OSError("process loss after closure commit")

        system.runtime.close_new_work_exact.side_effect = crash_close
    with pytest.raises((OSError, ValueError)):
        prepare(system)
    decision = system.adapter.load_verified(system.operation)
    assert decision.state == "MATERIALIZING_INPUT" and decision.failure_decision == "CHART_SEALED_COVERAGE_UNAVAILABLE"
    assert decision.runtime_binding_reference is not None
    # Reclaim from fresh PostgreSQL reader: durable decision alone determines recovery.
    system.clock[0] += timedelta(minutes=3)
    restarted = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    monkeypatch.setattr(restarted, "_now", lambda connection: system.clock[0])
    system.service._store = restarted
    if cut == "release":
        system.runtime.release_work.side_effect = original_release
    if cut == "closure":
        system.runtime.close_new_work_exact.side_effect = original_close
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("closing worker read Market"))
    )
    monkeypatch.setattr(
        system.materializer,
        "materialize_with_lineage",
        Mock(side_effect=AssertionError("closing worker wrote Dataset")),
    )
    failed = prepare(system, OTHER)
    assert failed.state == "FAILED" and failed.runtime_closure_reference is not None
    assert failed.runtime_binding_reference == decision.runtime_binding_reference
    assert not system.runtime.require_work_binding(system.operation.reserved_run_id.value).active
    assert (
        system.runtime.require_work_admission_closure_evidence(system.operation.reserved_run_id.value)
        == failed.runtime_closure_reference
    )


def test_v1_claim_can_append_runtime_bound_without_rewriting_history(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationPreparationV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    legacy = OnlyChartCalculationPreparationV1(
        system.operation.operation_id,
        1,
        1,
        WORKER,
        NOW + timedelta(minutes=2),
        GENERATION,
        system.operation.reserved_run_id.value,
        fact_schema_version=1,
    )
    with psycopg.connect(postgres_dsn) as connection:
        system.adapter._append(connection, legacy, "CLAIM", None)
        before = connection.execute(
            "SELECT fact_json, fact_fingerprint FROM chart_calculation_preparation_fact WHERE revision = 1"
        ).fetchone()
    assert system.adapter.load_verified(system.operation) == legacy
    ready = prepare(system)
    assert ready.fact_schema_version == 2 and ready.runtime_binding_reference is not None
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute(
                "SELECT fact_json, fact_fingerprint FROM chart_calculation_preparation_fact WHERE revision = 1"
            ).fetchone()
            == before
        )


def test_v1_input_ready_is_readable_but_cannot_be_silently_backfilled(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from onlyalpha.persistence.postgres.chart_calculation_preparation_store import _decode, _payload

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    ready = prepare(system)
    legacy = replace(ready, fact_schema_version=1, runtime_binding_reference=None)
    assert _decode(_payload(legacy), 1) == legacy
    historical = Mock()
    historical.load_verified.return_value = legacy
    system.service._store = historical
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    historical.claim.assert_not_called()
    historical.commit_runtime_binding.assert_not_called()


@pytest.mark.parametrize("cut", ("RuntimeWorkReleased", "RuntimeNewWorkClosed"))
def test_fresh_runtime_and_postgres_recover_durable_closing_decision(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
    from tests.runtime_support.generation_support import only_ready_test_generation

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    root = tmp_path / "closing-runtime"
    registry = OnlyRuntimeGenerationRegistry(root)
    other = only_ready_test_generation(registry, "a", NOW)
    manifest = replace(
        registry.load_manifest(other),
        catalog_generation_fingerprint=system.operation.catalog_witness.to_dict()["context"][
            "catalog_generation_fingerprint"
        ],
    )
    registry.prepare(manifest, actor="test", occurred_at=NOW)
    registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="test", occurred_at=NOW)
    generation = manifest.runtime_generation_fingerprint
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    system.service._runtime = registry
    original = OnlyRuntimeGenerationRegistry._append

    def process_loss(self, event):
        original(self, event)
        if event.kind == cut:
            raise OSError("process death after Runtime fsync")

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "_append", process_loss)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE"):
        system.service.prepare(
            system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
        )
    decided = system.adapter.load_verified(system.operation)
    assert decided.state == "MATERIALIZING_INPUT" and decided.failure_decision == "CHART_SEALED_COVERAGE_UNAVAILABLE"
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "_append", original)
    system.clock[0] += timedelta(minutes=3)
    restarted = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    monkeypatch.setattr(restarted, "_now", lambda connection: system.clock[0])
    system.service._store = restarted
    fresh_runtime = OnlyRuntimeGenerationRegistry(root)
    system.service._runtime = fresh_runtime
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("recovery read Market"))
    )
    monkeypatch.setattr(
        system.materializer, "materialize_with_lineage", Mock(side_effect=AssertionError("recovery wrote Dataset"))
    )
    failed = system.service.prepare(
        system.operation, worker_id=OTHER, runtime_generation_fingerprint=generation, occurred_at=NOW
    )
    assert failed.runtime_binding_reference == decided.runtime_binding_reference
    assert failed.state == "FAILED" and failed.runtime_closure_reference is not None
    assert not fresh_runtime.require_work_binding(system.operation.reserved_run_id.value).active
    fresh_runtime.activate_for_new_work(expected_current=generation, target=other, actor="operator", occurred_at=NOW)
    fresh_runtime.retire(generation, actor="operator", occurred_at=NOW)


def test_durable_failure_decision_fences_successor_after_original_session_is_gone(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    original = system.runtime.close_new_work_exact.side_effect
    winners = []

    def after_decision_before_runtime(*args, **kwargs):
        # begin_failure has committed and closed its PG session; no volatile lock protects A.
        system.runtime.close_new_work_exact.side_effect = original
        decision = system.adapter.load_verified(system.operation)
        assert decision.failure_decision == "CHART_SEALED_COVERAGE_UNAVAILABLE"
        system.clock[0] += timedelta(minutes=3)
        fresh = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
        monkeypatch.setattr(fresh, "_now", lambda connection: system.clock[0])
        winner_claim = fresh.claim(system.operation, OTHER, GENERATION, lease_duration=timedelta(minutes=2))
        with pytest.raises(ValueError, match="CHART_PREPARATION_RELATION_CORRUPT"):
            fresh.input_ready(
                system.operation,
                winner_claim,
                snapshot_fingerprint="a" * 64,
                materialization_id="dataset-materialization:" + "a" * 64,
            )
        winners.append(prepare(system, OTHER))
        return original(*args, **kwargs)

    system.runtime.close_new_work_exact.side_effect = after_decision_before_runtime
    with pytest.raises(ValueError, match="CHART_PREPARATION_FENCE_LOST"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == winners[0]
    assert winners[0].state == "FAILED"
    assert winners[0].runtime_closure_reference is not None
    assert not system.runtime.require_work_binding(system.operation.reserved_run_id.value).active


@pytest.mark.parametrize("boundary", ("claim", "heartbeat"))
def test_returned_claim_or_heartbeat_failure_decision_bypasses_input_reads(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationRuntimeBindingReferenceV1

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    claim = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    work = system.operation.reserved_run_id.value
    system.runtime.bind_new_work_exact(
        work, GENERATION, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
    )
    reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(
        system.runtime.require_work_binding_evidence(work)
    )
    bound = system.adapter.commit_runtime_binding(system.operation, claim, reference)
    original = getattr(system.adapter, boundary)

    def decide_between_reads(*args, **kwargs):
        system.adapter.begin_failure(system.operation, bound, "CHART_SEALED_COVERAGE_UNAVAILABLE")
        if boundary == "claim":
            system.clock[0] += timedelta(minutes=3)
        return original(*args, **kwargs)

    monkeypatch.setattr(system.adapter, boundary, decide_between_reads)
    monkeypatch.setattr(
        system.market.service, "plan_selection", Mock(side_effect=AssertionError("decision reached Market"))
    )
    monkeypatch.setattr(
        system.materializer, "materialize_with_lineage", Mock(side_effect=AssertionError("decision reached Dataset"))
    )
    failed = prepare(system, OTHER if boundary == "claim" else WORKER)
    assert failed.state == "FAILED" and failed.failure_code == "CHART_SEALED_COVERAGE_UNAVAILABLE"
    assert failed.runtime_binding_reference == bound.runtime_binding_reference
    assert failed.runtime_closure_reference is not None


@pytest.mark.parametrize(
    "field,value", (("closure_event_fingerprint", "f" * 64), ("closure_sequence", 3), ("closure_actor", "other"))
)
def test_terminal_replay_rejects_substitution_of_persisted_closure_event(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    from dataclasses import replace

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, acquire=False)
    failed = prepare(system)
    assert failed.runtime_closure_reference is not None
    work = system.operation.reserved_run_id.value
    system.closures[work] = replace(system.closures[work], **{field: value})
    system.runtime.close_new_work_exact.reset_mock()
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        prepare(system)
    assert system.adapter.load_verified(system.operation) == failed
    system.runtime.close_new_work_exact.assert_not_called()
