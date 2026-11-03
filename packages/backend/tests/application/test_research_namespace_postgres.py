"""Formal deployment initializer and real source cuts; no Shipping business steps are substituted."""

from __future__ import annotations

import json
import os
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
    extended = extension(initializer_backend, postgres_dsn, tmp_path)
    assert extended.returncode == 0, extended.stdout + extended.stderr
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
    extended = extension(initializer_backend, postgres_dsn, tmp_path)
    assert extended.returncode == 0, extended.stdout + extended.stderr
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


@pytest.fixture(scope="session")
def strategy_extension_backend() -> Path:
    # Exercise the admitted optimized Shipping CLI for this new extension.
    return native_executable(release=True)


@pytest.fixture(scope="session")
def strategy_extension_probe() -> Path:
    from packages.backend.tests.application.test_market_storage_postgres_clickhouse import _build_market_probe

    return _build_market_probe(release=True)


STRATEGY_EXTENSION = ".onlyalpha-strategy-research-owner-extension-v1.json"
BASE_PROFILE_FP = "e65c1f68866533f9779f85f6f254ce1b43115ea22b6a33bb4cd7af31ba8fc01b"


def original_namespace_v1(probe: Path, dsn: str, root: Path) -> str:
    result = subprocess.run(
        [str(probe)],
        input=json.dumps({"op": "research-namespace", "phase": "initialize-original-base-v1", "user_data": str(root)}),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    payload = json.loads(result.stdout)
    assert "error" not in payload, payload
    assert payload["profile"]["profile_fingerprint"] == BASE_PROFILE_FP
    assert not (root / "research" / STRATEGY_EXTENSION).exists()
    with psycopg.connect(dsn) as db:
        db.execute(
            "INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (payload["semantic_store_id"],),
        )
    return str(payload["semantic_store_id"])


def extension(backend: Path, dsn: str, root: Path) -> subprocess.CompletedProcess[str]:
    from psycopg.conninfo import make_conninfo

    return subprocess.run(
        [str(backend), "--extend-strategy-research-namespace", str(root)],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode="disable")},
        text=True,
        capture_output=True,
        timeout=30,
    )


def existing_files(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(path.relative_to(root)): (path.stat().st_ino, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_explicit_strategy_extension_preserves_the_original_bound_profile_and_every_existing_file(
    strategy_extension_backend: Path, strategy_extension_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    identity = original_namespace_v1(strategy_extension_probe, postgres_dsn, tmp_path)
    # Opaque unrelated bytes prove that extension cannot reset the user-data root.
    # They are not fabricated model settings, scientific reports or read grants;
    # real retained model/two-round Product loading remains a separate Web gate.
    (tmp_path / "use_test_unrelated_retained_data.bin").write_bytes(b"preserve unrelated user data")
    before = existing_files(tmp_path)
    with psycopg.connect(postgres_dsn) as db:
        binding = db.execute(
            "SELECT singleton,semantic_store_id::text,bound_at FROM research_deployment_semantic_store_binding"
        ).fetchall()
    completed = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    for name, retained in before.items():
        path = tmp_path / name
        assert (path.stat().st_ino, path.read_bytes()) == retained
    body = {
        "schema_version": 1,
        "contract": "ONLYALPHA_STRATEGY_RESEARCH_OWNER_EXTENSION_V1",
        "semantic_store_id": identity,
        "base_profile_fingerprint": BASE_PROFILE_FP,
        "file_source_extensions": [
            {
                "family": "QUALIFICATION_DECISION",
                "owner": "strategy/qualification-decisions",
                "source_schema_version": 1,
                "enumeration_contract_version": 2,
            }
        ],
    }
    expected = {**body, "extension_fingerprint": only_canonical_fingerprint(body)}
    path = tmp_path / "research" / STRATEGY_EXTENSION
    assert path.read_text() == only_canonical_json(expected)
    owner = tmp_path / "research/strategy/qualification-decisions"
    assert (owner / ".source-cut.lock").is_file() and (owner / "sha256").is_dir()
    complete = existing_files(tmp_path)
    replay = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert existing_files(tmp_path) == complete
    with psycopg.connect(postgres_dsn) as db:
        assert (
            db.execute(
                "SELECT singleton,semantic_store_id::text,bound_at FROM research_deployment_semantic_store_binding"
            ).fetchall()
            == binding
        )
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity


@pytest.mark.parametrize("missing", ["results/.source-cut.lock", "qualification-decisions/.source-cut.lock"])
def test_strategy_extension_refuses_to_repair_any_original_owner(
    strategy_extension_backend: Path, strategy_extension_probe: Path, postgres_dsn: str, tmp_path: Path, missing: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    identity = original_namespace_v1(strategy_extension_probe, postgres_dsn, tmp_path)
    original = tmp_path / "research" / missing
    original.unlink()
    before = existing_files(tmp_path)
    denied = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0
    assert existing_files(tmp_path) == before and not original.exists()
    assert not (tmp_path / "research" / STRATEGY_EXTENSION).exists()
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity


def test_strategy_extension_does_not_hide_or_copy_an_unsupported_legacy_qualification_fact(
    strategy_extension_backend: Path, strategy_extension_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    original_namespace_v1(strategy_extension_probe, postgres_dsn, tmp_path)
    locator = "a" * 64
    retained = tmp_path / "research/qualification-decisions/sha256/aa" / locator / "manifest.json"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"unavailable original legacy qualification source fact")
    before = existing_files(tmp_path)
    denied = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0
    assert existing_files(tmp_path) == before
    assert not (tmp_path / "research" / STRATEGY_EXTENSION).exists()
    assert not (tmp_path / "research/strategy/qualification-decisions/sha256/aa" / locator).exists()


def test_strategy_extension_cannot_bypass_an_existing_physical_node_writer(
    strategy_extension_backend: Path, strategy_extension_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    original_namespace_v1(strategy_extension_probe, postgres_dsn, tmp_path)
    before = existing_files(tmp_path)
    # An adversarial real PostgreSQL lock only denies acquisition; it grants no
    # capability to the extension command and is not a fabricated admission seal.
    with psycopg.connect(postgres_dsn) as blocker:
        blocker.execute("SELECT pg_advisory_lock(1329199301,5)")
        denied = extension(strategy_extension_backend, postgres_dsn, tmp_path)
        assert denied.returncode != 0
        assert existing_files(tmp_path) == before
    assert not (tmp_path / "research" / STRATEGY_EXTENSION).exists()


def test_a_committed_extension_never_recreates_a_lost_canonical_decision_owner(
    strategy_extension_backend: Path, strategy_extension_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    import shutil

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    original_namespace_v1(strategy_extension_probe, postgres_dsn, tmp_path)
    completed = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    owner = tmp_path / "research/strategy/qualification-decisions"
    shutil.rmtree(owner)
    before = existing_files(tmp_path)
    denied = extension(strategy_extension_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0
    assert not owner.exists() and existing_files(tmp_path) == before


MANUAL_EXTENSION = ".onlyalpha-manual-backtest-owner-extension-v1.json"


def manual_extension(backend: Path, dsn: str, root: Path) -> subprocess.CompletedProcess[str]:
    from psycopg.conninfo import make_conninfo

    return subprocess.run(
        [str(backend), "--extend-manual-backtest-namespace", str(root)],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode="disable")},
        text=True,
        capture_output=True,
        timeout=30,
    )


def prepare_manual_extension_base(backend: Path, probe: Path, dsn: str, root: Path) -> str:
    OnlyPostgresMigrationAuthority(dsn).migrate()
    identity = original_namespace_v1(probe, dsn, root)
    completed = extension(backend, dsn, root)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return identity


def test_explicit_manual_backtest_extension_preserves_original_namespace_and_retained_files(
    initializer_backend: Path, native_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

    identity = prepare_manual_extension_base(initializer_backend, native_probe, postgres_dsn, tmp_path)
    (tmp_path / "unrelated_retained_user_data.bin").write_bytes(b"retained independent data")
    before = existing_files(tmp_path)
    completed = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["semantic_store_id"] == identity
    for relative, retained in before.items():
        path = tmp_path / relative
        assert (path.stat().st_ino, path.read_bytes()) == retained
    marker = json.loads((tmp_path / "research" / MANUAL_EXTENSION).read_text())
    assert marker["semantic_store_id"] == identity
    assert marker["contract"] == "ONLYALPHA_MANUAL_BACKTEST_OWNER_EXTENSION_V1"
    original = json.loads((tmp_path / "research" / STRATEGY_EXTENSION).read_text())
    assert marker["strategy_extension_fingerprint"] == original["extension_fingerprint"]
    fingerprint = marker.pop("extension_fingerprint")
    assert fingerprint == only_canonical_fingerprint(marker)
    marker["extension_fingerprint"] = fingerprint
    assert (tmp_path / "research" / MANUAL_EXTENSION).read_text() == only_canonical_json(marker)
    owner = tmp_path / "research/backtest/strategy-validation"
    assert owner.stat().st_mode & 0o777 == 0o700
    assert (owner / "by-preparation").stat().st_mode & 0o777 == 0o700
    assert (owner / ".source-cut.lock").stat().st_mode & 0o777 == 0o600
    policy = json.loads(
        (tmp_path / "research/strategy/qualification-policies/manual-backtest/1/manifest.json").read_text()
    )
    assert policy["gate"] == "MANUAL_STRATEGY_TO_BACKTEST"
    assert policy["criteria"] == [
        {
            "criterion_id": "execution-validation",
            "evidence_kind": "STRATEGY_VALIDATION",
            "metric": "strategy.execution_validation_passed",
            "comparison": "EQ",
            "threshold": "1",
        }
    ]
    complete = existing_files(tmp_path)
    replay = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert existing_files(tmp_path) == complete
    assert str(OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id()) == identity


@pytest.mark.parametrize("partial", ["parent", "owner", "lock", "rows", "complete"])
def test_explicit_manual_extension_can_continue_only_healthy_empty_uncommitted_topology(
    initializer_backend: Path, native_probe: Path, postgres_dsn: str, tmp_path: Path, partial: str
) -> None:
    prepare_manual_extension_base(initializer_backend, native_probe, postgres_dsn, tmp_path)
    backtest = tmp_path / "research/backtest"
    backtest.mkdir(mode=0o700)
    if partial != "parent":
        owner = backtest / "strategy-validation"
        owner.mkdir(mode=0o700)
        if partial in {"lock", "complete"}:
            (owner / ".source-cut.lock").touch(mode=0o600)
        if partial in {"rows", "complete"}:
            (owner / "by-preparation").mkdir(mode=0o700)
    before = existing_files(tmp_path)
    completed = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    for relative, retained in before.items():
        path = tmp_path / relative
        assert (path.stat().st_ino, path.read_bytes()) == retained
    assert (tmp_path / "research" / MANUAL_EXTENSION).is_file()


@pytest.mark.parametrize(
    "missing",
    [
        "backtest/strategy-validation",
        "backtest/strategy-validation/.source-cut.lock",
        "backtest/strategy-validation/by-preparation",
        "strategy/qualification-policies/manual-backtest/1/manifest.json",
    ],
)
def test_committed_manual_extension_never_repairs_missing_validation_or_policy_history(
    initializer_backend: Path, native_probe: Path, postgres_dsn: str, tmp_path: Path, missing: str
) -> None:
    import shutil

    prepare_manual_extension_base(initializer_backend, native_probe, postgres_dsn, tmp_path)
    assert manual_extension(initializer_backend, postgres_dsn, tmp_path).returncode == 0
    target = tmp_path / "research" / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    before = existing_files(tmp_path)
    denied = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0
    assert not target.exists() and existing_files(tmp_path) == before


@pytest.mark.parametrize("damage", ["fact", "unsafe-lock", "foreign-entry", "symlink"])
def test_uncommitted_manual_extension_refuses_positive_unprofiled_facts_and_unsafe_layout(
    initializer_backend: Path, native_probe: Path, postgres_dsn: str, tmp_path: Path, damage: str
) -> None:
    prepare_manual_extension_base(initializer_backend, native_probe, postgres_dsn, tmp_path)
    owner = tmp_path / "research/backtest/strategy-validation"
    owner.mkdir(parents=True, mode=0o700)
    (owner / ".source-cut.lock").touch(mode=0o600)
    rows = owner / "by-preparation"
    rows.mkdir(mode=0o700)
    if damage == "fact":
        (rows / "unprofiled.json").write_bytes(b"positive unprofiled bytes")
    elif damage == "unsafe-lock":
        (owner / ".source-cut.lock").chmod(0o666)
    elif damage == "foreign-entry":
        (owner / "unexpected.json").write_bytes(b"unknown owner fact")
    else:
        rows.rmdir()
        rows.symlink_to(tmp_path, target_is_directory=True)
    before = existing_files(tmp_path)
    denied = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0
    assert not (tmp_path / "research" / MANUAL_EXTENSION).exists()
    assert existing_files(tmp_path) == before


def test_manual_extension_requires_same_bound_namespace_and_original_physical_node_writer(
    initializer_backend: Path, native_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    identity = prepare_manual_extension_base(initializer_backend, native_probe, postgres_dsn, tmp_path)
    before = existing_files(tmp_path)
    with psycopg.connect(postgres_dsn) as blocker:
        blocker.execute("SELECT pg_advisory_lock(1329199301,5)")
        denied = manual_extension(initializer_backend, postgres_dsn, tmp_path)
        assert denied.returncode != 0 and existing_files(tmp_path) == before
    with psycopg.connect(postgres_dsn) as db:
        db.execute(
            "UPDATE research_deployment_semantic_store_binding SET semantic_store_id='22222222-2222-4222-8222-222222222222'"
        )
    denied = manual_extension(initializer_backend, postgres_dsn, tmp_path)
    assert denied.returncode != 0 and existing_files(tmp_path) == before
    assert json.loads((tmp_path / "research/.onlyalpha-semantic-store.json").read_text())["store_id"] == identity
