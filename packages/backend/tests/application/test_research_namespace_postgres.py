"""Formal deployment initializer and real source cuts; no Shipping business steps are substituted."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import psycopg
import pytest

from onlyalpha.persistence.postgres import OnlyPostgresResearchDeploymentStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from packages.backend.tests.application.test_factor_proposals_postgres import grant as factor_grant
from scripts.database import _initialize_deployment
from scripts.native_http_contract import native_executable

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="session")
def initializer_backend() -> Path:
    # Existing canonical builder, current source, same single development profile.
    return native_executable(release=False)


def project(probe: Path, root: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)],
        input=json.dumps({"op": "research-namespace", "user_data": str(root)}),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def test_formal_operator_fresh_and_restart_use_the_same_bound_identity_and_actual_pg_history(
    initializer_backend, native_probe, postgres_dsn, tmp_path
):
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    identity = _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity
    before = (tmp_path / "research/.onlyalpha-semantic-store.json").read_bytes()
    assert _initialize_deployment(postgres_dsn, tmp_path, initializer_backend) == identity
    assert (tmp_path / "research/.onlyalpha-semantic-store.json").read_bytes() == before
    initial = project(native_probe, tmp_path)
    assert "error" not in initial, initial
    # This is a real original Command owner operation in the isolated technical namespace.
    # It does not create a Factor, Research Run or scientific result.
    factor_grant(native_probe, postgres_dsn)
    captured = project(native_probe, tmp_path)
    assert "error" not in captured, captured
    assert captured != initial
    pin = captured["projection_fingerprint"]
    projection = json.loads(
        (tmp_path / f"research/experiment-memory/revisions/sha256/{pin[:2]}/{pin}/projection.json").read_text()
    )
    with psycopg.connect(postgres_dsn) as db:
        for family in ["PRODUCT_COMMAND_ADMISSION", "PRODUCT_COMMAND_RECEIPT"]:
            cut = next(c for c in projection["source_manifest"]["cuts"] if c["source_family"] == family)
            row = db.execute(
                "SELECT canonical_document FROM research_source_closed_cut WHERE cut_fingerprint=%s",
                (cut["cut_fingerprint"],),
            ).fetchone()
            assert row is not None and len(json.loads(row[0])["entries"]) > 0


@pytest.mark.parametrize("missing", ["results/.source-cut.lock", "search-provenance"])
def test_partial_namespace_is_not_repaired_or_given_a_second_semantic_identity(
    initializer_backend, postgres_dsn, tmp_path, missing
):
    import shutil

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    identity = _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    path = tmp_path / "research" / missing
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    with pytest.raises(subprocess.CalledProcessError):
        _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    assert not path.exists()
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity


def test_missing_bound_namespace_cannot_be_reinitialized_as_empty(initializer_backend, postgres_dsn, tmp_path):
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    identity = _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    original = tmp_path / "retained-research"
    (tmp_path / "research").rename(original)
    with pytest.raises(RuntimeError, match="EXISTING_HISTORY_UNAVAILABLE"):
        _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    assert not (tmp_path / "research").exists()
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity


def test_nonempty_unsupported_source_is_unavailable_and_never_an_empty_cut(
    initializer_backend, native_probe, postgres_dsn, tmp_path
):
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path, initializer_backend)
    locator = "a" * 64
    path = tmp_path / f"research/agent-provenance/sha256/aa/{locator}"
    path.mkdir(parents=True)
    retained = b"original unsupported source fact"
    (path / "manifest.json").write_bytes(retained)
    assert project(native_probe, tmp_path) == {"error": "NOVELTY_PROOF_UNAVAILABLE"}
    assert (path / "manifest.json").read_bytes() == retained


def test_published_files_before_db_binding_resume_the_original_namespace(initializer_backend, postgres_dsn, tmp_path):
    from onlyalpha.research.operations.deployment import OnlyResearchDeploymentError, OnlyResearchDeploymentErrorCode

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    result = subprocess.run(
        [str(initializer_backend), "--initialize-fresh-research-namespace", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    original = json.loads(result.stdout)["semantic_store_id"]
    with pytest.raises(OnlyResearchDeploymentError) as missing:
        OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()
    assert missing.value.code is OnlyResearchDeploymentErrorCode.DEPLOYMENT_BINDING_MISSING
    before = (tmp_path / "research/.onlyalpha-semantic-store.json").read_bytes()
    assert _initialize_deployment(postgres_dsn, tmp_path, initializer_backend) == original
    assert (tmp_path / "research/.onlyalpha-semantic-store.json").read_bytes() == before


def test_operator_without_selected_binary_cannot_create_python_fallback_namespace(postgres_dsn, tmp_path, monkeypatch):
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    monkeypatch.delenv("ONLYALPHA_NATIVE_ARTIFACT_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="NATIVE_BACKEND_REQUIRED"):
        _initialize_deployment(postgres_dsn, tmp_path)
    assert not (tmp_path / "research").exists()
