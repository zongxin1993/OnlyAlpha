from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import psycopg
import pytest

from onlyalpha.persistence.postgres import only_assert_postgres_test_database


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ONLYALPHA_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ONLYALPHA_POSTGRES_DSN is required for the canonical Compose research-postgres lane")
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    return dsn


@pytest.fixture
def isolated_postgres_cluster(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Physically fresh roles, inside the non-root canonical test container only."""
    assert Path.cwd() == Path("/workspace"), "canonical Compose test container required"
    assert os.geteuid() != 0, "PostgreSQL must run as the unprivileged test user"
    binaries = Path(os.environ["ONLYALPHA_POSTGRES_CLIENT_BIN_DIR"])
    with TemporaryDirectory(prefix="postgres-cluster-") as temporary:
        root = Path(temporary)
        data, sockets = root / "data", root / "sockets"
        sockets.mkdir(mode=0o700)
        log = Path("test-results") / (root.name + ".log")
        log.parent.mkdir(exist_ok=True)
        subprocess.run(
            [
                str(binaries / "initdb"),
                "-D",
                str(data),
                "-U",
                "onlyalpha",
                "--locale=C",
                "--encoding=UTF8",
                "--auth-local=trust",
                "--auth-host=reject",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        # Explicit private paths only: no TCP listener, Docker socket, shared
        # PGDATA, host PostgreSQL service, or secondary connection env variable.
        with (data / "postgresql.conf").open("a") as configuration:
            configuration.write(f"\nlisten_addresses = ''\nunix_socket_directories = '{sockets}'\n")
        try:
            subprocess.run(
                [str(binaries / "pg_ctl"), "-D", str(data), "-l", str(log.resolve()), "-w", "start"],
                check=True,
                capture_output=True,
                text=True,
            )
            admin = "postgresql://onlyalpha@/postgres?" + urlencode({"host": str(sockets)})
            with psycopg.connect(admin, autocommit=True) as connection:
                assert 180000 <= connection.info.server_version < 190000
                connection.execute("CREATE DATABASE chart_native_migration_test")
            dsn = "postgresql://onlyalpha@/chart_native_migration_test?" + urlencode({"host": str(sockets)})
            only_assert_postgres_test_database(dsn)
            monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", dsn)
            yield dsn
        finally:
            # pg_ctl startup can fail after launching the server. Stop only the
            # cluster created above, even when setup/test fails before yielding.
            if (data / "postmaster.pid").exists():
                subprocess.run(
                    [str(binaries / "pg_ctl"), "-D", str(data), "-w", "-m", "fast", "stop"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            assert not (data / "postmaster.pid").exists()
            print(f"ISOLATED_POSTGRES_CLUSTER_STOPPED {root.name}")
