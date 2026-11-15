"""Actual common graph build facts and the owning read used before READY confirmation.

No fabricated READY/Run and no relaxation of Research's existing FACTOR-only
statistics contract. Full scientific execution is a later integration boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from packages.backend.tests.application.test_manual_backtest_validation import (
    actual_manual_environment as actual_manual_environment,
)
from packages.backend.tests.application.test_manual_backtest_validation import (
    database as database,
)
from packages.backend.tests.application.test_manual_backtest_validation import (
    manual_validation_owner_binary as manual_validation_owner_binary,
)
from packages.backend.tests.application.test_manual_backtest_validation import (
    market_probe as market_probe,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]


def test_actual_graph_build_is_once_and_missing_original_fact_never_rebuilds(
    actual_manual_environment: dict[str, Any],
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    fixture = actual_manual_environment
    first = fixture["produce"]("proof-build")
    assert "error" not in first, first
    proof = first["proof"]
    assert first["process_observation"]["controlled_begins"] == 1
    assert first["process_observation"]["controlled_joins"] == 1
    assert len(proof["graph_cases"]) == 6 and proof["node_profiles"]
    assert all(case["target_outputs"] == [] for case in proof["graph_cases"])
    assert proof["build_key"] == only_canonical_fingerprint(proof["context"])
    assert proof["proof_fingerprint"] == only_canonical_fingerprint(
        {k: v for k, v in proof.items() if k != "proof_fingerprint"}
    )
    with psycopg.connect(postgres_dsn) as conn:
        assert conn.info.dbname.endswith("_test")
        assert conn.execute("SELECT count(*) FROM calculation_build_proof").fetchone() == (1,)
        original = conn.execute("SELECT to_jsonb(t)::text FROM calculation_build_proof t").fetchone()
        assert original is not None
    repeated = fixture["produce"]("proof-build")
    assert repeated["proof"] == proof
    assert repeated["process_observation"]["controlled_begins"] == 0
    read = fixture["read_proof"](proof)
    assert read["verified"] is True and read["process_observation"]["controlled_begins"] == 0
    with psycopg.connect(postgres_dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE calculation_build_proof SET payload=payload")
        conn.rollback()
        conn.execute("ALTER TABLE calculation_build_proof DISABLE TRIGGER USER")
        conn.execute("DELETE FROM calculation_build_proof")
        conn.execute("ALTER TABLE calculation_build_proof ENABLE TRIGGER USER")
    try:
        missing = fixture["read_proof"](proof)
        assert missing["error"] == "CALCULATION_BUILD_PROOF_MISSING", missing
        assert missing["process_observation"]["controlled_begins"] == 0
        with psycopg.connect(postgres_dsn) as builder:
            assert builder.execute("SELECT count(*) FROM calculation_build_proof").fetchone() == (0,)
            assert builder.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
            assert builder.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
            builder.execute("SELECT pg_catalog.pg_advisory_xact_lock(%s)", (int(proof["build_key"][:15], 16),))
            busy = fixture["produce"]("proof-build")
            assert busy["error"] == "CALCULATION_BUILD_PROOF_BUSY", busy
            assert busy["process_observation"]["controlled_begins"] == 0
            builder.rollback()
    finally:
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute(
                "INSERT INTO calculation_build_proof SELECT * FROM jsonb_populate_record(NULL::calculation_build_proof,%s::jsonb)",
                (original[0],),
            )
    assert fixture["read_proof"](proof)["verified"] is True
    original_row = json.loads(original[0])
    original_body = json.loads(original_row["payload"])
    for mutation in ("artifact", "missing-case", "implementation"):
        body = json.loads(json.dumps(original_body))
        if mutation == "artifact":
            body["context"]["execution_binding"]["executor_artifact_sha256"] = "0" * 64
        elif mutation == "missing-case":
            body["graph_cases"].pop()
        else:
            body["node_profiles"][0]["research_implementation_fingerprint"] = "0" * 64
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute("ALTER TABLE calculation_build_proof DISABLE TRIGGER USER")
            conn.execute(
                "UPDATE calculation_build_proof SET payload=%s,proof_fingerprint=%s",
                (only_canonical_json(body), only_canonical_fingerprint(body)),
            )
            conn.execute("ALTER TABLE calculation_build_proof ENABLE TRIGGER USER")
        try:
            rejected = fixture["read_proof"](proof)
            assert rejected["error"] == "CALCULATION_BUILD_PROOF_MISMATCH", (mutation, rejected)
            assert rejected["process_observation"]["controlled_begins"] == 0
        finally:
            with psycopg.connect(postgres_dsn) as conn:
                conn.execute("ALTER TABLE calculation_build_proof DISABLE TRIGGER USER")
                conn.execute(
                    "UPDATE calculation_build_proof SET payload=%s,proof_fingerprint=%s",
                    (original_row["payload"], original_row["proof_fingerprint"]),
                )
                conn.execute("ALTER TABLE calculation_build_proof ENABLE TRIGGER USER")
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("ALTER TABLE calculation_build_proof RENAME TO calculation_build_proof_unavailable")
    try:
        unreadable = fixture["read_proof"](proof)
        assert unreadable["error"] == "CALCULATION_BUILD_PROOF_UNAVAILABLE", unreadable
    finally:
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute("ALTER TABLE calculation_build_proof_unavailable RENAME TO calculation_build_proof")
    from psycopg import sql

    role = "onlyalpha_graph_proof_test_reader"
    with psycopg.connect(postgres_dsn) as conn:
        existing = conn.execute(
            "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if existing is None:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(sql.Identifier(role))
            )
            conn.execute(
                sql.SQL("COMMENT ON ROLE {} IS 'OnlyAlpha graph proof controlled test reader'").format(
                    sql.Identifier(role)
                )
            )
        else:
            assert existing == (
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                "OnlyAlpha graph proof controlled test reader",
            )
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(conn.info.password)))
        conn.execute(sql.SQL("GRANT onlyalpha_job_reader TO {}").format(sql.Identifier(role)))
    reader_dsn = psycopg.conninfo.make_conninfo(postgres_dsn, user=role)
    with psycopg.connect(reader_dsn) as reader:
        reader.execute("SET ROLE onlyalpha_job_reader")
        assert reader.execute("SELECT count(*) FROM calculation_build_proof").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("UPDATE calculation_build_proof SET payload=payload")
        reader.rollback()
        reader.execute("SET ROLE onlyalpha_job_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("INSERT INTO calculation_build_proof SELECT * FROM calculation_build_proof")
        reader.rollback()

    print(
        "CALCULATION_BUILD_PROFILE "
        + json.dumps(
            {
                "build_key": proof["build_key"],
                "proof_fingerprint": proof["proof_fingerprint"],
                "controlled_graph_rows": sum(len(case["rows"]) for case in proof["graph_cases"]),
                "profile_rows": sum(len(case["inputs"]) for node in proof["node_profiles"] for case in node["cases"]),
                "proof_bytes": len(original_row["payload"].encode()),
                "build": first["process_observation"],
                "reuse": repeated["process_observation"],
                "read_us": read["elapsed_us"],
                "process_peaks": [first["process_peak"], repeated["process_peak"]],
            }
        )
    )
