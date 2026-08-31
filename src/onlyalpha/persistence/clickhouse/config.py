"""Secret-safe ClickHouse configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class OnlyClickHouseConfig:
    url: str
    database: str = "onlyalpha"
    user: str = "default"
    password: str = ""
    storage_policy: str = "hot_cold"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("CLICKHOUSE_URL_INVALID")
        if not _IDENTIFIER.fullmatch(self.database) or not _IDENTIFIER.fullmatch(self.storage_policy):
            raise ValueError("CLICKHOUSE_IDENTIFIER_INVALID")
        if self.timeout_seconds <= 0:
            raise ValueError("CLICKHOUSE_TIMEOUT_INVALID")

    @classmethod
    def from_environment(cls) -> OnlyClickHouseConfig:
        url = os.environ.get("ONLYALPHA_CLICKHOUSE_URL")
        if not url:
            raise ValueError("ONLYALPHA_CLICKHOUSE_URL is required")
        return cls(
            url=url,
            database=os.environ.get("ONLYALPHA_CLICKHOUSE_DATABASE", "onlyalpha"),
            user=os.environ.get("ONLYALPHA_CLICKHOUSE_USER", "default"),
            password=os.environ.get("ONLYALPHA_CLICKHOUSE_PASSWORD", ""),
            storage_policy=os.environ.get("ONLYALPHA_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
        )

    def __repr__(self) -> str:
        return f"OnlyClickHouseConfig(url={self.url!r}, database={self.database!r}, credentials=<redacted>)"


def only_assert_clickhouse_test_database(database: str, *, restore: bool = False) -> str:
    prefix = "onlyalpha_restore_" if restore else "onlyalpha_test_"
    if not database.startswith(prefix) or not _IDENTIFIER.fullmatch(database):
        purpose = "RESTORE" if restore else "TEST"
        raise RuntimeError(f"CLICKHOUSE_{purpose}_DATABASE_REQUIRED")
    return database


__all__ = ["OnlyClickHouseConfig", "only_assert_clickhouse_test_database"]
