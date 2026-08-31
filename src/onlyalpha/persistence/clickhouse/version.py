"""Frozen ClickHouse application compatibility policy."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .client import OnlyClickHouseClient

ONLYALPHA_CLICKHOUSE_MAJOR = 26
ONLYALPHA_CLICKHOUSE_MINOR = 3


@dataclass(frozen=True, slots=True)
class OnlyClickHouseServerVersion:
    version: str
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> OnlyClickHouseServerVersion:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.\d+)?", value.strip())
        if match is None:
            raise RuntimeError("CLICKHOUSE_SERVER_VERSION_INVALID")
        major, minor, patch = (int(item) for item in match.groups())
        return cls(value.strip(), major, minor, patch)


def only_clickhouse_server_version(client: OnlyClickHouseClient) -> OnlyClickHouseServerVersion:
    rows = client.query_json("SELECT version() AS version", database="default")
    if len(rows) != 1 or "version" not in rows[0]:
        raise RuntimeError("CLICKHOUSE_SERVER_VERSION_INSPECTION_FAILED")
    return OnlyClickHouseServerVersion.parse(str(rows[0]["version"]))


def only_assert_supported_clickhouse_server(client: OnlyClickHouseClient) -> OnlyClickHouseServerVersion:
    inspected = only_clickhouse_server_version(client)
    if (inspected.major, inspected.minor) != (ONLYALPHA_CLICKHOUSE_MAJOR, ONLYALPHA_CLICKHOUSE_MINOR):
        raise RuntimeError(
            "CLICKHOUSE_SERVER_FAMILY_UNSUPPORTED: "
            f"expected {ONLYALPHA_CLICKHOUSE_MAJOR}.{ONLYALPHA_CLICKHOUSE_MINOR}.x, got {inspected.version}"
        )
    return inspected


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLYALPHA_"))]
