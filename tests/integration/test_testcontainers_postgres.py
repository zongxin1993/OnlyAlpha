from __future__ import annotations

import psycopg
import pytest

postgres_module = pytest.importorskip("testcontainers.postgres")
PostgresContainer = postgres_module.PostgresContainer

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.postgres]

POSTGRES_IMAGE = "postgres:18.6@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280"


def test_testcontainers_provides_real_postgres_round_trip() -> None:
    with PostgresContainer(
        POSTGRES_IMAGE,
        username="onlyalpha",
        password="onlyalpha_test",
        dbname="onlyalpha_test",
    ) as postgres:
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        dsn = f"postgresql://onlyalpha:onlyalpha_test@{host}:{port}/onlyalpha_test"
        with psycopg.connect(dsn, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version")
                version = cursor.fetchone()
                assert version is not None
                assert str(version[0]).split(".", maxsplit=1)[0] == "18"

                cursor.execute("CREATE TABLE quality_tooling_probe (id integer PRIMARY KEY, value text NOT NULL)")
                cursor.execute("INSERT INTO quality_tooling_probe (id, value) VALUES (1, 'verified')")
                cursor.execute("SELECT value FROM quality_tooling_probe WHERE id = 1")
                assert cursor.fetchone() == ("verified",)
