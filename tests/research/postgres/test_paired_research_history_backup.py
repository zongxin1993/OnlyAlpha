"""Retained paired-history backup proof; this is not Research Product acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchRunStore,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.research_run_store import _COLUMNS, _insert_run_query
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchArtifactProfileReader,
    OnlyResearchArtifactStoreError,
    OnlyResearchResultStoreError,
)
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentCoherenceVerifier,
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.run.evidence import (
    only_research_admission_resolution_fingerprint,
)
from scripts.database import _backup, _initialize_deployment, _restore_test
from tests.certification.research_product.support import (
    provision_product_api_master_key,
)
from tests.research.artifact.support import scientific_artifact_case
from tests.research.postgres.test_postgres_authority import NOW

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _semantic_readers(root: Path):  # type: ignore[no-untyped-def]
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    return (
        OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations),
        OnlyResearchArtifactProfileReader(layout.research_artifact_root),
    )


def test_paired_database_files_and_key_restore_exact_history_and_reject_missing_or_corrupt_proofs(
    postgres_dsn: str, tmp_path: Path
) -> None:
    only_assert_postgres_test_database(postgres_dsn)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    master_key_path = provision_product_api_master_key(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    resolved, candidate, artifact_store = scientific_artifact_case(tmp_path)
    artifact_outcome = artifact_store.commit(candidate)
    shutil.copytree(tmp_path / "scientific-artifacts", layout.research_artifact_root, dirs_exist_ok=True)
    result = candidate.result.manifest.research_result_fingerprint
    artifact = artifact_outcome.artifact_content_fingerprint
    # Establish controlled existing history, not the deferred user goal of submitting Research.
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000008601"),
        specification=resolved.specification,
        canonical_specification_payload=only_canonical_json(resolved.specification.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(
            resolved.specification_resolution
        ),
        queued_at=NOW,
    )
    historical_running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    completed = historical_running.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=2),
        research_result_fingerprint=result,
        artifact_content_fingerprint=artifact,
    )
    # Explicit historical fixture insertion establishes the backup's existing input.
    # Do not call a current Command/Execution writer or pretend a Research submission.
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(_insert_run_query(_COLUMNS), OnlyPostgresResearchRunStore._values(completed))
    result_reader, source_artifact_reader = _semantic_readers(tmp_path)
    source_result = result_reader.load_verified(resolved.workload.result_plan.fingerprint)
    source_artifact = source_artifact_reader.load_verified(result)
    backup = tmp_path.parent / f"{tmp_path.name}.dump"
    metadata_path = _backup(postgres_dsn, backup)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    tdb = datetime.fromisoformat(metadata["created_at"])
    assert metadata["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    restore_root = tmp_path.parent / f"{tmp_path.name}-restored"
    shutil.copytree(tmp_path, restore_root)
    restored_master_key_path = OnlyUserDataLayout(restore_root).root / MASTER_KEY_FILE
    assert master_key_path.is_file()
    assert restored_master_key_path.is_file()
    assert restored_master_key_path.read_bytes() == master_key_path.read_bytes()
    tfs = datetime.now(UTC)
    assert tfs >= tdb
    target_name = "onlyalpha_restore_test"
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + f"/{target_name}"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (target_name,))
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        _restore_test(postgres_dsn, target_dsn, backup, queued.run_id.value)
        restored_run = OnlyPostgresResearchRunStore(target_dsn).load(queued.run_id)
        assert restored_run == completed
        assert restored_run.state.value == "COMPLETED"
        assert restored_run.research_result_fingerprint == result
        assert restored_run.artifact_content_fingerprint == artifact
        assert OnlyResearchDeploymentCoherenceVerifier(
            OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(restore_root).research_root),
            OnlyPostgresResearchDeploymentStore(target_dsn),
        ).verify()
        result_reader, artifact_reader = _semantic_readers(restore_root)
        restored_result = result_reader.load_verified(resolved.workload.result_plan.fingerprint)
        restored_artifact = artifact_reader.load_verified(result)
        assert restored_result == source_result
        assert restored_artifact == source_artifact
        assert restored_result.manifest.research_result_fingerprint == result
        assert restored_artifact.manifest.artifact_content_fingerprint == artifact
        missing_result_root = tmp_path.parent / f"{tmp_path.name}-missing-result"
        shutil.copytree(restore_root, missing_result_root)
        shutil.rmtree(OnlyUserDataLayout(missing_result_root).research_result_root)
        with pytest.raises(OnlyResearchResultStoreError):
            _semantic_readers(missing_result_root)[0].load_verified(resolved.workload.result_plan.fingerprint)
        missing_artifact_root = tmp_path.parent / f"{tmp_path.name}-missing-artifact"
        shutil.copytree(restore_root, missing_artifact_root)
        shutil.rmtree(OnlyUserDataLayout(missing_artifact_root).research_artifact_root)
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(missing_artifact_root)[1].load_verified(result)
        corrupt_artifact_root = tmp_path.parent / f"{tmp_path.name}-corrupt-artifact"
        shutil.copytree(restore_root, corrupt_artifact_root)
        manifest = next(OnlyUserDataLayout(corrupt_artifact_root).research_artifact_root.rglob("*manifest.json"))
        manifest.write_text("{}", encoding="utf-8")
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(corrupt_artifact_root)[1].load_verified(result)
        with pytest.raises(OnlyResearchArtifactStoreError):
            artifact_reader.load_verified("f" * 64)
        incoherent_root = tmp_path.parent / f"{tmp_path.name}-incoherent"
        OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(incoherent_root).research_root).initialize()
        assert OnlyPostgresResearchRunStore(target_dsn).load(restored_run.run_id).state.value == "COMPLETED"
        with pytest.raises(OnlyResearchDeploymentError) as incoherent:
            OnlyResearchDeploymentCoherenceVerifier(
                OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(incoherent_root).research_root),
                OnlyPostgresResearchDeploymentStore(target_dsn),
            ).verify()
        assert incoherent.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(incoherent_root)[1].load_verified(result)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (target_name,)
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
