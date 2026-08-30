"""Explicit ClickHouse market-data schema and bounded recovery operator tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMigrationAuthority,
)

_TABLES = ("market_raw_event", "market_trade", "market_bar", "market_reference_price")


def _authority() -> OnlyClickHouseMigrationAuthority:
    return OnlyClickHouseMigrationAuthority(OnlyClickHouseClient(OnlyClickHouseConfig.from_environment()))


def _client() -> OnlyClickHouseClient:
    return OnlyClickHouseClient(OnlyClickHouseConfig.from_environment())


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _backup_segment(client: OnlyClickHouseClient, segment_id: str, destination: Path) -> None:
    if not segment_id.strip():
        raise ValueError("CLICKHOUSE_BACKUP_SEGMENT_ID_INVALID")
    tables = {
        table: client.query_json(f"SELECT * FROM {table} WHERE segment_id={_quote(segment_id)} ORDER BY tuple(*)")
        for table in _TABLES
    }
    if not any(tables.values()):
        raise RuntimeError("CLICKHOUSE_BACKUP_SEGMENT_NOT_FOUND")
    payload = json.dumps(
        {"schema_version": 1, "segment_id": segment_id, "tables": tables},
        sort_keys=True,
        separators=(",", ":"),
    )
    checksum = hashlib.sha256(payload.encode()).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(payload)
    destination.with_suffix(destination.suffix + ".sha256").write_text(checksum + "\n")


def _restore_segment(client: OnlyClickHouseClient, source: Path) -> None:
    payload = source.read_text()
    checksum = source.with_suffix(source.suffix + ".sha256").read_text().strip()
    if hashlib.sha256(payload.encode()).hexdigest() != checksum:
        raise RuntimeError("CLICKHOUSE_BACKUP_CHECKSUM_MISMATCH")
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("tables"), dict):
        raise RuntimeError("CLICKHOUSE_BACKUP_FORMAT_INVALID")
    for table in _TABLES:
        rows = value["tables"].get(table)
        if not isinstance(rows, list):
            raise RuntimeError("CLICKHOUSE_BACKUP_TABLE_MISSING")
        if rows:
            client.insert_json_each_row(table, rows)
        restored = client.query_json(
            f"SELECT * FROM {table} WHERE segment_id={_quote(str(value['segment_id']))} ORDER BY tuple(*)"
        )
        if tuple(rows) != restored:
            raise RuntimeError("CLICKHOUSE_RESTORE_CONTENT_MISMATCH")


def main() -> int:
    parser = argparse.ArgumentParser(description="OnlyAlpha ClickHouse market-data operator tool")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("plan")
    commands.add_parser("migrate")
    commands.add_parser("validate")
    cold = commands.add_parser("move-partition-cold")
    cold.add_argument("table", choices=_TABLES)
    cold.add_argument("partition")
    cold.add_argument("--volume", default="cold")
    backup = commands.add_parser("backup-segment")
    backup.add_argument("segment_id")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore-segment")
    restore.add_argument("source", type=Path)
    args = parser.parse_args()
    authority = _authority()
    if args.command == "status":
        pending = authority.plan()
        print(json.dumps({"compatible": not pending, "pending": [item.migration_id for item in pending]}))
        return 0 if not pending else 2
    if args.command == "plan":
        print(json.dumps([item.migration_id for item in authority.plan()]))
        return 0
    if args.command == "migrate":
        print(json.dumps({"applied": authority.migrate()}))
        return 0
    if args.command == "validate":
        authority.validate()
        print(json.dumps({"schema": "VERIFIED"}))
        return 0
    client = _client()
    if args.command == "move-partition-cold":
        if not args.partition.isdigit() or not args.volume.replace("_", "").isalnum():
            raise ValueError("CLICKHOUSE_PARTITION_OR_VOLUME_INVALID")
        before = {
            table: client.query_json(f"SELECT count() count, groupBitXor(cityHash64(tuple(*))) hash FROM {table}")
            for table in _TABLES
        }
        client.execute(f"ALTER TABLE {args.table} MOVE PARTITION {args.partition} TO VOLUME '{args.volume}'")
        after = {
            table: client.query_json(f"SELECT count() count, groupBitXor(cityHash64(tuple(*))) hash FROM {table}")
            for table in _TABLES
        }
        if before != after:
            raise RuntimeError("CLICKHOUSE_HOT_COLD_LOGICAL_RESULT_CHANGED")
        print(json.dumps({"hot_cold_move": "VERIFIED"}))
        return 0
    if args.command == "backup-segment":
        _backup_segment(client, args.segment_id, args.destination)
        print(json.dumps({"backup": str(args.destination)}))
        return 0
    if args.command == "restore-segment":
        _restore_segment(client, args.source)
        print(json.dumps({"restore": "VERIFIED"}))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
