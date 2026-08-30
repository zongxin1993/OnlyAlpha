"""Small synchronous HTTP client with explicit synchronous insert settings."""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from typing import cast

from .config import OnlyClickHouseConfig


class OnlyClickHouseError(RuntimeError):
    pass


class OnlyClickHouseClient:
    def __init__(self, config: OnlyClickHouseConfig) -> None:
        self.config = config

    def execute(self, sql: str, *, database: str | None = None) -> str:
        return self._request(sql.encode("utf-8"), database=database)

    def execute_script(self, sql: str, *, database: str | None = None) -> None:
        statements = tuple(item.strip() for item in sql.split(";") if item.strip())
        if not statements:
            raise ValueError("CLICKHOUSE_SQL_SCRIPT_EMPTY")
        for statement in statements:
            self.execute(statement, database=database)

    def insert_json_each_row(self, table: str, rows: Iterable[Mapping[str, object]]) -> None:
        payload = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
        query = (
            f"INSERT INTO {table} SETTINGS async_insert=0, wait_for_async_insert=1, "
            "insert_deduplicate=1 FORMAT JSONEachRow\n"
        )
        self._request((query + payload).encode("utf-8"))

    def query_json(self, sql: str, *, database: str | None = None) -> tuple[dict[str, object], ...]:
        raw = json.loads(self._request(f"{sql} FORMAT JSON".encode(), database=database))
        rows = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise OnlyClickHouseError("CLICKHOUSE_JSON_RESPONSE_INVALID")
        return tuple(dict(row) for row in rows)

    def _request(self, payload: bytes, *, database: str | None = None) -> str:
        params = urllib.parse.urlencode({"database": database or self.config.database})
        request = urllib.request.Request(f"{self.config.url.rstrip('/')}?{params}", data=payload, method="POST")
        token = base64.b64encode(f"{self.config.user}:{self.config.password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return cast(str, response.read().decode("utf-8"))
        except Exception as exc:
            raise OnlyClickHouseError(f"CLICKHOUSE_REQUEST_FAILED:{type(exc).__name__}") from exc


__all__ = ["OnlyClickHouseClient", "OnlyClickHouseError"]
