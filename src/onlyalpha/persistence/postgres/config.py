"""Secret-safe PostgreSQL configuration boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyPostgresConfig:
    dsn: str

    def __post_init__(self) -> None:
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise ValueError("PostgreSQL DSN is required")

    @classmethod
    def from_environment(cls, name: str = "ONLYALPHA_POSTGRES_DSN") -> OnlyPostgresConfig:
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"{name} is required")
        return cls(value)

    def __repr__(self) -> str:
        return "OnlyPostgresConfig(dsn=<redacted>)"


__all__ = ["OnlyPostgresConfig"]
