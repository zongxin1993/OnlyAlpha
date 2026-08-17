"""Explicit PostgreSQL operator tooling; application startup never invokes this module."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from onlyalpha.persistence.postgres import (
    OnlyPostgresConfig,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.research.run import OnlyResearchRunId


def _authority(dsn: str) -> OnlyPostgresMigrationAuthority:
    return OnlyPostgresMigrationAuthority(dsn)


def _status_payload(authority: OnlyPostgresMigrationAuthority) -> dict[str, object]:
    status = authority.status()
    return {
        "verdict": status.verdict.value,
        "compatible": status.compatible,
        "repository_migrations": status.repository_migrations,
        "applied_migrations": status.applied_migrations,
        "pending_migrations": status.pending_migrations,
        "detail": status.detail,
    }


def _client_environment(dsn: str) -> dict[str, str]:
    values = conninfo_to_dict(dsn)
    mapping = {
        "host": "PGHOST",
        "port": "PGPORT",
        "dbname": "PGDATABASE",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
    }
    environment = os.environ.copy()
    for key, target in mapping.items():
        if value := values.get(key):
            environment[target] = str(value)
    return environment


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"required PostgreSQL client tool is unavailable: {name}")
    return executable


def _backup(dsn: str, destination: Path) -> None:
    _authority(dsn).assert_compatible()
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_tool("pg_dump"), "--format=custom", "--file", str(destination)],
        env=_client_environment(dsn),
        check=True,
    )


def _restore_test(source_dsn: str, target_dsn: str, backup: Path, run_id: str | None) -> None:
    source = conninfo_to_dict(source_dsn)
    target = conninfo_to_dict(target_dsn)
    if source.get("dbname") == target.get("dbname") and source.get("host") == target.get("host"):
        raise RuntimeError("restore-test target must be isolated from the source database")
    if not str(target.get("dbname", "")).endswith("_restore_test"):
        raise RuntimeError("restore-test target database name must end with _restore_test")
    with psycopg.connect(target_dsn) as connection:
        result = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
        if result is None:
            raise RuntimeError("restore-test target inspection returned no result")
        count = result[0]
    if count != 0:
        raise RuntimeError("restore-test target must be empty")
    subprocess.run(
        [_tool("pg_restore"), "--exit-on-error", "--dbname", str(target["dbname"]), str(backup)],
        env=_client_environment(target_dsn),
        check=True,
    )
    _authority(target_dsn).assert_compatible()
    if run_id is not None:
        OnlyPostgresResearchRunStore(target_dsn).load(OnlyResearchRunId(run_id))
    _authority(source_dsn).assert_compatible()


def main() -> int:
    parser = argparse.ArgumentParser(description="OnlyAlpha PostgreSQL authority operator tool")
    parser.add_argument("--dsn-env", default="ONLYALPHA_POSTGRES_DSN")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("plan")
    commands.add_parser("migrate")
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore-test")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target-dsn-env", default="ONLYALPHA_POSTGRES_RESTORE_TEST_DSN")
    restore.add_argument("--run-id")
    args = parser.parse_args()
    dsn = OnlyPostgresConfig.from_environment(args.dsn_env).dsn
    authority = _authority(dsn)
    if args.command == "status":
        print(json.dumps(_status_payload(authority), sort_keys=True))
        return 0 if authority.status().compatible else 2
    if args.command == "plan":
        print(
            json.dumps(
                [
                    {"migration_id": item.migration_id, "checksum_sha256": item.checksum_sha256}
                    for item in authority.plan()
                ],
                sort_keys=True,
            )
        )
        return 0
    if args.command == "migrate":
        print(json.dumps({"applied": authority.migrate()}, sort_keys=True))
        return 0
    if args.command == "backup":
        _backup(dsn, args.destination)
        print(json.dumps({"backup": str(args.destination)}, sort_keys=True))
        return 0
    if args.command == "restore-test":
        target = OnlyPostgresConfig.from_environment(args.target_dsn_env).dsn
        _restore_test(dsn, target, args.backup, args.run_id)
        print(json.dumps({"restore_test": "VERIFIED"}, sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"database operation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from exc
