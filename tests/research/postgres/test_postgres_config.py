from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg.conninfo import conninfo_to_dict

from onlyalpha.persistence.postgres import (
    OnlyPostgresConfig,
    OnlyPostgresOperationalConnectionOptions,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "field",
    ("connect_timeout", "statement_timeout", "lock_timeout", "tcp_user_timeout"),
)
def test_operational_connection_timeouts_must_be_positive(field: str) -> None:
    values = {
        "connect_timeout": timedelta(seconds=5),
        "statement_timeout": timedelta(seconds=5),
        "lock_timeout": timedelta(seconds=2),
        "tcp_user_timeout": timedelta(seconds=5),
    }
    values[field] = timedelta(0)

    with pytest.raises(ValueError, match=rf"^{field} must be positive$"):
        OnlyPostgresOperationalConnectionOptions(**values)


def test_operational_connection_timeouts_preserve_ordering_and_resolution_bounds() -> None:
    with pytest.raises(ValueError, match="lock_timeout cannot exceed statement_timeout"):
        OnlyPostgresOperationalConnectionOptions(
            statement_timeout=timedelta(seconds=1),
            lock_timeout=timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="connect_timeout must be at least one second"):
        OnlyPostgresOperationalConnectionOptions(connect_timeout=timedelta(milliseconds=999))

    submillisecond = OnlyPostgresOperationalConnectionOptions(tcp_user_timeout=timedelta(microseconds=500))
    with pytest.raises(ValueError, match="PostgreSQL timeout must be at least one millisecond"):
        submillisecond.apply("postgresql://localhost/onlyalpha")


def test_operational_connection_bound_must_fit_worker_heartbeat_and_lease() -> None:
    options = OnlyPostgresOperationalConnectionOptions(
        connect_timeout=timedelta(seconds=2),
        statement_timeout=timedelta(seconds=3),
    )
    assert options.worst_case_operation_duration == timedelta(seconds=5)

    with pytest.raises(ValueError, match="shorter than heartbeat_interval"):
        options.assert_worker_compatible(
            heartbeat_interval=timedelta(seconds=5),
            lease_duration=timedelta(seconds=10),
        )
    with pytest.raises(ValueError, match="shorter than lease_duration"):
        options.assert_worker_compatible(
            heartbeat_interval=timedelta(seconds=6),
            lease_duration=timedelta(seconds=5),
        )

    options.assert_worker_compatible(
        heartbeat_interval=timedelta(seconds=6),
        lease_duration=timedelta(seconds=7),
    )


def test_postgres_config_requires_dsn_and_environment_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL DSN is required"):
        OnlyPostgresConfig("")

    monkeypatch.delenv("ONLYALPHA_TEST_POSTGRES_DSN", raising=False)
    with pytest.raises(ValueError, match="ONLYALPHA_TEST_POSTGRES_DSN is required"):
        OnlyPostgresConfig.from_environment("ONLYALPHA_TEST_POSTGRES_DSN")

    monkeypatch.setenv(
        "ONLYALPHA_TEST_POSTGRES_DSN",
        "postgresql://onlyalpha:super-secret@localhost/onlyalpha",
    )
    config = OnlyPostgresConfig.from_environment("ONLYALPHA_TEST_POSTGRES_DSN")
    assert config.dsn.endswith("@localhost/onlyalpha")
    assert repr(config) == "OnlyPostgresConfig(dsn=<redacted>)"
    assert "super-secret" not in repr(config)


def test_operational_dsn_applies_repository_owned_connection_policy() -> None:
    config = OnlyPostgresConfig("postgresql://onlyalpha:secret@localhost/onlyalpha")
    operational = conninfo_to_dict(
        config.operational_dsn(
            OnlyPostgresOperationalConnectionOptions(
                connect_timeout=timedelta(seconds=3),
                statement_timeout=timedelta(milliseconds=2500),
                lock_timeout=timedelta(milliseconds=750),
                tcp_user_timeout=timedelta(milliseconds=1250),
            )
        )
    )

    assert operational["connect_timeout"] == "3"
    assert operational["tcp_user_timeout"] == "1250"
    assert operational["keepalives"] == "1"
    assert operational["keepalives_idle"] == "5"
    assert operational["keepalives_interval"] == "2"
    assert operational["keepalives_count"] == "2"
    assert operational["options"] == ("-c timezone=UTC -c statement_timeout=2500ms -c lock_timeout=750ms")
