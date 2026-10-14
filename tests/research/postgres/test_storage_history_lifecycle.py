from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresCredentialAuthority,
    OnlyPostgresResearchDeploymentStore,
    only_ensure_dev_master_key,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research import OnlyParquetResearchScientificArtifactStoreV3
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreIdentity
from tests.research.artifact.support import scientific_artifact_v3_case
from tests.research.postgres.migration_support import copy_migrations_through, current_migrations

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _database_history(dsn: str) -> tuple:
    with psycopg.connect(dsn) as connection:
        return (
            connection.execute("SELECT * FROM research_deployment_semantic_store_binding").fetchall(),
            connection.execute("SELECT * FROM product_credential ORDER BY credential_id").fetchall(),
        )


def _prepare(dsn: str, root: Path) -> dict[str, object]:
    layout = OnlyUserDataLayout(root)
    identity = OnlyResearchSemanticStoreIdentity(layout.research_root).initialize()
    OnlyPostgresResearchDeploymentStore(dsn).initialize(identity)
    key = only_ensure_dev_master_key(root / MASTER_KEY_FILE)
    credentials = OnlyPostgresCredentialAuthority(dsn, key)
    slot = credentials.create(
        "INTEGRATION_SECRET", "b52eb762-34cf-47d4-8cca-56ef93f0d2ac", "api_key", "controlled-history-value"
    )
    _, candidate, _ = scientific_artifact_v3_case(root)
    store = OnlyParquetResearchScientificArtifactStoreV3(
        layout.research_artifact_root, audit_time=lambda: datetime(2026, 10, 14, tzinfo=UTC)
    )
    store.commit(candidate)
    artifact = store.load_verified(candidate.result.manifest.research_result_fingerprint)
    assert credentials.read_secret(slot.credential_id, slot.generation) == "controlled-history-value"
    return {
        "root": str(root),
        "store_id": str(identity),
        "credential_id": slot.credential_id,
        "credential_generation": slot.generation,
        "result_fingerprint": candidate.result.manifest.research_result_fingerprint,
        "artifact_fingerprint": candidate.artifact_content_fingerprint,
        "sections": [section.to_dict() for section in artifact.manifest.sections],
    }


def _read(expected: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.runtime_support.storage_history_reader"],
        input=json.dumps(expected),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_forward_schema_upgrade_and_fresh_processes_preserve_usable_history(postgres_dsn: str, tmp_path: Path) -> None:
    # Real prior canonical schema -> current canonical schema; no legacy reader,
    # fallback, empty-store replacement or business-dev data preparation.
    previous = tmp_path / "previous-schema"
    previous.mkdir()
    migrations = current_migrations()
    copy_migrations_through(previous, migrations[-2])
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=previous).migrate()
    root = tmp_path / "user_data"
    expected = _prepare(postgres_dsn, root)
    files, rows = _files(root), _database_history(postgres_dsn)
    current = OnlyPostgresMigrationAuthority(postgres_dsn)
    assert current.migrate() == (migrations[-1],)
    assert _database_history(postgres_dsn) == rows
    for _ in range(2):
        loaded = _read(expected)
        assert loaded.returncode == 0, loaded.stderr
        assert loaded.stdout.strip() == "VERIFIED_HISTORY_LOADED"
        assert _files(root) == files
        assert _database_history(postgres_dsn) == rows
    assert current.migrate() == ()


@pytest.mark.parametrize("mutation", ["namespace", "missing-key", "wrong-key", "missing-artifact", "corrupt-artifact"])
def test_incomplete_history_is_refused_not_initialized_or_recomputed(
    postgres_dsn: str, tmp_path: Path, mutation: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    root = tmp_path / "user_data"
    expected = _prepare(postgres_dsn, root)
    if mutation == "namespace":
        path = OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(root).research_root).path
        payload = json.loads(path.read_text())
        payload["store_id"] = "46c26a0e-796e-4c57-90b6-7c4a7506912f"
        path.write_text(json.dumps(payload))
    elif mutation == "missing-key":
        (root / MASTER_KEY_FILE).unlink()
    elif mutation == "wrong-key":
        (root / MASTER_KEY_FILE).write_bytes(b"w" * 32)
    else:
        identity = str(expected["result_fingerprint"])
        path = (
            OnlyUserDataLayout(root).research_artifact_root
            / "research-scientific-v3"
            / "sha256"
            / identity[:2]
            / identity
            / "market.parquet"
        )
        assert path.is_file()
        if mutation == "missing-artifact":
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b"corrupt")
    files, rows = _files(root), _database_history(postgres_dsn)
    loaded = _read(expected)
    assert loaded.returncode != 0
    assert "VERIFIED_HISTORY_LOADED" not in loaded.stdout
    assert {
        "namespace": "SEMANTIC_STORE_IDENTITY_MISMATCH",
        "missing-key": "CREDENTIAL_MASTER_KEY_MISSING",
        "wrong-key": "CREDENTIAL_CIPHERTEXT_INVALID",
        "missing-artifact": "ARTIFACT_CORRUPT",
        "corrupt-artifact": "ARTIFACT_CORRUPT",
    }[mutation] in loaded.stderr
    assert _files(root) == files
    assert _database_history(postgres_dsn) == rows
