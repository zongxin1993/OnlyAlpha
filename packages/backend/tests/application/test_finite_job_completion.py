"""真实 PG/ClickHouse、原 Run、内存执行与 join；不发布正式作业结果。"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from packages.backend.tests.application.support.native_research_market_fixture import (
    database as database,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    native_environment_case as native_environment_case,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    probe,
    strategy_preparation_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(300)]


def prepare_runtime_login(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.info.dbname.endswith("_test")
        role = "onlyalpha_job_storage_test_login"
        found = connection.execute(
            "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if found is None:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("COMMENT ON ROLE {} IS 'OnlyAlpha controlled publication test login'").format(
                    sql.Identifier(role)
                )
            )
        else:
            assert found == (
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                "OnlyAlpha controlled publication test login",
            )
        connection.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(connection.info.password))
        )
        connection.execute(
            sql.SQL("GRANT onlyalpha_job_reader,onlyalpha_factor_builder TO {}").format(sql.Identifier(role))
        )


def test_actual_finite_research_joins_and_retains_all_members_without_publishing(
    native_environment_case: dict, native_release_probe: Path, database, postgres_dsn: str, tmp_path: Path
) -> None:
    # Build a current asset through the actual value owner; the historical
    # research_factor.json remains byte-for-byte bound to its old ABI identity.
    native_environment_case = copy.deepcopy(native_environment_case)
    reference = subprocess.run(
        [str(native_release_probe)],
        input=json.dumps(
            {
                "op": "factor-reference",
                "candidate": native_environment_case["vector"]["candidate"],
                "factor_id": "private.factor.stage5_" + uuid4().hex,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    native_environment_case["vector"] = json.loads(reference.stdout)
    command = str(uuid4())
    digest = bytearray(
        hashlib.sha256(b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command.encode()).digest()[:16]
    )
    digest[6], digest[8] = (digest[6] & 15) | 64, (digest[8] & 63) | 128
    run_id = str(UUID(bytes=bytes(digest)))
    case = strategy_preparation_case(
        native_environment_case,
        native_release_probe,
        database,
        tmp_path,
        "evaluate",
        work_id=run_id,
        first_bar_start=datetime(2025, 1, 2, 11, 39, tzinfo=UTC),
    )
    executable, arguments = case["selected"], case["arguments"]
    semantic = tmp_path / "finite-semantic"
    semantic.mkdir(mode=0o700)
    provisioned = probe(executable, database, "strategy-evidence-provision", semantic_root=str(semantic))
    assert "error" not in provisioned, provisioned
    research = semantic / "research"
    arguments.update(
        dataset_root=str(research / "datasets"),
        research_root=str(research),
        semantic_root=str(semantic),
        projection_root=str(research / "experiment-memory"),
        source_roots=provisioned["source_roots"],
        research_command=command,
        strategy_evaluation=False,
        strategy_evidence=True,
    )
    prepare_runtime_login(postgres_dsn)
    built = probe(
        executable,
        database,
        "strategy-evidence-phase",
        **arguments,
        evidence_phase="memory-build",
        build_instances=[
            {
                "factor_id": case["vector"]["revision"]["factor_id"],
                "revision": case["vector"]["revision"]["revision_fingerprint"],
                "parameters": {"literal_1": "1"},
            }
        ],
    )
    assert "error" not in built and len(built["bindings"]) == 1, built
    submitted = probe(executable, database, "dataset-strategy-prepare", **arguments)
    assert "error" not in submitted and submitted["run_id"] == run_id, submitted
    common = {**arguments, "run_id": run_id, "evidence_phase": "memory"}
    first = probe(executable, database, "strategy-evidence-phase", **common)
    assert "error" not in first, first
    assert first["state"] == "QUEUED" and first["publications"] == 0
    batch = first["lineage"]["calculation_batch"]
    assert batch is not None and batch["contract"] == "NATIVE_GRAPH_BATCH_COMPLETED_V1", first["lineage"]
    assert batch["implementations"]
    for implementation in batch["implementations"]:
        assert implementation["backend_kind"] == "RESEARCH"
        if implementation["calculation_type_reference"]["kind"] == "FACTOR":
            assert implementation["entrypoint_identity"] == "onlyalpha_calculation.program:evaluate_batch"
    assert first["lineage"]["signal_plane"]["backend_kind"] == "TRADING"
    assert first["lineage"]["signal_plane"]["purpose"] == "SHARED_EVENT_SIGNAL_REFERENCE"
    members = {row["kind"]: row for row in first["members"]}
    assert set(members) == {"CALCULATION_VALUES", "SIGNAL_VALUES", "STATISTICS", "RESEARCH_REPORT", "CAUSAL_EVIDENCE"}
    assert members["CALCULATION_VALUES"]["rows"] == members["SIGNAL_VALUES"]["rows"] == 740
    assert members["STATISTICS"]["rows"] == 2
    again = probe(executable, database, "strategy-evidence-phase", **common)
    assert "error" not in again and again["candidate"] == first["candidate"], again
    assert all(count in (None, 0) for count in again["source_parses_in_preparation"])
    for fault in ["run", "execution", "plan-axis", "cancel"]:
        rejected = probe(executable, database, "strategy-evidence-phase", **common, finite_fault=fault)
        assert "error" in rejected, (fault, rejected)
    print(
        {
            "candidate": first["candidate"],
            "prepared_us": first["prepared_us"],
            "execute_join_us": first["execute_join_us"],
            "probe_observation_us": first["probe_observation_us"],
        }
    )
