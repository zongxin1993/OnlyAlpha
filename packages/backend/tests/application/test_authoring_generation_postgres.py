"""Exact Rust authoring generation through original Run/Attempt and fresh subprocesses."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from packages.backend.tests.application.support.research_admission_reference import build, call
from packages.backend.tests.application.test_factor_proposals_postgres import call as proposal_call
from packages.backend.tests.application.test_factor_proposals_postgres import grant, proposal
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db
from scripts.native_web_e2e import clickhouse_namespace, research_deployment_id

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse]


def iso(nanos: int) -> str:
    assert nanos % 1_000_000_000 == 0
    return datetime.fromtimestamp(nanos // 1_000_000_000, UTC).isoformat()


@pytest.mark.parametrize("mode", ["normal", "wrong-native-version", "sdk-drift", "crash-after-claim"])
def test_authoring_generation_claim_and_original_run_recovery(
    native_release_probe: Path,
    migration_backend: Path,
    schema_db: str,
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONLYALPHA_CLICKHOUSE_USER", os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"])
    monkeypatch.setenv("ONLYALPHA_CLICKHOUSE_PASSWORD", os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"])
    command = str(uuid4())
    digest = bytearray(
        hashlib.sha256(b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command.encode()).digest()[:16]
    )
    digest[6] = (digest[6] & 15) | 64
    digest[8] = (digest[8] & 63) | 128
    work = str(UUID(bytes=bytes(digest)))
    executable = tmp_path / "original-executor"
    shutil.copyfile(native_release_probe, executable)
    subprocess.run(["strip", "--strip-all", str(executable)], check=True, timeout=30)
    executable.chmod(0o500)
    user = tmp_path / "user"
    user.mkdir()
    research_deployment_id(
        migration_backend,
        ["--initialize-research-deployment", str(user), str(Path("/workspace/database/postgres/migrations"))],
        make_conninfo(schema_db, sslmode="disable"),
    )
    research_deployment_id(
        migration_backend,
        ["--extend-strategy-research-namespace", str(user)],
        make_conninfo(schema_db, sslmode="disable"),
    )
    _, token = grant(executable, schema_db, owner="local-developer")
    candidate = proposal(executable, token)
    candidate["candidate"] = {
        "name": "收盘价观察",
        "purpose": "精确认领回归",
        "hypothesis": "fixture",
        "expression": {"input": "close"},
    }
    staged = proposal_call(executable, "stage", token=token, body=candidate, actor="local-developer")
    assert "error" not in staged, staged
    fingerprint = staged["effect"]["proposal_fingerprint"]
    preview = proposal_call(executable, "read", fingerprint=fingerprint, actor="local-developer")
    accepted = proposal_call(
        executable,
        "confirm",
        actor="local-developer",
        body={"schema_version": 1, "proposal_fingerprint": fingerprint},
    )
    assert "error" not in accepted, accepted
    factor = build(
        tmp_path / "runtime",
        executable,
        work_id=work,
        candidate_record=candidate["candidate"],
        draft_record=preview["snapshot"]["preview"]["draft"],
    )
    actual = tmp_path / "runtime/native-executor"
    database = "onlyalpha_test_authoring_" + uuid4().hex
    clickhouse_namespace(migration_backend, database, initialize=True)

    def market(operation: str, **values):
        result = call(
            actual,
            {
                "op": "market-storage",
                "request": {
                    "op": operation,
                    "at": "2026-10-29T00:00:00Z",
                    "database": database,
                    "url": os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
                    **values,
                },
            },
        )
        return result

    try:
        retained = market(
            "retained-source-prerequisite",
            user_data=str(user),
            selected_backend=str(actual),
            selected_backend_sha256=hashlib.sha256(actual.read_bytes()).hexdigest(),
            source_trust="/etc/ssl/certs/ca-certificates.crt",
            integration_id=str(uuid4()),
            create_command=str(uuid4()),
            publish_command=str(uuid4()),
        )
        segment = retained["segment"]
        scope_keys = (
            "source_id",
            "market",
            "instrument_id",
            "data_kind",
            "start_ns",
            "end_ns",
            "data_version",
            "bar_type",
            "first_sequence",
            "last_sequence",
            "bar_construction",
        )
        full = {key: segment[key] for key in scope_keys}
        market("drain", root=retained["wal_root"], ids=[segment["segment_id"]], scope=full)
        stride = 900_000_000_000
        scope = {**full, "end_ns": full["start_ns"] + 128 * stride}
        composed = market("compose", scope=scope, refs=[[segment["segment_id"], segment["content_hash"]]])
        start = scope["start_ns"] + stride
        end = scope["end_ns"] + stride
        definition = {
            "schema_version": 2,
            "dataset_type": "HISTORICAL_BAR",
            "instruments": [scope["instrument_id"]],
            "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
            "time_range": {"start": iso(start), "end": iso(end)},
            "quality_policy": "STRICT",
            "closed_only": True,
        }
        study = {
            "schema_version": 1,
            "bar_ns": stride,
            "horizon_bars": 1,
            "samples": [
                {"role": "DEVELOPMENT", "start_ns": start, "end_ns": start + 64 * stride},
                {"role": "OUT_OF_SAMPLE", "start_ns": start + 64 * stride, "end_ns": end},
            ],
            "protected_start_ns": end,
            "protected_end_ns": end + 64 * stride,
            "expected_block_length": 4,
            "replicates": 4096,
            "confidence_bps": 9500,
            "seed": "00" * 32,
        }
        roots = {
            "AGENT_PROVENANCE": "agent-provenance",
            "QUALIFICATION_DECISION": "strategy/qualification-decisions",
            "SEARCH_PROVENANCE": "search-provenance",
            "RESEARCH_RESULT": "results",
            "RESEARCH_STATISTICS": "statistics-results",
            "RESEARCH_FACTOR_PAIR_STATISTICS": "statistics-results",
            "RESEARCH_SUMMARY_STATISTICS": "statistics-results",
        }
        request = {
            "id": composed["revision"]["revision_id"],
            "definition": definition,
            "scope": scope,
            "dataset_root": str(user / "research/datasets"),
            "factor": factor,
            "study": study,
            "research_command": command,
            "proposal_fingerprint": fingerprint,
            "semantic_root": str(user),
            "research_root": str(user / "research"),
            "projection_root": str(user / "research/experiment-memory"),
            "source_roots": {name: str(user / "research" / directory) for name, directory in roots.items()},
            "initialize_evidence": False,
            "mode": "wrong-native-version" if mode == "wrong-native-version" else "normal",
            "policy_id": "onlyalpha.factor-research",
        }
        queued = market("dataset-research", phase="submit", **request)
        assert queued["state"] == "QUEUED", queued
        with psycopg.connect(schema_db) as db:
            row = db.execute(
                "SELECT specification_schema_version,specification_fingerprint,specification_payload FROM research_run WHERE run_id=%s",
                (work,),
            ).fetchone()
            assert row is not None and row[0] == 6
            original = row[1]
            generation = json.loads(row[2])["authoring_generation_fingerprint"]
            assert len(generation) == 64
            assert db.execute("SELECT count(*) FROM research_run_attempt WHERE run_id=%s", (work,)).fetchone() == (0,)
        if mode == "sdk-drift":
            manifest = Path(factor["installation"]) / "algorithm-installation.json"
            original_bytes, original_mode = manifest.read_bytes(), manifest.stat().st_mode & 0o777
            try:
                manifest.chmod(0o600)
                manifest.write_bytes(original_bytes + b" ")
                with pytest.raises(ValueError, match="NATIVE_RESEARCH_FIXTURE_FAILED"):
                    market(
                        "dataset-research", phase="execute", materialization_id=queued["materialization_id"], **request
                    )
                with psycopg.connect(schema_db) as db:
                    assert db.execute(
                        "SELECT state,revision FROM research_run WHERE run_id=%s", (work,)
                    ).fetchone() == ("QUEUED", 0)
                    assert db.execute(
                        "SELECT count(*) FROM research_run_attempt WHERE run_id=%s", (work,)
                    ).fetchone() == (0,)
            finally:
                manifest.write_bytes(original_bytes)
                manifest.chmod(original_mode)
        if mode == "crash-after-claim":
            with pytest.raises(subprocess.CalledProcessError) as crash:
                market(
                    "dataset-research",
                    phase="crash-after-claim",
                    materialization_id=queued["materialization_id"],
                    **request,
                )
            assert crash.value.returncode == 73
            with psycopg.connect(schema_db) as db:
                assert db.execute("SELECT state,revision FROM research_run WHERE run_id=%s", (work,)).fetchone() == (
                    "RUNNING",
                    1,
                )
                assert db.execute(
                    "SELECT state,attempt_number FROM research_run_attempt WHERE run_id=%s", (work,)
                ).fetchall() == [("ACTIVE", 1)]
                # Deliberate lease-expiry fault in this isolated test namespace.
                db.execute(
                    "UPDATE research_run_attempt SET lease_expires_at=last_heartbeat_at WHERE run_id=%s", (work,)
                )
        result = market("dataset-research", phase="execute", materialization_id=queued["materialization_id"], **request)
        assert result["state"] == ("QUEUED" if mode == "wrong-native-version" else "COMPLETED"), result
        with psycopg.connect(schema_db) as db:
            assert db.execute(
                "SELECT specification_fingerprint FROM research_run WHERE run_id=%s", (work,)
            ).fetchone() == (original,)
            if mode == "wrong-native-version":
                assert db.execute("SELECT count(*) FROM research_run_attempt WHERE run_id=%s", (work,)).fetchone() == (
                    0,
                )
            if mode == "crash-after-claim":
                attempts = db.execute(
                    "SELECT attempt_number,state,attempt_id::text FROM research_run_attempt WHERE run_id=%s ORDER BY attempt_number",
                    (work,),
                ).fetchall()
                assert [(number, state) for number, state, _ in attempts] == [(1, "EXPIRED"), (2, "SUCCEEDED")]
                assert attempts[0][2] == "00000000-0000-4000-8000-000000000920"
        if mode != "wrong-native-version":
            inspected = market(
                "dataset-research", phase="inspect", materialization_id=queued["materialization_id"], **request
            )
            assert inspected["run_id"] == work and inspected["state"] == "COMPLETED"
    finally:
        clickhouse_namespace(migration_backend, database, initialize=False)
