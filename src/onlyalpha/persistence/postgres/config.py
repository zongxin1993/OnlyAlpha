"""Secret-safe PostgreSQL configuration boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from psycopg.conninfo import make_conninfo


@dataclass(frozen=True, slots=True)
class OnlyPostgresOperationalConnectionOptions:
    """Repository-owned bounds for short operational control-plane I/O."""

    connect_timeout: timedelta = timedelta(seconds=5)
    statement_timeout: timedelta = timedelta(seconds=5)
    lock_timeout: timedelta = timedelta(seconds=2)
    tcp_user_timeout: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        for name in ("connect_timeout", "statement_timeout", "lock_timeout", "tcp_user_timeout"):
            value = getattr(self, name)
            if value <= timedelta(0):
                raise ValueError(f"{name} must be positive")
        if self.lock_timeout > self.statement_timeout:
            raise ValueError("lock_timeout cannot exceed statement_timeout")
        if self.connect_timeout.total_seconds() < 1:
            raise ValueError("connect_timeout must be at least one second")

    @property
    def worst_case_operation_duration(self) -> timedelta:
        return self.connect_timeout + self.statement_timeout

    def assert_worker_compatible(self, *, heartbeat_interval: timedelta, lease_duration: timedelta) -> None:
        if self.worst_case_operation_duration >= heartbeat_interval:
            raise ValueError("PostgreSQL operational I/O bound must be shorter than heartbeat_interval")
        if self.worst_case_operation_duration >= lease_duration:
            raise ValueError("PostgreSQL operational I/O bound must be shorter than lease_duration")

    def apply(self, dsn: str) -> str:
        """Apply explicit runtime bounds without creating another connection identity."""

        return make_conninfo(
            dsn,
            connect_timeout=int(self.connect_timeout.total_seconds()),
            options=(
                f"-c statement_timeout={_milliseconds(self.statement_timeout)}ms "
                f"-c lock_timeout={_milliseconds(self.lock_timeout)}ms"
            ),
            tcp_user_timeout=_milliseconds(self.tcp_user_timeout),
            keepalives=1,
            keepalives_idle=5,
            keepalives_interval=2,
            keepalives_count=2,
        )


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

    def operational_dsn(self, options: OnlyPostgresOperationalConnectionOptions | None = None) -> str:
        return (options or OnlyPostgresOperationalConnectionOptions()).apply(self.dsn)


def _milliseconds(value: timedelta) -> int:
    milliseconds = int(value.total_seconds() * 1000)
    if milliseconds < 1:
        raise ValueError("PostgreSQL timeout must be at least one millisecond")
    return milliseconds


__all__ = [name for name in globals() if name.startswith("Only")]
