"""Real bounded job inputs through the existing PG/ClickHouse owners; no Run or Web acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint

from packages.backend.tests.application.test_market_storage_postgres_clickhouse import (
    ClickHouseObservations,
    _quote,
    _scope_payload,
    drain,
    fixture,
    probe,
    retained,
    retained_records,
)
from packages.backend.tests.application.test_market_storage_postgres_clickhouse import (
    database as database,
)
from packages.backend.tests.application.test_private_factor_authoring_postgres import call as factor_call
from packages.backend.tests.application.test_private_factor_authoring_postgres import draft as factor_draft

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize("source_rows", [1, 128, 740])
def test_frozen_job_input_repeats_exact_sealed_slice_and_rejects_every_changed_pin(
    native_release_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path, source_rows: int
) -> None:
    from psycopg import sql

    from scripts.build_algorithm_sdk import install

    market_probe = native_release_probe
    wal_root = tmp_path / "input-wal"
    wal_root.mkdir()
    wal, segment = retained(wal_root, "BAR", updates=[{"index": index} for index in range(source_rows)])
    bars = [
        fact["canonical_payload"]["payload"]["value"]
        for fact in retained_records(wal, segment)["records"][0]["canonical_facts"]
    ]
    bar = bars[0]
    # A retained copy is only the controlled test oracle. The loader itself
    # receives no filesystem path and reads the actual ClickHouse owner.
    expected_wal_root = tmp_path / "expected-market-input"
    shutil.copytree(wal, expected_wal_root)
    sealed = drain(market_probe, database, wal, segment)
    assert "error" not in sealed, sealed
    scope = _scope_payload(segment)
    first = datetime.fromisoformat(bar["ts_event"])
    definition = {
        "schema_version": 2,
        "dataset_type": "HISTORICAL_BAR",
        "instruments": [scope["instrument_id"]],
        "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
        "time_range": {"start": first.isoformat(), "end": (first + timedelta(minutes=source_rows)).isoformat()},
        "quality_policy": "STRICT",
        "closed_only": True,
    }
    expected = fixture(
        "dataset-reference-from-wal",
        definition=definition,
        scope=scope,
        revision=sealed["revision"],
        seal=sealed["seal"],
        expected_wal_root=str(expected_wal_root),
        expected_segment=segment["segment_id"],
    )
    axis = [
        [row[key] for key in ("instrument_id", "bar_start_ns", "bar_end_ns", "ts_event_ns", "revision")]
        for row in expected["rows"]
    ]
    stamp = first - datetime(1970, 1, 1, tzinfo=UTC)
    start_ns = (stamp.days * 86400 + stamp.seconds) * 1_000_000_000 + stamp.microseconds * 1000
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.info.dbname.endswith("_test")
        selected = connection.execute(
            "SELECT semantic_store_id::text FROM research_deployment_semantic_store_binding"
        ).fetchone()
        if selected is None:
            namespace = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(true,%s::uuid)",
                (namespace,),
            )
        else:
            namespace = selected[0]
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
    pin = "a" * 64
    market = {
        "dataset_snapshot": expected["snapshot"],
        "source_revision": sealed["revision"]["fingerprint"],
        "bar_semantic": only_canonical_fingerprint(definition["bar_semantic"]),
        "instruments": definition["instruments"],
        "start_ns": start_ns,
        "end_ns": start_ns + source_rows * 60_000_000_000,
        "versions": [only_canonical_fingerprint(scope["data_version"])],
        "seals": [sealed["seal"]["seal_id"].removeprefix("seal:")],
        "segments": sorted(only_canonical_fingerprint(row) for row in sealed["revision"]["segment_refs"]),
        "rows": source_rows,
        "warmup_rows": 0,
        "sample_rows": source_rows,
        "axis": only_canonical_fingerprint(axis),
        "content": expected["content"],
    }
    binding = {
        "schema_version": 1,
        "kind": "BACKTEST",
        "scope": {"namespace": namespace, "owner": "human:job-input-test", "run_id": str(uuid.uuid4())},
        "strategy_revision": pin,
        "signal_graph": pin,
        "factor_bindings": [],
        "kernel_artifact": pin,
        "runtime_generation": pin,
        "initial_state": pin,
        "execution_configuration": pin,
        "calendar": pin,
        "fees": pin,
        "market_rules": pin,
        "market": market,
        "result_plan": {
            "kind": "BACKTEST",
            "members": [
                {"key": "execution", "kind": "EXECUTION_FACTS", "schema": pin, "axis": pin, "rows": 1},
                {"key": "result", "kind": "ECONOMIC_RESULT", "schema": pin, "axis": None, "rows": 1},
                {"key": "curve", "kind": "CLOSE_CURVE", "schema": pin, "axis": pin, "rows": 1},
                {"key": "causes", "kind": "CAUSAL_EVIDENCE", "schema": pin, "axis": None, "rows": 1},
            ],
        },
    }
    installation = tmp_path / "algorithms"
    artifact = install(tmp_path / "wheels", installation)
    arguments = {
        "binding": binding,
        "installation": str(installation),
        "algorithm_artifact": artifact,
        "integration_revision": scope["bar_construction"]["plan"]["integration_revision_fingerprint"],
        "source": scope["source_id"],
    }
    factor_id = "private.factor.input_" + uuid.uuid4().hex
    draft = factor_draft(factor_id)
    saved = factor_call(market_probe, factor_id, "save", draft=draft, expected=None)
    assert "error" not in saved, saved
    published = factor_call(market_probe, factor_id, "publish", expected=saved["result"]["draft_fingerprint"])
    assert "error" not in published, published
    revision = published["result"]["revision"]["revision_fingerprint"]
    built = probe(market_probe, database, "job-input", **arguments, build=True, factor_id=factor_id, revision=revision)
    assert "error" not in built, built
    assert built["source_parse_count"] == 1
    binding["factor_bindings"] = [built["factor_binding"]]

    def process_files() -> dict[str, tuple[int, str]]:
        return {
            str(path.relative_to(tmp_path)): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in tmp_path.rglob("*")
            if path.is_file() and (path.suffix == ".parquet" or ".sqlite" in path.name)
        }

    # The installed SDK already carries a PyArrow Parquet reference file.
    # Reject new or modified process files, including inside that installation.
    process_files_before = process_files()
    with psycopg.connect(postgres_dsn) as connection:
        inventory_tables = (
            "market_data_revision",
            "market_ingest_segment",
            "market_revision_seal",
            "market_segment_physical_proof",
            "factor_built_program",
            "factor_parameter_certificate",
            "factor_build_request",
        )
        inventory_before = [
            connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()
            for table in inventory_tables
        ]
    loaded = probe(market_probe, database, "job-input", **arguments, samples=10)
    assert "error" not in loaded, loaded
    assert len(loaded["samples"]) == 10
    for sample in loaded["samples"]:
        assert sample["bars"] == bars
        assert sample["rows"] == expected["rows"]
        assert sample["snapshot"] == expected["snapshot"]
        assert sample["programs"] == 1
        assert sample["profile"]["requests"] > 0
        assert sample["profile"]["bytes"] > 0
    for key in ("dataset_snapshot", "source_revision", "bar_semantic", "content", "axis"):
        changed = json.loads(json.dumps(binding))
        changed["market"][key] = "0" * 64
        rejected = probe(market_probe, database, "job-input", **{**arguments, "binding": changed})
        assert "error" in rejected, (key, rejected)
    for key in ("versions", "seals", "segments", "instruments"):
        changed = json.loads(json.dumps(binding))
        changed["market"][key] = ["OTHER.BINANCE"] if key == "instruments" else ["0" * 64]
        rejected = probe(market_probe, database, "job-input", **{**arguments, "binding": changed})
        assert "error" in rejected, (key, rejected)
    for controls, error in [
        ({"deny": True}, "JOB_INPUT_Forbidden"),
        ({"revoke": True}, "JOB_INPUT_Forbidden"),
        ({"rows_limit": 1, "bytes_limit": 1}, "JOB_INPUT_BudgetExceeded"),
    ]:
        assert probe(market_probe, database, "job-input", **arguments, **controls)["error"] == error
    overflow = json.loads(json.dumps(binding))
    overflow["market"].update(rows=2**64 - 1, warmup_rows=2**64 - 2, sample_rows=1)
    assert (
        probe(market_probe, database, "job-input", **{**arguments, "binding": overflow})["error"]
        == "JOB_INPUT_BudgetExceeded"
    )
    wrong_owner = json.loads(json.dumps(binding))
    wrong_owner["scope"]["owner"] = "human:another"
    assert (
        probe(market_probe, database, "job-input", **{**arguments, "binding": wrong_owner})["error"]
        == "JOB_INPUT_Forbidden"
    )
    missing_certificate = json.loads(json.dumps(binding))
    missing_certificate["factor_bindings"][0]["certificate"] = "0" * 64
    assert (
        probe(market_probe, database, "job-input", **{**arguments, "binding": missing_certificate})["error"]
        == "JOB_INPUT_MissingEvidence"
    )
    with psycopg.connect(postgres_dsn) as connection:
        assert [
            connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()
            for table in inventory_tables
        ] == inventory_before
    if source_rows == 1:
        # Administrative fault injection in the isolated test catalog only.
        # Missing owner proofs are not affirmative content mismatches.
        for table, key, identity in (
            ("market_revision_seal", "revision_id", sealed["revision"]["revision_id"]),
            ("market_segment_physical_proof", "segment_id", segment["segment_id"]),
        ):
            with psycopg.connect(postgres_dsn) as connection:
                assert connection.info.dbname.endswith("_test")
                connection.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table)))
                saved_row = connection.execute(
                    sql.SQL("DELETE FROM {} t WHERE {}=%s RETURNING to_jsonb(t)::text").format(
                        sql.Identifier(table), sql.Identifier(key)
                    ),
                    (identity,),
                ).fetchone()
                assert saved_row is not None
                connection.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(sql.Identifier(table)))
            try:
                assert probe(market_probe, database, "job-input", **arguments)["error"] == "JOB_INPUT_MissingEvidence"
            finally:
                with psycopg.connect(postgres_dsn) as connection:
                    connection.execute(
                        sql.SQL("INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{},%s::jsonb)").format(
                            sql.Identifier(table), sql.Identifier(table)
                        ),
                        (saved_row[0],),
                    )
        assert "error" not in probe(market_probe, database, "job-input", **arguments, samples=1)
    if source_rows == 1:
        # Small certified programs must be charged by actual declared content,
        # not a full 32 MiB maximum reservation for every single factor.
        four = json.loads(json.dumps(binding))
        for _ in range(3):
            next_id = "private.factor.input_" + uuid.uuid4().hex
            next_saved = factor_call(market_probe, next_id, "save", draft=factor_draft(next_id), expected=None)
            next_published = factor_call(
                market_probe, next_id, "publish", expected=next_saved["result"]["draft_fingerprint"]
            )
            next_built = probe(
                market_probe,
                database,
                "job-input",
                **arguments,
                build=True,
                factor_id=next_id,
                revision=next_published["result"]["revision"]["revision_fingerprint"],
            )
            assert "error" not in next_built, next_built
            assert next_built["source_parse_count"] == 0
            four["factor_bindings"].append(next_built["factor_binding"])
        four_loaded = probe(market_probe, database, "job-input", **{**arguments, "binding": four}, samples=1)
        assert "error" not in four_loaded, four_loaded
        assert four_loaded["samples"][0]["programs"] == 4
    assert process_files() == process_files_before
    unavailable = probe(
        market_probe, database, "job-input", **arguments, database="onlyalpha_test_missing_" + uuid.uuid4().hex
    )
    assert unavailable["error"] == "JOB_INPUT_Unavailable"
    # Same axis and row count, changed physical content: the original owning
    # Segment proof must reject it before a different Dataset could be accepted.
    database.execute(
        "ALTER TABLE market_bar UPDATE close='0.123456789' WHERE segment_id="
        + _quote(segment["segment_id"])
        + " SETTINGS mutations_sync=2"
    )
    assert probe(market_probe, database, "job-input", **arguments)["error"] == "JOB_INPUT_Mismatch"
    print(
        "JOB_INPUT_PROFILE "
        + json.dumps(
            {
                "rows": source_rows,
                "warmup_rows": 0,
                "sample_rows": source_rows,
                "cache": "first_loader_cold_then_loader_warm_storage_warm",
                "binary_sha256": hashlib.sha256(native_release_probe.read_bytes()).hexdigest(),
                "binding": loaded["samples"][0]["binding"],
                "snapshot": loaded["samples"][0]["snapshot"],
                "factor": built["factor_binding"],
                "source_parse_count": built["source_parse_count"],
                "samples": [sample["profile"] for sample in loaded["samples"]],
                "peak": loaded["peak"],
                "setup_us": loaded["setup_us"],
            }
        )
    )
