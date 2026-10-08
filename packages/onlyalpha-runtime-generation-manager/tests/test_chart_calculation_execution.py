"""Isolated installed host evidence with deterministic fixture data, never customer runs."""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module, metadata
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_execution import (
    OnlyChartCalculationExecutionService,
)
from onlyalpha.application.chart_calculation_run_admission import only_chart_calculation_queued_run
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationExecutionMismatch,
    OnlyHistoricalGenerationUnavailable,
    OnlyHistoricalGenerationWorkerUnavailable,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.research.run.model import OnlyResearchRunState

pytestmark = pytest.mark.contract


@pytest.fixture
def postgres_dsn():
    import psycopg

    from onlyalpha.persistence.postgres import only_assert_postgres_test_database

    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    return dsn


@pytest.fixture(scope="module")
def exact_host_environment(tmp_path_factory):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider
    from onlyalpha_runtime_generation_manager import (
        OnlyHistoricalGenerationHostManager,
        OnlyLocalImmutableArtifactStore,
        OnlyRuntimeGenerationBuilder,
    )

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
    from onlyalpha.runtime.generation import (
        OnlyArtifactSourceProvenanceAuthority,
        OnlyCoreExecutionIdentity,
        OnlyDistributionArtifactRole,
    )

    root = tmp_path_factory.mktemp("exact-chart-host")
    helpers = import_module(f"{__package__}.test_builder")
    repository = Path(__file__).resolve().parents[3]
    wheels = [
        helpers._build_wheel(repository, root / "core"),
        helpers._build_wheel(repository / "packages/onlyalpha-runtime-generation-manager", root / "manager"),
        helpers._build_wheel(repository / "plugs/onlyalpha-plugin-indicators", root / "indicators"),
        helpers._installed_distribution_wheel("pyarrow", root / "arrow"),
        helpers._installed_distribution_wheel("pyyaml", root / "yaml"),
    ]
    authority = OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
    core = helpers._plain_artifact(
        wheels[0],
        role=OnlyDistributionArtifactRole.CORE,
        authority=authority,
        repository="OnlyAlpha",
        revision="1" * 40,
    )
    identity = OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)
    provider = quant_asset_provider()
    indicator = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="2" * 40,
        artifact_logical_name=wheels[2].name,
        artifact_bytes=wheels[2].read_bytes(),
        tested_core_execution_fingerprint=identity.fingerprint,
        provider=provider,
    )
    manager = helpers._plain_artifact(
        wheels[1],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=authority,
        repository="OnlyAlpha",
        revision="3" * 40,
    )
    arrow = helpers._plain_artifact(
        wheels[3],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision="release-" + metadata.version("pyarrow"),
    )
    yaml = helpers._plain_artifact(
        wheels[4],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="PyYAML",
        revision="release-" + metadata.version("pyyaml"),
    )
    artifacts = (core, manager, indicator, arrow, yaml)
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    for artifact, wheel in zip(artifacts, wheels, strict=True):
        store.put_once(artifact, wheel.read_bytes())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    built = builder.build_validated(
        artifacts=artifacts,
        expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
        environment_root=root / "built",
    )
    return builder, built, OnlyHistoricalGenerationHostManager


@pytest.fixture
def hosted_chart(exact_host_environment, tmp_path):
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    builder, built, manager_type = exact_host_environment
    helpers = import_module(f"{__package__}.test_calculation_publication_resolution")
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
    now = datetime(2026, 10, 8, tzinfo=UTC)
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="fixture", occurred_at=now)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=now)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=now)
    host = manager_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")

    def create(*, period=3, price_field="CLOSE"):
        chart, _, compilation = helpers._compile_chart_in_exact_host(
            tmp_path, registry, builder, generation, host, period=period, price_field=price_field
        )
        chart.operations = Mock()
        chart.operations.load_verified.return_value = chart.operation
        chart.runs = Mock()
        chart.run = only_chart_calculation_queued_run(compilation, queued_at=chart.operation.accepted_at)
        chart.runs.load_verified.return_value = chart.run
        chart.runs.hold_queued_run.side_effect = lambda *args: nullcontext(chart.runs.load_verified.return_value)
        chart.compilation = compilation
        chart.runtime = registry
        chart.host = host
        chart.now = now
        chart.execution = OnlyChartCalculationExecutionService(
            operations=chart.operations,
            preparations=chart.preparations,
            compilations=chart.compilations,
            datasets=chart.dataset,
            materializations=chart.dataset,
            runtime_generations=registry,
            runs=chart.runs,
            host=host,
            dataset_store_root=str(tmp_path / "chart-input" / "dataset"),
        )
        return chart

    try:
        yield create
    finally:
        host.close()


@pytest.mark.parametrize(
    ("period", "field", "value"),
    [(3, "CLOSE", "101"), (3, "VOLUME", "2"), (1, "CLOSE", "101"), (1, "VOLUME", "2"), (5, "CLOSE", "101")],
)
def test_actual_exact_host_numeric_and_rowwise_readiness(hosted_chart, monkeypatch, period, field, value):
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

    chart = hosted_chart(period=period, price_field=field)
    dataset_files = {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("receiver attempted current Registry/executor")

    monkeypatch.setattr(OnlyResearchSpecificationResolver, "resolve", forbidden)
    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden)
    result = chart.execution.execute(chart.operation.operation_id)
    count = period + 3
    assert result.values.column("value").to_pylist() == [Decimal(value)] * count
    assert result.readiness.column("readiness").to_pylist() == ["PARTIAL"] * (period - 1) + ["READY"] * 4
    assert result.readiness.column("reason").to_pylist() == ["WARMUP_INCOMPLETE"] * (period - 1) + ["NONE"] * 4
    verified = chart.dataset.load_verified_table(chart.compilation.dataset_snapshot_fingerprint)
    assert result.values.column("ts_event_ns").to_pylist() == verified.table.column("ts_event_ns").to_pylist()
    assert result.request.compilation == chart.compilation
    assert result.status == "EXECUTED_UNPUBLISHED"
    assert chart.runs.load_verified(chart.operation) == chart.run
    chart.runs.commit_or_replay.assert_not_called()
    assert {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()} == dataset_files
    assert chart.execution.execute(chart.operation.operation_id).to_dict() == result.to_dict()


def test_general_host_entry_never_accepts_numeric_wire_dto(hosted_chart):
    chart = hosted_chart()
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        chart.host.execute(
            OnlySearchGenerationExecutionRequestV1(
                chart.compilation.runtime_generation_fingerprint,
                OnlySearchGenerationOperationV1.EXECUTE_CHART_CALCULATION_PROJECTION,
                chart.compilation.to_dict(),
            )
        )
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_UNAUTHORIZED"):
        chart.host.execute_chart_calculation({"compilation": chart.compilation.to_dict()})


@pytest.mark.parametrize(
    "mutation", ["compilation", "generation", "capability", "work_release", "cancel_run", "cancel_request", "host_loss"]
)
def test_exact_host_negative_paths_never_return_success(hosted_chart, monkeypatch, mutation):
    from tests.research.postgres.test_chart_calculation_compilation import different_compilation

    chart = hosted_chart()
    host = chart.host
    cancellation = Event()
    if mutation == "compilation":
        chart.compilations.load_verified.return_value = different_compilation(chart.compilation)
        chart.runs.load_verified.return_value = only_chart_calculation_queued_run(
            chart.compilations.load_verified.return_value, queued_at=chart.run.queued_at
        )
    elif mutation == "generation":
        monkeypatch.setattr(
            host, "_verify_handshake", lambda *args: (_ for _ in ()).throw(OnlyHistoricalGenerationUnavailable())
        )
        host.evict(chart.compilation.runtime_generation_fingerprint)
    elif mutation == "capability":
        worker = host._workers[chart.compilation.runtime_generation_fingerprint]
        worker.handshake = replace(
            worker.handshake,
            supported_capabilities=(OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_CALCULATION_PUBLICATION,),
        )
    else:
        exchange = host._exchange_chart

        def interrupted(process, request, cancel, **kwargs):
            response = exchange(process, request, cancel, **kwargs)
            if mutation == "work_release":
                chart.runtime.release_work(chart.run.run_id.value, actor="fixture", occurred_at=chart.now)
            elif mutation == "cancel_run":
                chart.runs.load_verified.return_value = chart.run.transition(
                    OnlyResearchRunState.CANCELLED, at=chart.now
                )
            elif mutation == "cancel_request":
                cancellation.set()
            else:
                host._terminate(process)
            return response

        monkeypatch.setattr(host, "_exchange_chart", interrupted)
    with pytest.raises(
        (
            OnlyChartCalculationError,
            OnlyHistoricalGenerationExecutionMismatch,
            OnlyHistoricalGenerationUnavailable,
            OnlyHistoricalGenerationCapabilityUnsupported,
            OnlyHistoricalGenerationWorkerUnavailable,
        )
    ):
        chart.execution.execute(chart.operation.operation_id, cancellation=cancellation)
    chart.runs.commit_or_replay.assert_not_called()


def test_retired_compilation_is_readable_but_never_numeric_permission(hosted_chart):
    from tests.runtime_support.generation_support import only_ready_test_generation

    chart = hosted_chart()
    generation = chart.compilation.runtime_generation_fingerprint
    chart.runtime.release_work(chart.run.run_id.value, actor="fixture", occurred_at=chart.now)
    other = only_ready_test_generation(chart.runtime, "e", chart.now)
    chart.runtime.activate_for_new_work(
        expected_current=generation, target=other, actor="fixture", occurred_at=chart.now
    )
    chart.runtime.retire(generation, actor="fixture", occurred_at=chart.now)
    assert chart.compilations.load_verified(chart.operation) == chart.compilation
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)


def test_same_generation_complete_other_occurrence_response_is_rejected(hosted_chart, monkeypatch):
    from onlyalpha.application.search_generation_execution import OnlySearchGenerationExecutionResponseV1

    chart = hosted_chart()
    exchange = chart.host._exchange_chart

    def swapped(process, request, cancellation, **kwargs):
        raw = exchange(process, request, cancellation, **kwargs)
        raw["result_payload"]["run_id"] = "00000000-0000-4000-8000-000000000999"
        # A valid outer hash is not ownership proof.
        return OnlySearchGenerationExecutionResponseV1(
            raw["runtime_generation_fingerprint"],
            OnlySearchGenerationOperationV1(raw["operation_kind"]),
            raw["result_payload"],
        ).to_dict()

    monkeypatch.setattr(chart.host, "_exchange_chart", swapped)
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)


def test_hosted_period_one_zero_is_ready_numeric_zero(hosted_chart, monkeypatch):
    from onlyalpha.domain.value import OnlyQuantity
    from tests.application.test_market_data_product import _FakeSource

    original = _FakeSource._update

    def zero_input(source, start_ns, bar_type):
        update = original(source, start_ns, bar_type)
        bar = replace(update.payload.bar, volume=OnlyQuantity(Decimal("0"), 5))
        return replace(update, payload=replace(update.payload, bar=bar))

    monkeypatch.setattr(_FakeSource, "_update", zero_input)
    chart = hosted_chart(period=1, price_field="VOLUME")
    result = chart.execution.execute(chart.operation.operation_id)
    assert result.values.column("value").to_pylist() == [Decimal("0")] * 4
    assert result.readiness.column("readiness").to_pylist() == ["READY"] * 4
    assert result.readiness.column("reason").to_pylist() == ["NONE"] * 4


def test_hosted_sma_partial_and_full_windows_have_exact_nonconstant_numeric_parity(hosted_chart, monkeypatch):
    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.domain.value import OnlyQuantity
    from tests.application.test_market_data_product import BASE, MINUTE_NS, _FakeSource

    original = _FakeSource._update
    start = OnlyTimestamp.from_datetime(BASE).unix_nanos

    def nonconstant_input(source, start_ns, bar_type):
        update = original(source, start_ns, bar_type)
        index = (start_ns - start) // (15 * MINUTE_NS)
        bar = replace(update.payload.bar, volume=OnlyQuantity(Decimal(index * 2), 5))
        return replace(update, payload=replace(update.payload, bar=bar))

    monkeypatch.setattr(_FakeSource, "_update", nonconstant_input)
    chart = hosted_chart(period=3, price_field="VOLUME")
    result = chart.execution.execute(chart.operation.operation_id)
    assert result.values.column("value").to_pylist() == [Decimal(value) for value in ("0", "1", "2", "4", "6", "8")]
    assert result.readiness.column("readiness").to_pylist() == [
        "PARTIAL",
        "PARTIAL",
        "READY",
        "READY",
        "READY",
        "READY",
    ]
    assert result.readiness.column("reason").to_pylist() == [
        "WARMUP_INCOMPLETE",
        "WARMUP_INCOMPLETE",
        "NONE",
        "NONE",
        "NONE",
        "NONE",
    ]


def test_missing_snapshot_partition_fails_without_repair_or_numeric_response(hosted_chart):
    chart = hosted_chart()
    snapshot = chart.dataset.load(chart.compilation.dataset_snapshot_fingerprint)
    partition = chart.dataset._target(snapshot.snapshot_fingerprint) / snapshot.partitions[0].relative_path
    before = partition.read_bytes()
    partition.write_bytes(before[:-1])  # Test-owned immutable fixture corruption injection.
    with pytest.raises(OnlyChartCalculationError):
        chart.execution.execute(chart.operation.operation_id)
    assert partition.read_bytes() == before[:-1]
    chart.runs.commit_or_replay.assert_not_called()


def test_host_loss_restarts_same_generation_without_cached_success(hosted_chart):
    chart = hosted_chart()
    result = chart.execution.execute(chart.operation.operation_id)
    generation = chart.compilation.runtime_generation_fingerprint
    old = chart.host._workers[generation]
    chart.host._terminate(old.process)
    repeated = chart.execution.execute(chart.operation.operation_id)
    assert repeated.to_dict() == result.to_dict()
    assert chart.host._workers[generation] is not old


def test_numeric_host_rejects_busy_work_without_queueing_or_run_mutation(hosted_chart):
    chart = hosted_chart()
    chart.host._chart_execution_lock.acquire()
    try:
        with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable, match="busy"):
            chart.execution.execute(chart.operation.operation_id)
    finally:
        chart.host._chart_execution_lock.release()
    chart.runs.commit_or_replay.assert_not_called()
    assert chart.execution.execute(chart.operation.operation_id).status == "EXECUTED_UNPUBLISHED"


def test_numeric_acquisition_never_rebuilds_after_environment_eviction(hosted_chart, monkeypatch):
    chart = hosted_chart()
    generation = chart.compilation.runtime_generation_fingerprint
    chart.host.evict(generation, delete_environment=True)
    monkeypatch.setattr(chart.host, "_rebuild", lambda *args: pytest.fail("numeric entry must not install"))
    with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable, match="not prepared"):
        chart.execution.execute(chart.operation.operation_id)
    chart.runs.commit_or_replay.assert_not_called()


def test_release_between_final_read_and_pipe_is_refused_by_owning_dispatch_fence(hosted_chart, monkeypatch):
    chart = hosted_chart()
    exchange = chart.host._exchange_chart

    def released_before_fence(process, request, cancellation, **kwargs):
        chart.runtime.release_work(chart.run.run_id.value, actor="fixture", occurred_at=chart.now)
        return exchange(process, request, cancellation, **kwargs)

    monkeypatch.setattr(chart.host, "_exchange_chart", released_before_fence)
    pipe_fd = chart.host._workers[chart.compilation.runtime_generation_fingerprint].process.stdin.fileno()
    original_write = os.write

    def reject_numeric_write(fd, payload):
        if fd == pipe_fd:
            pytest.fail("released-before-dispatch work must not send")
        return original_write(fd, payload)  # The injected owning release must persist.

    monkeypatch.setattr("onlyalpha_runtime_generation_manager.host_manager.os.write", reject_numeric_write)
    with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable):
        chart.execution.execute(chart.operation.operation_id)


def test_numeric_request_copy_replacement_and_reuse_have_no_dispatch_permission(hosted_chart):
    import copy

    chart = hosted_chart()
    host = chart.host

    class ObservingPort:
        def execute_chart_calculation(self, capability, *, cancellation):
            for forged in (copy.copy(capability), replace(capability), capability.request.to_dict()):
                with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_UNAUTHORIZED"):
                    host.execute_chart_calculation(forged, cancellation=cancellation)
            projection = host.execute_chart_calculation(capability, cancellation=cancellation)
            with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_UNAUTHORIZED"):
                host.execute_chart_calculation(capability, cancellation=cancellation)
            return projection

    chart.execution._host = ObservingPort()
    assert chart.execution.execute(chart.operation.operation_id).status == "EXECUTED_UNPUBLISHED"


@pytest.mark.postgres
@pytest.mark.integration
# Requires the controlled PostgreSQL test-profile service, unlike the package's
# database-free private-asset contract lane. No public network is used.
@pytest.mark.external
@pytest.mark.parametrize(
    "fault", ["none", "swapped_response", "release", "host_loss", "cancel_request", "contended_run"]
)
def test_postgres_owning_chain_through_real_isolated_host_is_readonly(
    exact_host_environment, postgres_dsn, tmp_path, monkeypatch, fault
):
    import psycopg
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
    from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader
    from psycopg import sql

    from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
    from onlyalpha.application.chart_calculation import OnlyChartCalculationCatalogWitnessV1
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
    from onlyalpha.application.chart_calculation_run_admission import OnlyChartCalculationRunAdmissionService
    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from tests.application.test_chart_calculation_admission import NOW
    from tests.research.postgres import test_chart_calculation_preparation as preparation_fixtures

    builder, built, manager_type = exact_host_environment
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "runtime")
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="fixture", occurred_at=NOW)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=NOW)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=NOW)
    reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(registry, builder, tmp_path / "catalog")
    query = OnlyExactCatalogContextQueryService(reader, reader, reader, reader, readiness=reader)
    catalog = built.manifest.catalog_generation_fingerprint
    witness = OnlyChartCalculationCatalogWitnessV1.from_projections(
        query.get_exact_catalog_context(catalog), query.get_exact_catalog_readiness(catalog)
    )
    monkeypatch.setattr(preparation_fixtures, "witness", lambda: witness)
    system = preparation_fixtures.prepared_system(postgres_dsn, tmp_path, monkeypatch, period=3)
    system.service._runtime = registry
    ready = system.service.prepare(
        system.operation,
        worker_id=preparation_fixtures.WORKER,
        runtime_generation_fingerprint=generation,
        occurred_at=NOW,
    )
    assert ready.state == "INPUT_READY"
    host = manager_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
    compilations = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    runs = OnlyPostgresChartCalculationRunAdmissionStore(postgres_dsn, runtime_generations=registry)
    try:
        frozen = OnlyChartCalculationCompilationService(
            preparations=system.adapter,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            resolver=OnlyResearchHostedRuntimeGenerationResolver(
                execution=host, dataset_store_root=str(tmp_path / "dataset")
            ),
            compilations=compilations,
        ).compile(system.operation)
        run = OnlyChartCalculationRunAdmissionService(
            preparations=system.adapter,
            compilations=compilations,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            runs=runs,
        ).admit(system.operation, queued_at=NOW)
        service = OnlyChartCalculationExecutionService(
            operations=OnlyPostgresChartCalculationAdmissionStore(postgres_dsn),
            preparations=system.adapter,
            compilations=compilations,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            runs=runs,
            host=host,
            dataset_store_root=str(tmp_path / "dataset"),
        )

        def facts():
            with psycopg.connect(postgres_dsn) as connection:
                return {
                    table: connection.execute(
                        sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text").format(
                            sql.Identifier(table)
                        )
                    ).fetchall()
                    for table in (
                        "product_command_admission",
                        "product_command_receipt",
                        "chart_calculation_operation",
                        "chart_calculation_preparation_fact",
                        "chart_calculation_compilation",
                        "chart_calculation_run_admission",
                        "research_run_id_reservation",
                        "research_run",
                        "research_run_attempt",
                        "research_source_history",
                    )
                }

        before = facts()
        dataset = {path: path.read_bytes() for path in system.dataset._root.rglob("*") if path.is_file()}
        cancellation = Event()
        exchange = host._exchange_chart

        def injected(process, request, cancel, **kwargs):
            if "dispatch_guard" in kwargs:
                from contextlib import contextmanager

                original_guard = kwargs["dispatch_guard"]

                @contextmanager
                def checked_guard():
                    with original_guard:
                        # A concurrent cancellation update cannot commit until the
                        # complete request is sent, without any global command lock.
                        with psycopg.connect(postgres_dsn) as other:
                            with pytest.raises(psycopg.errors.LockNotAvailable):
                                other.execute(
                                    "SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE NOWAIT",
                                    (run.run_id.value,),
                                )
                        yield

                kwargs["dispatch_guard"] = checked_guard()
            response = exchange(process, request, cancel, **kwargs)
            # The same owning row is not held while waiting for/after output.
            with psycopg.connect(postgres_dsn) as other:
                other.execute("SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE NOWAIT", (run.run_id.value,))
            if fault == "swapped_response":
                from onlyalpha.application.search_generation_execution import OnlySearchGenerationExecutionResponseV1

                response["result_payload"]["operation_id"] = "00000000-0000-4000-8000-000000000998"
                return OnlySearchGenerationExecutionResponseV1(
                    response["runtime_generation_fingerprint"],
                    OnlySearchGenerationOperationV1(response["operation_kind"]),
                    response["result_payload"],
                ).to_dict()
            if fault == "release":
                registry.release_work(run.run_id.value, actor="fixture", occurred_at=NOW)
            elif fault == "host_loss":
                host._terminate(process)
            elif fault == "cancel_request":
                cancellation.set()
            return response

        monkeypatch.setattr(host, "_exchange_chart", injected)
        if fault == "none":
            result = service.execute(system.operation.operation_id, cancellation=cancellation)
            assert result.values.column("value").to_pylist() == [Decimal("101")] * 6
            assert result.readiness.column("readiness").to_pylist() == [
                "PARTIAL",
                "PARTIAL",
                "READY",
                "READY",
                "READY",
                "READY",
            ]
            assert result.readiness.column("reason").to_pylist() == [
                "WARMUP_INCOMPLETE",
                "WARMUP_INCOMPLETE",
                "NONE",
                "NONE",
                "NONE",
                "NONE",
            ]
            assert result.request.compilation == frozen
        elif fault == "contended_run":
            from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError

            with psycopg.connect(postgres_dsn) as cancellation_writer:
                cancellation_writer.execute(
                    "SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE", (run.run_id.value,)
                )
                with pytest.raises(OnlyProductCommandAuthorityUnavailableError):
                    service.execute(system.operation.operation_id, cancellation=cancellation)
        else:
            with pytest.raises((OnlyChartCalculationError, OnlyHistoricalGenerationWorkerUnavailable)):
                service.execute(system.operation.operation_id, cancellation=cancellation)
        assert facts() == before
        assert before["research_run_attempt"] == []
        assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
        assert run.state is OnlyResearchRunState.QUEUED and run.revision == 0
        assert run.research_result_fingerprint is None and run.artifact_content_fingerprint is None
        assert run.calculation_execution_evidence_fingerprints == ()
        assert {path: path.read_bytes() for path in system.dataset._root.rglob("*") if path.is_file()} == dataset
    finally:
        host.close()
