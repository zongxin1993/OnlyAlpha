"""Explicit PostgreSQL operator tooling; application startup never invokes this module."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    ONLYALPHA_POSTGRES_CLIENT_MAJOR,
    OnlyPostgresConfig,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchOperationsStore,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerifier,
    only_assert_supported_postgres_server,
    only_discover_postgres_migrations,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreIdentity
from onlyalpha.research.run import OnlyResearchRunId


def _authority(dsn: str) -> OnlyPostgresMigrationAuthority:
    return OnlyPostgresMigrationAuthority(dsn)


def _verifier(dsn: str) -> OnlyPostgresSchemaVerifier:
    return OnlyPostgresSchemaVerifier(dsn)


def _status_payload(verifier: OnlyPostgresSchemaVerifier) -> dict[str, object]:
    status = verifier.status()
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


def _tool_version(name: str) -> str:
    completed = subprocess.run([_tool(name), "--version"], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _tool_major(name: str) -> int:
    version_text = _tool_version(name)
    match = re.search(r"(?:PostgreSQL\)\s+|\b)([0-9]+)(?:\.[0-9]+)", version_text)
    if match is None:
        raise RuntimeError(f"POSTGRES_CLIENT_VERSION_INVALID: {name}")
    return int(match.group(1))


def _assert_client_major(name: str) -> str:
    version_text = _tool_version(name)
    if _tool_major(name) != ONLYALPHA_POSTGRES_CLIENT_MAJOR:
        raise RuntimeError(f"POSTGRES_CLIENT_MAJOR_UNSUPPORTED: {name} must be major {ONLYALPHA_POSTGRES_CLIENT_MAJOR}")
    return version_text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repository_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, cwd=Path(__file__).parents[1]
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _metadata_path(backup: Path) -> Path:
    return backup.with_name(f"{backup.name}.metadata.json")


def _backup(dsn: str, destination: Path) -> Path:
    _verifier(dsn).assert_compatible()
    server = only_assert_supported_postgres_server(dsn)
    dump_version = _assert_client_major("pg_dump")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_tool("pg_dump"), "--format=custom", "--file", str(destination)],
        env=_client_environment(dsn),
        check=True,
    )
    metadata = {
        "schema_version": 1,
        "backup_sha256": _sha256(destination),
        "created_at": datetime.now(UTC).isoformat(),
        "repository_version": importlib.metadata.version("onlyalpha"),
        "repository_sha": _repository_sha(),
        "postgres_server_version": server.version,
        "pg_dump_version": dump_version,
        "migrations": [
            {"migration_id": item.migration_id, "checksum_sha256": item.checksum_sha256}
            for item in only_discover_postgres_migrations()
        ],
    }
    metadata_path = _metadata_path(destination)
    temporary = metadata_path.with_name(f".{metadata_path.name}.tmp")
    temporary.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, metadata_path)
    return metadata_path


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
    only_assert_supported_postgres_server(source_dsn)
    only_assert_supported_postgres_server(target_dsn)
    _assert_client_major("pg_restore")
    metadata_path = _metadata_path(backup)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("backup_sha256") != _sha256(backup):
        raise RuntimeError("backup metadata checksum verification failed")
    subprocess.run(
        [_tool("pg_restore"), "--exit-on-error", "--dbname", str(target["dbname"]), str(backup)],
        env=_client_environment(target_dsn),
        check=True,
    )
    _verifier(target_dsn).assert_compatible()
    if run_id is not None:
        selected = OnlyResearchRunId(run_id)
        OnlyPostgresResearchRunStore(target_dsn).load(selected)
        OnlyPostgresResearchOperationsStore(target_dsn).load_operational_snapshot(run_id=selected, limit=1)
    _verifier(source_dsn).assert_compatible()


def _validate(dsn: str, run_id: str | None) -> None:
    _verifier(dsn).assert_compatible()
    only_assert_supported_postgres_server(dsn)
    selected = None if run_id is None else OnlyResearchRunId(run_id)
    snapshot = OnlyPostgresResearchOperationsStore(dsn).load_operational_snapshot(run_id=selected, limit=100)
    if selected is not None and not snapshot.runs:
        raise RuntimeError("selected Research Run does not exist")


def _initialize_deployment(dsn: str, user_data_root: Path) -> str:
    _verifier(dsn).assert_compatible()
    only_assert_supported_postgres_server(dsn)
    layout = OnlyUserDataLayout(user_data_root)
    identity = OnlyResearchSemanticStoreIdentity(layout.research_root).initialize()
    OnlyPostgresResearchDeploymentStore(dsn).initialize(identity)
    for root in (
        layout.research_dataset_root,
        layout.research_calculation_result_root,
        layout.research_statistics_result_root,
        layout.research_result_root,
        layout.research_artifact_root,
    ):
        root.mkdir(parents=True, exist_ok=True)
    return str(identity)


def main() -> int:
    parser = argparse.ArgumentParser(description="OnlyAlpha PostgreSQL authority operator tool")
    parser.add_argument("--dsn-env", default="ONLYALPHA_POSTGRES_DSN")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("plan")
    commands.add_parser("migrate")
    initialize = commands.add_parser("initialize-deployment")
    initialize.add_argument("--user-data-root", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--run-id")
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore-test")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target-dsn-env", default="ONLYALPHA_POSTGRES_RESTORE_TEST_DSN")
    restore.add_argument("--run-id")
    args = parser.parse_args()
    dsn = OnlyPostgresConfig.from_environment(args.dsn_env).dsn
    authority = _authority(dsn)
    verifier = _verifier(dsn)
    if args.command == "status":
        print(json.dumps(_status_payload(verifier), sort_keys=True))
        return 0 if verifier.status().compatible else 2
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
    if args.command == "initialize-deployment":
        store_id = _initialize_deployment(dsn, args.user_data_root)
        print(json.dumps({"deployment": "BOUND", "semantic_store_id": store_id}, sort_keys=True))
        return 0
    if args.command == "validate":
        _validate(dsn, args.run_id)
        print(json.dumps({"domain_validation": "VERIFIED"}, sort_keys=True))
        return 0
    if args.command == "backup":
        metadata = _backup(dsn, args.destination)
        print(json.dumps({"backup": str(args.destination), "metadata": str(metadata)}, sort_keys=True))
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
