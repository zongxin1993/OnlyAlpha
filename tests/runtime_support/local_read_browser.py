"""Loopback acceptance composition: real Product services and isolated PG/CH facts.

Only the external Provider and Integration resolver use deterministic contract fakes.
No HTTP response or Browser data is intercepted or manufactured.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg
import uvicorn
from fastapi import FastAPI, Request
from onlyalpha_http_server.local_read_access import OnlyLocalReadIngress, only_load_local_read_configuration
from onlyalpha_http_server.market_data import (
    create_market_data_router,
    create_market_data_stream_router,
    market_data_error_response,
)
from psycopg import sql

from onlyalpha.application.market_data_product import OnlyMarketDataProductError, OnlyMarketDataProductService
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.application.source_read_access import OnlySourceReadAccessError
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataRequestStatus
from onlyalpha.data.models import OnlyMarketDataSubscriptionResult, OnlyRealtimeBarPreviewV1
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType
from onlyalpha.persistence.clickhouse import OnlyClickHouseMarketFactStore, OnlyClickHouseMigrationAuthority
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog, only_assert_postgres_test_database
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from tests.application.test_market_data_product import BASE, INSTRUMENT, MINUTE_NS, _FakeSource, _reference, _service
from tests.market_data_durable.test_real_database_acceptance import _clickhouse


def _inventory(dsn, clickhouse):
    inventory = {}
    with psycopg.connect(dsn) as connection:
        names = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
        for (name,) in names:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))).fetchall()
            serialized = sorted(json.dumps(row[0], sort_keys=True, default=str) for row in rows)
            inventory["postgres:" + name] = {
                "count": len(rows),
                "sha256": hashlib.sha256(json.dumps(serialized).encode()).hexdigest(),
            }
    for row in clickhouse.query_json("SELECT name FROM system.tables WHERE database=currentDatabase() ORDER BY name"):
        name = row["name"]
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            raise ValueError("UNSAFE_TEST_TABLE")
        rows = clickhouse.query_json(f"SELECT * FROM `{name}`")
        serialized = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
        inventory["clickhouse:" + name] = {
            "count": len(rows),
            "sha256": hashlib.sha256(json.dumps(serialized).encode()).hexdigest(),
        }
    return inventory


async def wait_for_read_cleanup(ingress: OnlyLocalReadIngress) -> None:
    # An observer must never acquire cancellation authority over retained work.
    pending = tuple(ingress._work)
    if pending:
        await asyncio.gather(*(asyncio.shield(owner) for owner in pending))


def main() -> None:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    OnlyPostgresMigrationAuthority(dsn).migrate()
    client = _clickhouse("onlyalpha_test_local_read_browser")
    OnlyClickHouseMigrationAuthority(client).migrate()
    artifacts = Path("test-results/local-read-browser")
    artifacts.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="onlyalpha-read-browser-") as raw:
        root = Path(raw)
        harness = _service(root)
        catalog = OnlyPostgresMarketDataCatalog(dsn, now=lambda: BASE + timedelta(hours=1))
        facts = OnlyClickHouseMarketFactStore(client)
        product = OnlyMarketDataProductService(
            integrations=harness.service._integrations,
            resolver=harness.service._resolver,
            data_sources=harness.service._data_sources,
            catalog=catalog,
            fact_store=facts,
            wal_root=root / "history",
            clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
            logger=logging.getLogger(__name__),
            now=lambda: BASE + timedelta(hours=1),
        )
        assert product._ranges._catalog is catalog and product._ranges._facts is facts
        reference = _reference(harness.revision_fingerprint)
        end = (OnlyBacktestClock(BASE + timedelta(hours=1)).timestamp_ns() // MINUTE_NS) * MINUTE_NS
        acquired = product.acquire_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=end - 1440 * MINUTE_NS, end_ns=end
        )
        assert acquired.status == "COMPLETE"
        before = _inventory(dsn, client)
        (artifacts / "before.json").write_text(json.dumps(before, indent=2))

        class PreviewSource(_FakeSource):
            def subscribe(self, request):
                self._request.market_data_preview_sink(
                    OnlyRealtimeBarPreviewV1(
                        self._request.source_id,
                        INSTRUMENT,
                        OnlyBarType(INSTRUMENT, OnlyBarSemantic.fixed_duration(1)),
                        end,
                        end + MINUTE_NS,
                        "100.00",
                        "102.00",
                        "99.00",
                        "101.00",
                        "2.00000",
                        end,
                        end,
                    )
                )
                return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "preview")

            def unsubscribe(self, request):
                return None

        harness.factory.create = lambda request: PreviewSource(request, provider=harness.provider)
        stream = OnlyMarketDataStreamProductService(
            historical=product,
            catalog=catalog,
            fact_store=facts,
            wal_root=root / "live",
            clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
            logger=logging.getLogger(__name__),
        )
        config_path = root / "credentials.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "subject_id": "local-operator",
                    "bearer_sha256": hashlib.sha256(("ee" * 32).encode()).hexdigest(),
                    "origin": "http://127.0.0.1:4173",
                    "grants": [
                        {
                            "integration_id": reference.integration_id,
                            "integration_revision_fingerprint": reference.integration_revision_fingerprint,
                            "expected_type_id": reference.expected_type_id,
                            "source_id": "test.spot.live",
                            "environment": "LIVE",
                            "permissions": ["CLOSED_HISTORY", "REALTIME_PREVIEW"],
                        }
                    ],
                }
            )
        )
        config_path.chmod(0o600)
        app = FastAPI()
        app.include_router(create_market_data_router(product))
        app.include_router(create_market_data_stream_router(stream))

        @app.exception_handler(OnlyMarketDataProductError)
        async def market_error(request: Request, error: OnlyMarketDataProductError):
            return market_data_error_response(error)

        @app.exception_handler(OnlySourceReadAccessError)
        async def access_error(request: Request, error: OnlySourceReadAccessError):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"schema_version": 1, "error": {"phase": "QUERY", "code": error.code, "detail": error.code}},
                status_code=401 if error.code == "LOCAL_READ_UNAUTHORIZED" else 403,
            )

        @app.get("/health/ready")
        async def health():
            ingress = app.state.local_read_ingress
            # A real completion barrier: cleanup owns its work, not browser canvas state.
            await wait_for_read_cleanup(ingress)
            assert not stream._sessions
            after = _inventory(dsn, client)
            (artifacts / "after.json").write_text(json.dumps(after, indent=2))
            assert after == before, "Protected business fact inventory changed"
            return {"ready": True}

        app.add_middleware(OnlyLocalReadIngress, configuration=only_load_local_read_configuration(config_path))
        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=8000,
                ws_max_size=4096,
                ws_per_message_deflate=False,
                proxy_headers=False,
                access_log=False,
            )
        finally:
            stream.close()
            after = _inventory(dsn, client)
            (artifacts / "after.json").write_text(json.dumps(after, indent=2))
            assert after == before, "Protected business fact inventory changed"


if __name__ == "__main__":
    main()
