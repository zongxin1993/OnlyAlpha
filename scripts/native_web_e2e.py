"""Run the Shipping native Host and ordinary browser flows in the sole test namespace."""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.postgres import only_assert_postgres_test_database
from scripts.native_workstation_build import build

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-fuzz", action="store_true", help="Fuzz all declared Implemented native operations")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    output = ROOT / "test-results/native-web-e2e" / operation
    output.mkdir(parents=True)
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "scripts.database", "migrate"], cwd=ROOT, check=True)
    namespace = str(uuid.uuid4())
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO public.research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (namespace,),
        )
    data = output / "user-data"
    for relative in (
        "research/artifacts",
        "backtest/evidence",
        "research/datasets",
        "research/dataset-economic-bindings",
        "secrets",
    ):
        (data / relative).mkdir(parents=True, mode=0o700)
    key = data / "secrets/dev-master-key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    (data / "research/.onlyalpha-semantic-store.json").write_text(
        json.dumps({"schema_version": 1, "store_id": namespace})
    )
    # WAL locations are deployment paths, not Command or stream identities.
    # Actual startup must visit every retained location without renaming it.
    wal_parent = data / "market-data/retained-test-source/realtime"
    wal_locations = (
        "00000000000040008000000000000001",
        "00000000-0000-4000-8000-000000000001",
        "capture-location",
    )
    for location in wal_locations:
        (wal_parent / location / "wal").mkdir(parents=True, mode=0o700)
    resources = output / "artifacts"
    artifact = build(resources)["algorithm_artifact"]
    (output / "algorithm-artifact.sha256").write_text(artifact + "\n")
    executable = resources / "bin/onlyalpha-backend"
    # Existing immutable authoring metadata is a read-only UI precondition. The
    # test's user goal is discovery/inspection, not Factor authoring or execution.
    from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1
    from onlyalpha.persistence.postgres.private_asset_store import OnlyPostgresPrivateAssetStore
    from onlyalpha.quant_assets.private import OnlyPrivateFactorAsset, OnlyPrivateFactorDraft

    assets = OnlyPostgresPrivateAssetStore(dsn)
    factor_id = "private.factor.native_metadata"
    assets.put_factor_asset(OnlyPrivateFactorAsset(factor_id))
    draft = OnlyPrivateFactorDraft(
        factor_id=factor_id,
        semantic_version="1",
        source_text="def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        factor_api_version=1,
        factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
        input_contract={"close": {"type": "DECIMAL"}},
        parameter_contract={},
        output_contract={"value": {"type": "DECIMAL"}},
        description="Retained native metadata",
        economic_rationale="Explicit saved hypothesis",
        category="test",
        tags=("native",),
    )
    assets.save_factor_draft(draft)
    _, revision = assets.publish_factor_revision(factor_id)
    # Two existing immutable revisions prove exact reads never substitute the head.
    assets.save_factor_draft(
        replace(
            draft,
            semantic_version="2",
            source_text="def calculate(api, inputs, parameters):\n    return {'value': inputs['close'] * 2}\n",
            base_revision_fingerprint=revision.revision_fingerprint,
        )
    )
    _, current = assets.publish_factor_revision(factor_id)
    (output / "private-metadata-precondition.json").write_text(
        json.dumps({"first": revision.to_dict(), "current": current.to_dict()}, sort_keys=True)
    )
    database = "onlyalpha_test_native_host_" + operation.replace("-", "")
    only_assert_clickhouse_test_database(database)
    ch = OnlyClickHouseClient(
        OnlyClickHouseConfig(
            os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
            database=database,
            user=os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"],
            password=os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"],
            storage_policy=os.environ["ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY"],
        )
    )
    OnlyClickHouseMigrationAuthority(ch).migrate()
    pg = conninfo_to_dict(dsn)
    pg_user = pg.get("user")
    pg_database = pg.get("dbname")
    if (
        pg.get("host") != "postgres"
        or pg.get("port") != "5432"
        or not isinstance(pg_user, str)
        or not pg_user
        or not isinstance(pg_database, str)
        or not pg_database
    ):
        raise ValueError("CANONICAL_DEV_POSTGRES_REQUIRED")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ONLYALPHA_")}
    env.update(
        ONLYALPHA_NATIVE_DEPLOYMENT="CONTAINED_DEVELOPMENT",
        ONLYALPHA_NATIVE_LOCAL_ADDRESS="127.0.0.1",
        ONLYALPHA_NATIVE_GATEWAY="127.0.0.1",
        ONLYALPHA_NATIVE_PUBLICATION="127.0.0.1:5173",
        ONLYALPHA_NATIVE_SCHEMA=str(resources / "schema"),
        ONLYALPHA_NATIVE_WEB_ASSETS=str(resources / "web"),
        ONLYALPHA_NATIVE_ALGORITHMS=str(resources / "algorithms"),
        ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT=artifact,
        ONLYALPHA_NATIVE_SOURCE_TRUST="/etc/ssl/certs/ca-certificates.crt",
        ONLYALPHA_POSTGRES_DSN=make_conninfo(dsn, sslmode="disable"),
        ONLYALPHA_NATIVE_POSTGRES_PEER=f"{socket.gethostbyname('postgres')}:5432",
        ONLYALPHA_NATIVE_POSTGRES_USER=pg_user,
        ONLYALPHA_NATIVE_POSTGRES_DATABASE=pg_database,
        ONLYALPHA_CLICKHOUSE_URL=os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        ONLYALPHA_CLICKHOUSE_DATABASE=database,
        ONLYALPHA_CLICKHOUSE_USER=os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"],
        ONLYALPHA_CLICKHOUSE_PASSWORD=os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"],
    )
    started = time.monotonic()
    events: queue.Queue[bytes] = queue.Queue()
    with (output / "native.log").open("wb") as log:
        child = subprocess.Popen(
            [str(executable), "--user-data-root", str(data)],
            env=env,
            stdout=log,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert child.stderr is not None

        def read_errors() -> None:
            assert child.stderr is not None
            for line in child.stderr:
                log.write(line)
                log.flush()
                events.put(line)
            events.put(b"")

        reader = threading.Thread(target=read_errors, name="native-host-stderr")
        reader.start()

        def interrupted(number: int, _frame: object) -> None:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            raise InterruptedError(f"native browser verification interrupted by {number}")

        previous = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)}
        try:
            version = build_version = json.loads((resources / "manifest.json").read_text())["version"]
            while True:
                remaining = 20 - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Native Host did not report actual READY within startup budget")
                line = events.get(timeout=remaining)
                if not line:
                    raise RuntimeError("Native Host exited before READY")
                if line.decode().strip() == f"NATIVE_WORKSTATION_READY version={version}":
                    break
            (output / "startup.json").write_text(
                json.dumps(
                    {
                        "version": build_version,
                        "ready_seconds": time.monotonic() - started,
                        "pid": child.pid,
                        "resources": str(resources),
                        "operation_id": operation,
                    },
                    indent=2,
                )
            )
            assert sorted(path.name for path in wal_parent.iterdir()) == sorted(wal_locations)
            for location in wal_locations:
                wal_directory = wal_parent / location / "wal"
                # Only the real owning Wal::from_directory creates this lock.
                # This proves traversal rather than a skip of unknown labels.
                writer_lock = wal_directory / ".writer.lock"
                assert writer_lock.is_file() and not writer_lock.is_symlink()
                assert writer_lock.read_bytes() == b""
                assert {path.name for path in wal_directory.iterdir()} == {".writer.lock"}
            (output / "wal-recovery-locations.json").write_text(json.dumps(wal_locations) + "\n")
            result = 0
            results = {}
            if not args.contract_fuzz or args.tests:
                browser = subprocess.run(
                    ["npm", "exec", "--", "playwright", "test", "--workers=1", *args.tests],
                    cwd=ROOT / "packages/frontend",
                    env={
                        **os.environ,
                        "PLAYWRIGHT_BASE_URL": "http://127.0.0.1:5173",
                        "PLAYWRIGHT_OUTPUT_DIR": str(output / "browser"),
                    },
                )
                result = browser.returncode
                results["browser"] = result
                (output / "functional-results.json").write_text(json.dumps(results, indent=2) + "\n")
            if args.contract_fuzz:
                from scripts.native_contract_fuzz import run_contract_fuzz

                fuzz = run_contract_fuzz(executable, output, ROOT)
                results["contract_fuzz"] = fuzz
                result = result or fuzz
            (output / "functional-results.json").write_text(json.dumps(results, indent=2) + "\n")
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired as error:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise RuntimeError("Native Host did not drain after SIGTERM") from error
            finally:
                reader.join(timeout=5)
                if reader.is_alive():
                    raise RuntimeError("Native stderr owner did not drain")
                remaining_processes = []
                for entry in Path("/proc").iterdir():
                    if entry.name.isdigit():
                        try:
                            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                            if int(fields[2]) == child.pid:
                                remaining_processes.append(int(entry.name))
                        except (FileNotFoundError, ProcessLookupError):
                            continue
                (output / "process-drain.json").write_text(
                    json.dumps(
                        {"pid": child.pid, "exit": child.returncode, "remaining_process_group": remaining_processes},
                        indent=2,
                    )
                )
                if remaining_processes:
                    os.killpg(child.pid, signal.SIGKILL)
                    raise RuntimeError("Native process group did not drain")
                ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")
    if child.returncode != 0:
        raise RuntimeError("Native Host failed its owned lifecycle")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
