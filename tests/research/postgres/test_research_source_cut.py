"""Transactional source-owned history, including pre-migration baseline and later revisions."""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread

import psycopg
import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
)
from onlyalpha_http_server.main import _compose_experiment_memory_projection_builder, _GenerationOwnedCatalogReader
from onlyalpha_runtime_generation_manager import (
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
)
from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.private_asset_store import OnlyPostgresPrivateAssetStore
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.research_execution_store import OnlyPostgresResearchExecutionStore
from onlyalpha.persistence.postgres.research_run_store import _COLUMNS
from onlyalpha.persistence.postgres.research_source_cut_store import OnlyPostgresResearchSourceCutAuthority
from onlyalpha.quant_assets.private import OnlyPrivateAssetRevisionBindingResolver
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.factor_pair.result_store import OnlyParquetResearchFactorPairStatisticsResultStore
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.evaluation.summary.result_store import OnlyJsonResearchSummaryStatisticsResultStore
from onlyalpha.research.execution import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.experiment.store import OnlyJsonSearchProvenanceStore
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.source_cut import OnlySourceCutError
from onlyalpha.strategy.qualification_store import OnlyQualificationDecisionStore
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_memory_production_topology_certification import _build_exact_runtime_generation
from tests.research.postgres.test_postgres_authority import NOW, _queued
from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def test_transactional_run_cut_preserves_baseline_and_later_revision(postgres_dsn: str, tmp_path: Path) -> None:
    copy_migrations_through(tmp_path, "0022_product_command_admission_convergence")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    run = _queued("00000000-0000-4000-8000-000000000901")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run, columns=_COLUMNS[:-1])

    copy_migrations_through(tmp_path, "0023_research_source_closed_cut")
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate() == (
        "0023_research_source_closed_cut",
    )
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    old = source.capture_closed_cut("RESEARCH_RUN")
    assert old == source.capture_closed_cut("RESEARCH_RUN")
    assert old.cut_boundary == "JOURNAL_INDEX:1"
    assert len(old.entries) == 1

    # This test intentionally remains on the pre-0030 schema; use an explicit
    # historical fixture update instead of the current-schema production store.
    cancelled = run.transition(run.state.CANCELLED, at=run.queued_at)
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute(
                "UPDATE research_run SET revision = %s, state = %s, finished_at = %s "
                "WHERE run_id = %s AND revision = %s",
                (
                    cancelled.revision,
                    cancelled.state.value,
                    cancelled.finished_at,
                    run.run_id.value,
                    run.revision,
                ),
            ).rowcount
            == 1
        )
    newer = source.capture_closed_cut("RESEARCH_RUN")
    assert len(newer.entries) == 2
    assert source.load_closed_cut_verified(old.cut_fingerprint, "RESEARCH_RUN") == old
    assert source.load_closed_cut_verified(newer.cut_fingerprint, "RESEARCH_RUN") == newer
    historical = source.for_family("RESEARCH_RUN").iter_closed_cut_observations_verified(old.cut_fingerprint)
    assert len(historical) == 1
    assert historical[0].locator == old.entries[0].locator
    assert historical[0].content_fingerprint == old.entries[0].content_fingerprint
    assert historical[0].canonical_payload["source_row"]["revision"] == 0
    assert (
        source.iter_closed_cut_observations_verified(newer.cut_fingerprint, "RESEARCH_RUN")[1].canonical_payload[
            "source_row"
        ]["revision"]
        == 1
    )

    program = (
        "import sys\n"
        "from onlyalpha.persistence.postgres.research_source_cut_store import OnlyPostgresResearchSourceCutAuthority\n"
        "authority = OnlyPostgresResearchSourceCutAuthority(sys.argv[1])\n"
        "cut = authority.load_closed_cut_verified(sys.argv[2], 'RESEARCH_RUN')\n"
        "observations = authority.iter_closed_cut_observations_verified(sys.argv[2], 'RESEARCH_RUN')\n"
        "print(cut.cut_fingerprint, observations[0].canonical_payload['source_row']['revision'])\n"
    )
    assert (
        subprocess.check_output([sys.executable, "-c", program, postgres_dsn, old.cut_fingerprint], text=True).strip()
        == f"{old.cut_fingerprint} 0"
    )

    with psycopg.connect(postgres_dsn) as connection:
        rows = connection.execute(
            "SELECT event_index, operation, source_row ->> 'revision' FROM research_source_history ORDER BY event_index"
        ).fetchall()
        assert rows == [(1, "BASELINE", "0"), (2, "UPDATE", "1")]
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM research_source_history WHERE event_index = 1")


def test_postgres_source_cut_rejects_journal_gap(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("UPDATE research_source_history_frontier SET last_index = 2")
    with pytest.raises(OnlySourceCutError, match="SOURCE_CUT_JOURNAL_GAP"):
        source.capture_closed_cut("RESEARCH_RUN")


def test_attempt_and_product_admission_cuts_survive_later_changes(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = _queued("00000000-0000-4000-8000-000000000911")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    before = source.capture_closed_cut("RESEARCH_ATTEMPT")
    admission = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000912"),
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "a" * 64,
    )
    product = OnlyPostgresProductCommandAuthority(postgres_dsn)
    product.admit_exact(admission)
    admitted = source.capture_closed_cut("PRODUCT_COMMAND_ADMISSION")
    product.put_verified_receipt(
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run.run_id.value),
            NOW,
        )
    )
    received = source.capture_closed_cut("PRODUCT_COMMAND_RECEIPT")
    assert len(received.entries) == 1
    claim = OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000911"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000911"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    active = source.capture_closed_cut("RESEARCH_ATTEMPT")
    assert before.entries == () and len(active.entries) == 1
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    later = source.capture_closed_cut("RESEARCH_ATTEMPT")
    assert len(later.entries) == 2
    restarted = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    assert restarted.load_closed_cut_verified(active.cut_fingerprint, "RESEARCH_ATTEMPT") == active
    assert restarted.load_closed_cut_verified(admitted.cut_fingerprint, "PRODUCT_COMMAND_ADMISSION") == admitted
    assert restarted.load_closed_cut_verified(received.cut_fingerprint, "PRODUCT_COMMAND_RECEIPT") == received


def test_product_composition_captures_real_mixed_owner_topology(postgres_dsn: str, tmp_path: Path) -> None:
    """The canonical composition binds owner ports, including four real journal families."""
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    layout = OnlyUserDataLayout(tmp_path / "user-data")
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    pair = OnlyParquetResearchFactorPairStatisticsResultStore(layout.research_statistics_result_root, calculations)
    summary = OnlyJsonResearchSummaryStatisticsResultStore(
        layout.research_statistics_result_root, statistics, factor_pair_source_store=pair
    )
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    generations_root = tmp_path / "runtime-generations"
    generations, _catalog_generation, runtime_fingerprint = _build_exact_runtime_generation(generations_root)
    catalog = OnlyRuntimeGenerationExactCatalogDescriptorReader(
        generations,
        OnlyRuntimeGenerationBuilder(
            OnlyLocalImmutableArtifactStore(generations_root / "artifacts"), Path(sys.executable)
        ),
        generations_root / "catalog-context-cache",
    )
    search = OnlyJsonSearchProvenanceStore(
        layout.research_root, catalogs=_GenerationOwnedCatalogReader(), datasets=datasets
    )
    builder, _ = _compose_experiment_memory_projection_builder(
        layout=layout,
        postgres_dsn=postgres_dsn,
        search=search,
        results=results,
        statistics=statistics,
        factor_pair_statistics=pair,
        summary_statistics=summary,
        qualification_decisions=OnlyQualificationDecisionStore(layout.research_root),
        datasets=datasets,
        catalogs=catalog,
        calculations=calculations,
        runtime_generations=generations,
        authoring_generations=OnlyVerifiedAuthoringGenerationReader(
            OnlyAuthoringExecutionGenerationStore(tmp_path / "authoring-generations"),
            OnlyPrivateAssetRevisionBindingResolver(OnlyPostgresPrivateAssetStore(postgres_dsn)),
        ),
    )
    run = _queued("00000000-0000-4000-8000-000000000921")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)
    admission = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000922"),
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "a" * 64,
    )
    product = OnlyPostgresProductCommandAuthority(postgres_dsn)
    product.admit_exact(admission)
    product.put_verified_receipt(
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run.run_id.value),
            NOW,
        )
    )
    assert (
        OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
            worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000921"),
            attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000921"),
            lease_duration=timedelta(minutes=2),
            max_attempts=3,
            run_started_at=NOW + timedelta(seconds=1),
        )
        is not None
    )
    generations.bind_work_exact(
        run.run_id.value,
        runtime_fingerprint,
        actor="source-cut-test",
        occurred_at=NOW,
    )
    manifest = builder.capture_manifest()
    assert len(manifest.cuts) == 11
    assert all(
        len(builder._sources[cut.source_family].load_closed_cut_verified(cut.cut_fingerprint).entries) > 0
        for cut in manifest.cuts
        if cut.source_family
        in {"RESEARCH_RUN", "RESEARCH_ATTEMPT", "PRODUCT_COMMAND_ADMISSION", "PRODUCT_COMMAND_RECEIPT"}
    )
    projection = builder.publish_and_activate(manifest)
    assert projection.revision_fingerprint == builder._revisions.load_active_verified().revision_fingerprint


def test_postgres_capture_waits_for_uncommitted_writer(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = _queued("00000000-0000-4000-8000-000000000913")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    entered, release, done = Event(), Event(), Event()
    failures: list[Exception] = []

    def writer() -> None:
        try:
            with psycopg.connect(postgres_dsn) as connection:
                # A direct SQL writer is serialized by the source trigger.
                connection.execute(
                    "UPDATE research_run SET revision = revision + 1 WHERE run_id = %s",
                    (run.run_id.value,),
                )
                entered.set()
                assert release.wait(10)
        except Exception as exc:
            failures.append(exc)
        finally:
            done.set()

    thread = Thread(target=writer)
    thread.start()
    try:
        assert entered.wait(10)
        # The uncommitted trigger increment holds the frontier lock. Capture
        # can complete only after the writer's transaction commits.
        captured: list[object] = []
        capture = Thread(target=lambda: captured.append(source.capture_closed_cut("RESEARCH_RUN")))
        capture.start()
        release.set()
        assert done.wait(10)
        capture.join(10)
        assert not capture.is_alive() and not failures
        assert len(captured[0].entries) == 2  # type: ignore[attr-defined]
    finally:
        release.set()
        thread.join(10)
