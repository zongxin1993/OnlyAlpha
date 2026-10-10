"""Real PG/ClickHouse owning readers in an exact installed publication process.

This proves Source composition, not a Chart ACTIVE Attempt or terminal lifecycle.
The database remains default-closed and every Run/Attempt byte is retained.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
from onlyalpha.application.chart_calculation import OnlyChartCalculationCatalogWitnessV1
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.persistence.clickhouse.client import OnlyClickHouseClient
from onlyalpha.persistence.clickhouse.config import OnlyClickHouseConfig, only_assert_clickhouse_test_database
from onlyalpha.persistence.clickhouse.market_data_store import OnlyClickHouseMarketFactStore
from onlyalpha.persistence.clickhouse.migration import OnlyClickHouseMigrationAuthority
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
    OnlyPostgresChartCalculationRunAdmissionStore,
)
from onlyalpha.plugin.integration import OnlyIntegrationTypeId
from onlyalpha.research.artifact import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
from tests.application.test_market_data_product import _FakeSource
from tests.research.postgres import test_chart_calculation_preparation as preparation_tests
from tests.research.postgres.test_chart_calculation_native_publication import _provision_schema_reference
from tests.research.postgres.test_chart_native_publication_permissions import runtime_login, snapshot
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment
from tests.runtime_support.chart_execution_host import materialize_exact_host_environment

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse]

_INSTALLED_PUBLICATION = r"""
import json, sys
from datetime import UTC, datetime
from pathlib import Path
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.clickhouse.config import OnlyClickHouseConfig
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import OnlyPostgresChartCalculationCompilationStore
from onlyalpha_runtime_generation_manager.chart_native_source import only_chart_native_input_export
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.artifact_store import OnlyLocalImmutableArtifactStore
from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_result, only_publish_native_calculation_artifact

# This file is the test launcher's private configuration, not a Chart IPC request.
cfg = json.loads(Path(sys.argv[1]).read_text())
root = Path(cfg['root'])
export = only_chart_native_input_export(
    postgres_reader_dsn=cfg['dsn'], clickhouse_reader=OnlyClickHouseConfig(**cfg['clickhouse']),
    dataset_root=root/'chart-input'/'dataset', runtime_registry_root=root/'registry')
operation = OnlyPostgresChartCalculationAdmissionStore(cfg['dsn']).load_verified(OnlyProductCommandId(cfg['operation']))
compiled = OnlyPostgresChartCalculationCompilationStore(cfg['dsn']).load_verified(operation)
issued = export.export(operation.operation_id)
kwargs = dict(generations=OnlyRuntimeGenerationRegistry(root/'registry'),
    distribution_artifact_store=OnlyLocalImmutableArtifactStore(Path(cfg['distribution_artifacts'])),
    frozen=compiled.resolution, dataset_store_root=root/'chart-input'/'dataset',
    calculation_result_root=root/'calculation-results', execution_evidence_root=root/'semantic',
    research_result_root=root/'research-results', audit_time=lambda: datetime(2026,10,10,tzinfo=UTC))
result, producer = only_publish_native_calculation_result(**kwargs)
artifact = only_publish_native_calculation_artifact(**kwargs,
    research_artifact_root=root/'artifacts', verified_input=issued)
print(json.dumps(dict(result=result.manifest.research_result_fingerprint,
    artifact=artifact.manifest.artifact_content_fingerprint, evidence=producer.evidence_fingerprint)))
"""


@pytest.mark.parametrize("period", [3, 1])
def test_installed_source_bootstrap_issues_in_process_without_operational_authority(
    postgres_dsn, exact_host_environment, tmp_path, monkeypatch, period
):
    from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader

    admin = OnlyClickHouseClient(OnlyClickHouseConfig.from_environment())
    name = "onlyalpha_test_chart_source_" + uuid.uuid4().hex
    only_assert_clickhouse_test_database(name)
    user = "chart_source_" + uuid.uuid4().hex
    config = replace(admin.config, database=name)
    writer = OnlyClickHouseClient(config)
    try:
        OnlyClickHouseMigrationAuthority(writer).migrate()
        admin.execute(f"CREATE USER {user} IDENTIFIED WITH no_password SETTINGS readonly=1", database="default")
        admin.execute(f"GRANT SELECT ON {name}.* TO {user}", database="default")
        reader_config = replace(config, user=user, password="")
        physical = OnlyClickHouseMarketFactStore(writer)
        original_service = preparation_tests._service

        def service(*args, **kwargs):
            system = original_service(*args, **kwargs)
            system.service._facts = physical
            system.provider.canonical_writes = lambda: int(
                writer.query_json("SELECT count() AS n FROM market_bar")[0]["n"]
            )
            return system

        monkeypatch.setattr(preparation_tests, "_service", service)
        original_update = _FakeSource._update

        def recorded_update(source, start_ns, bar_type):
            update = original_update(source, start_ns, bar_type)
            volume = (0, 0, 2, 5, 0, 1)[(start_ns // (15 * 60_000_000_000)) % 6]
            return replace(
                update,
                payload=replace(
                    update.payload, bar=replace(update.payload.bar, volume=OnlyQuantity(Decimal(volume), 5))
                ),
            )

        monkeypatch.setattr(_FakeSource, "_update", recorded_update)
        builder, built, host_type, template = exact_host_environment
        registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
        now = datetime(2026, 10, 10, tzinfo=UTC)
        generation = built.manifest.runtime_generation_fingerprint
        registry.prepare(built.manifest, actor="fixture", occurred_at=now)
        registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=now)
        registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=now)
        catalog_reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(registry, builder, tmp_path / "catalog")
        query = OnlyExactCatalogContextQueryService(
            catalog_reader, catalog_reader, catalog_reader, catalog_reader, readiness=catalog_reader
        )
        catalog = built.manifest.catalog_generation_fingerprint
        witness = OnlyChartCalculationCatalogWitnessV1.from_projections(
            query.get_exact_catalog_context(catalog), query.get_exact_catalog_readiness(catalog)
        )
        system = preparation_tests.prepared_system(
            postgres_dsn,
            tmp_path / "chart-input",
            monkeypatch,
            period=period,
            price_field="VOLUME",
            catalog_witness=witness,
        )
        system.service._runtime = registry
        ready = system.service.prepare(
            system.operation,
            worker_id=preparation_tests.WORKER,
            runtime_generation_fingerprint=generation,
            occurred_at=now,
        )
        assert ready.state == "INPUT_READY"
        materialize_exact_host_environment(template, generation, tmp_path / "hosts")
        host = host_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
        try:
            compiled = OnlyChartCalculationCompilationService(
                preparations=system.adapter,
                datasets=system.dataset,
                materializations=system.dataset,
                runtime_generations=registry,
                resolver=OnlyResearchHostedRuntimeGenerationResolver(
                    execution=host, dataset_store_root=str(system.dataset._root)
                ),
                compilations=OnlyPostgresChartCalculationCompilationStore(postgres_dsn),
            ).compile(system.operation)
        finally:
            host.close()
        run = OnlyPostgresChartCalculationRunAdmissionStore(
            postgres_dsn, runtime_generations=registry
        ).commit_or_replay(system.operation, compiled, queued_at=system.operation.accepted_at)
        pin = ready.input_pin
        revision, seal = system.market.catalog.load_sealed_revision(pin.revision_id)
        ids = tuple(item[0] for item in revision.segment_refs)
        pg_catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
        segments = system.market.catalog.load_durable_segments(ids)
        pg_catalog.commit_durable_segments(segments, system.market.catalog.load_physical_proofs(ids))
        pg_catalog.commit_revision(
            segments, system.market.catalog.load_coverage_manifest(revision.manifest_id), revision, seal
        )
        integration = system.market.state.load_revision(system.market.revision_fingerprint)
        integration_store = OnlyPostgresIntegrationStore(postgres_dsn)
        integration_store.create_integration(
            OnlyIntegrationId(integration.integration_id.value),
            OnlyIntegrationTypeId(integration.type_id),
            "recorded test source",
        )
        integration_store.insert_revision(integration, ())
        python = builder.artifact_store.root.parent / "built" / "bin" / "python"
        _provision_schema_reference(python)
        (tmp_path / "semantic").mkdir()
        (tmp_path / "artifacts").mkdir()
        before = snapshot(postgres_dsn)
        source_bytes = {p: p.read_bytes() for p in system.dataset._root.rglob("*") if p.is_file()}
        registry_bytes = {p: p.read_bytes() for p in registry.root.rglob("*") if p.is_file()}
        with runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as dsn:
            private_config = tmp_path / "launcher.json"
            private_config.write_text(
                json.dumps(
                    {
                        "dsn": dsn,
                        "clickhouse": asdict(reader_config),
                        "root": str(tmp_path),
                        "operation": system.operation.operation_id.value,
                        "distribution_artifacts": str(builder.artifact_store.root),
                    }
                )
            )
            private_config.chmod(0o600)
            completed = subprocess.run(
                [str(python), "-I", "-c", _INSTALLED_PUBLICATION, str(private_config)],
                check=True,
                text=True,
                capture_output=True,
                timeout=60,
            )
        receipt = json.loads(completed.stdout)
        artifact = OnlyParquetResearchCalculationArtifactStoreV2(tmp_path / "artifacts").load_verified(
            receipt["artifact"], research_result_fingerprint=receipt["result"]
        )
        calculation = next(iter(artifact.calculations.values()))
        assert run.run_id.value == compiled.runtime_work_id != system.operation.operation_id.value
        assert artifact.manifest.selected_evidence[0].evidence_fingerprint == receipt["evidence"]
        values = calculation.outputs[0].table["value"].to_pylist()
        readiness = calculation.readiness[0].table.to_pylist()
        if period == 1:
            assert values == artifact.dataset_table["volume"].to_pylist()
            assert values[:2] == [Decimal(0), Decimal(0)]
            assert all(row["readiness"] == "READY" and row["reason"] == "NONE" for row in readiness)
        else:
            assert values == [Decimal(v) for v in ("0", "0", "0.666666666667", "2.333333333333", "2.333333333333", "2")]
            assert [row["readiness"] for row in readiness] == ["PARTIAL", "PARTIAL", "READY", "READY", "READY", "READY"]
        assert before == snapshot(postgres_dsn)
        assert source_bytes == {p: p.read_bytes() for p in system.dataset._root.rglob("*") if p.is_file()}
        assert registry_bytes == {p: p.read_bytes() for p in registry.root.rglob("*") if p.is_file()}
    finally:
        admin.execute(f"DROP USER IF EXISTS {user}", database="default")
        admin.execute(f"DROP DATABASE IF EXISTS {name}", database="default")
