"""Protected Shipping acceptance over real Product, plugins and isolated PG/CH.

By default external Binance wire payloads and preview delivery are deterministic
contract fakes. An explicit recorded-wire input instead replays hash-bound public
Binance history; neither mode certifies live transport or deployment. All setup
writes precede the browser interval; queries use actual owning readers.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import resource
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import create_autospec, patch
from urllib.request import Request

import uvicorn
from onlyalpha_http_server.app import create_product_app
from onlyalpha_http_server.composition import only_configure_product_registries
from onlyalpha_http_server.health import OnlyKernelResearchReadinessProjection
from onlyalpha_http_server.local_read_access import only_load_local_read_configuration
from onlyalpha_plugin_binance.spot.data_source.resource import OnlyBinanceSpotDataSource
from starlette.types import Receive, Scope, Send

from onlyalpha.application.integration_application import (
    OnlyCreateIntegration,
    OnlyIntegrationCommandService,
    OnlyIntegrationQueryService,
    OnlyPublishIntegrationRevision,
    OnlySetIntegrationLifecycle,
)
from onlyalpha.application.integration_configuration import OnlyIntegrationId, OnlyIntegrationLifecycleState
from onlyalpha.application.integration_probe import OnlyIntegrationOperationalQueryService, OnlyIntegrationProbeService
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeResolver
from onlyalpha.application.integration_type_catalog import OnlyIntegrationProbeCatalog, OnlyIntegrationTypeCatalog
from onlyalpha.application.market_data_product import OnlyMarketDataProductService, OnlyMarketDataSourceReferenceV1
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.qualification_product import OnlyQualificationProductService, OnlyQualificationQueryService
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeProductService,
    OnlyStrategyPromotionProductService,
    OnlyStrategyQueryService,
)
from onlyalpha.backtest import OnlyBacktestCommandService, OnlyBacktestQueryService
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataRequestStatus
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.models import (
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataSubscriptionResult,
    OnlyRealtimeBarPreviewV1,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.persistence.clickhouse import OnlyClickHouseMarketFactStore, OnlyClickHouseMigrationAuthority
from onlyalpha.persistence.postgres import (
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationProductStore,
    OnlyPostgresMarketDataCatalog,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessCheck,
    OnlyResearchReadinessStatus,
)
from onlyalpha.research.query import OnlyResearchArtifactReader
from tests.market_data_durable.test_real_database_acceptance import _clickhouse
from tests.runtime_support.binance_spot_probe_fixture import _kline
from tests.runtime_support.local_read_browser import _inventory
from tests.support.browser_database import reset_dev_browser_test_namespace

NOW = datetime(2026, 1, 25, tzinfo=UTC)
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
ORIGIN = "http://127.0.0.1:4173"
TOKEN = "ee" * 32  # Synthetic acceptance credential only.


class _PublicWireResponse:
    status = 200

    def __init__(self, document: object) -> None:
        self._body = json.dumps(document, separators=(",", ":")).encode()
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(self._body))}

    def read(self, maximum: int) -> bytes:
        return self._body[:maximum]

    def __enter__(self) -> _PublicWireResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _wire(request: Request, *, timeout: float) -> _PublicWireResponse:
    from urllib.parse import parse_qs, urlsplit

    del timeout
    parsed = urlsplit(request.full_url)
    query = parse_qs(parsed.query)
    if parsed.path == "/api/v3/exchangeInfo":
        return _PublicWireResponse(
            {
                "timezone": "UTC",
                "exchangeFilters": [],
                "symbols": [
                    {
                        "symbol": symbol,
                        "status": "TRADING",
                        "baseAsset": symbol.removesuffix("USDT"),
                        "quoteAsset": "USDT",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                            {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
                        ],
                    }
                    for symbol in json.loads(query.get("symbols", ['["BTCUSDT"]'])[0])
                ],
            }
        )
    if parsed.path == "/api/v3/klines":
        assert query["symbol"] == ["BTCUSDT"]
        stride = {"1m": 60_000, "15m": 900_000}[query["interval"][0]]
        return _PublicWireResponse(
            [
                _kline(value, stride)
                for value in range(int(query["startTime"][0]), int(query["endTime"][0]) + 1, stride)
            ][: int(query["limit"][0])]
        )
    if parsed.path == "/api/v3/time":
        return _PublicWireResponse({"serverTime": int(NOW.timestamp() * 1000)})
    raise AssertionError("Unexpected external request: " + parsed.path)


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _recorded_wire(path: Path) -> tuple[Callable[..., _PublicWireResponse], str, str]:
    """Acceptance-only recorded venue input; missing/changed capture fails closed."""
    from urllib.parse import parse_qs, urlsplit

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == path.with_suffix(".sha256").read_text().strip()
    recording = json.loads(raw)
    assert recording["source_kind"] == "CAPTURED_REAL_BINANCE_PUBLIC_HISTORY"
    assert recording["before_ns"] == str(int(NOW.timestamp()) * 1_000_000_000)
    captured_bars: dict[str, list[object]] = {}
    captured_info = None
    for item in recording["requests"]:
        assert item["status"] == 200
        parsed = urlsplit(item["url"])
        assert parsed.scheme == "https" and parsed.hostname == "data-api.binance.vision"
        body = (path.parent / item["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item["body_sha256"]
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v3/exchangeInfo":
            assert captured_info is None and json.loads(query["symbols"][0]) == ["BTCUSDT"]
            captured_info = json.loads(body)
        else:
            assert parsed.path == "/api/v3/klines" and query["symbol"] == ["BTCUSDT"]
            captured_bars.setdefault(query["interval"][0], []).extend(json.loads(body))
    assert captured_info == recording["exchange_info"] and captured_bars == recording["bars"]

    def replay(request: Request, *, timeout: float) -> _PublicWireResponse:
        del timeout
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https" and parsed.hostname == "data-api.binance.vision"
        if parsed.path == "/api/v3/exchangeInfo":
            assert json.loads(query.get("symbols", ['["BTCUSDT"]'])[0]) == ["BTCUSDT"]
            return _PublicWireResponse(recording["exchange_info"])
        assert parsed.path == "/api/v3/klines" and query["symbol"] == ["BTCUSDT"]
        interval = query["interval"][0]
        left, right = int(query["startTime"][0]), int(query["endTime"][0])
        limit = int(query["limit"][0])
        rows = recording["bars"][interval]
        assert rows[0][0] <= left <= right <= rows[-1][6]
        selected = [row for row in rows if left <= row[0] <= right][:limit]
        assert selected
        return _PublicWireResponse(selected)

    return replay, digest, str(recording["bars"]["15m"][-1][4])


def _denied_authority(kind: type[object]) -> Any:
    # These unrelated Product authorities are deliberately inaccessible in this
    # protected acceptance composition. An accidental call must fail, not return
    # an object-shaped success. Real owning Integration/Market/SMA services below
    # remain concrete; no request/response or numeric result is intercepted.
    authority = create_autospec(kind, instance=True)
    for name, _ in inspect.getmembers(kind, inspect.isfunction):
        if not name.startswith("_"):
            getattr(authority, name).side_effect = AssertionError("FORBIDDEN_ACCEPTANCE_AUTHORITY_CALL")
    return authority


def main() -> None:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    clickhouse = _clickhouse("onlyalpha_test_chart_study_browser")
    if os.environ.get("ONLYALPHA_DEV_SOURCE_ROOT"):
        reset_dev_browser_test_namespace(dsn, clickhouse)
    OnlyPostgresMigrationAuthority(dsn).migrate()
    OnlyClickHouseMigrationAuthority(clickhouse).migrate()
    artifacts = Path("test-results/chart-study-browser")
    artifacts.mkdir(parents=True, exist_ok=True)
    recording_path = os.environ.get("ONLYALPHA_CHART_STUDY_RECORDED_WIRE")
    external_wire, capture_digest, preview_price = (
        _recorded_wire(Path(recording_path)) if recording_path else (_wire, None, "105.00")
    )
    with (
        TemporaryDirectory(prefix="onlyalpha-chart-study-browser-") as raw,
        patch("onlyalpha_plugin_binance.common.http.urlopen", side_effect=external_wire),
    ):
        root = Path(raw)
        calculations, data_sources, brokers = (
            OnlyCalculationRegistry(),
            OnlyDataSourceFactoryRegistry(),
            OnlyBrokerFactoryRegistry(),
        )
        composition = only_configure_product_registries(
            calculations, data_sources, brokers, OnlyBrokerFeeContractRegistry(), OnlyMarketProductFactoryRegistry()
        )
        assert composition.chart_study is not None
        types = OnlyIntegrationTypeCatalog(data_sources, brokers)
        store = OnlyPostgresIntegrationProductStore(dsn, b"k" * 32)
        commands = OnlyIntegrationCommandService(types, store, b"k" * 32)
        integration_id = OnlyIntegrationId("00000000-0000-4000-8000-000000000701")

        def command(number: int) -> OnlyProductCommandId:
            return OnlyProductCommandId(f"00000000-0000-4000-8000-{number:012d}")

        commands.create_integration(
            OnlyCreateIntegration(
                command(701), integration_id, "binance.spot.market_data", "Chart acceptance Binance Spot"
            )
        )
        draft = store.load_draft(integration_id)
        commands.publish_integration_revision(
            OnlyPublishIntegrationRevision(command(702), integration_id, draft.draft_version)
        )
        integration = store.load_integration(integration_id)
        if integration.lifecycle_state is not OnlyIntegrationLifecycleState.ACTIVE:
            commands.set_integration_lifecycle(
                OnlySetIntegrationLifecycle(
                    command(703), integration_id, integration.lifecycle_state, OnlyIntegrationLifecycleState.ACTIVE
                )
            )
            integration = store.load_integration(integration_id)
        revision = integration.current_revision_fingerprint
        assert revision is not None
        reference = OnlyMarketDataSourceReferenceV1(str(integration_id), revision, "binance.spot.market_data")
        integration_queries = OnlyIntegrationQueryService(store)
        credentials = OnlyPostgresCredentialAuthority(dsn, b"k" * 32)
        probe_catalog = OnlyIntegrationProbeCatalog(data_sources, brokers)
        probe_store = OnlyPostgresIntegrationProbeStore(dsn)
        integration_probes = OnlyIntegrationProbeService(store, probe_store, credentials, probe_catalog)
        operational_queries = OnlyIntegrationOperationalQueryService(store, probe_store, probe_catalog)
        resolver = OnlyIntegrationRuntimeResolver(store, credentials, types)
        catalog = OnlyPostgresMarketDataCatalog(dsn, now=lambda: NOW)
        facts = OnlyClickHouseMarketFactStore(clickhouse)
        clock = OnlyBacktestClock(NOW)
        product = OnlyMarketDataProductService(
            integrations=integration_queries,
            resolver=resolver,
            data_sources=data_sources,
            catalog=catalog,
            fact_store=facts,
            wal_root=root / "history",
            clock=clock,
            logger=logging.getLogger(__name__),
            now=lambda: NOW,
        )
        resolved = product.resolve_runtime(reference)
        end = clock.timestamp_ns()
        # Respect the existing acquisition bound. No acquisition occurs after inventory.
        for left in range(0, 2000, 500):
            acquired = product.acquire_bars(
                reference,
                instrument_id=str(INSTRUMENT),
                start_ns=end - (2000 - left) * 900_000_000_000,
                end_ns=end - (1500 - left) * 900_000_000_000,
                bar_semantic=OnlyBarSemantic.fixed_duration(15),
            )
            assert acquired.status == "COMPLETE", acquired
        acquired = product.acquire_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=end - 2000 * 60_000_000_000, end_ns=end
        )
        assert acquired.status == "COMPLETE", acquired
        stream = OnlyMarketDataStreamProductService(
            historical=product,
            catalog=catalog,
            fact_store=facts,
            wal_root=root / "live",
            clock=clock,
            logger=logging.getLogger(__name__),
        )

        def preview(
            source: OnlyBinanceSpotDataSource, request: OnlyMarketDataSubscriptionRequest
        ) -> OnlyMarketDataSubscriptionResult:
            assert len(request.bar_types) == 1
            bar_type = next(iter(request.bar_types))
            assert source._request.market_data_preview_sink is not None
            source._request.market_data_preview_sink(
                OnlyRealtimeBarPreviewV1(
                    source._request.source_id,
                    INSTRUMENT,
                    OnlyBarType(INSTRUMENT, bar_type.semantic),
                    end,
                    end + bar_type.semantic.window_minutes * 60_000_000_000,
                    preview_price,
                    preview_price,
                    preview_price,
                    preview_price,
                    "2.00000",
                    end,
                    end,
                )
            )
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "preview")

        config_path = root / "local-read.json"
        config_path.write_text(
            json.dumps(
                dict(
                    schema_version=1,
                    subject_id="chart-acceptance-operator",
                    bearer_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
                    origin=ORIGIN,
                    grants=[
                        dict(
                            integration_id=str(integration_id),
                            integration_revision_fingerprint=revision,
                            expected_type_id=reference.expected_type_id,
                            source_id=resolved.selection.source_id,
                            environment=resolved.selection.environment,
                            permissions=["CLOSED_HISTORY", "REALTIME_PREVIEW"],
                        )
                    ],
                )
            )
        )
        config_path.chmod(0o600)
        before = dict(database=_inventory(dsn, clickhouse), files=_files(root))

        def inspect_fixture() -> OnlyResearchReadiness:
            ingress = getattr(app.state, "local_read_ingress", None)
            if ingress is None or ingress._work or stream._sessions:
                return OnlyResearchReadiness(
                    OnlyResearchReadinessStatus.NOT_READY,
                    (OnlyResearchReadinessCheck("fixture_inventory", "WORK_PENDING"),),
                    "WORK_PENDING",
                )
            after = dict(database=_inventory(dsn, clickhouse), files=_files(root))
            (artifacts / "after.json").write_text(json.dumps(after, indent=2))
            (artifacts / "process-observations.json").write_text(
                json.dumps(
                    {
                        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        "scope": "LINUX_FIXTURE_STARTUP_AND_BROWSER_INTERVAL",
                        "is_query_only_measurement": False,
                        "is_slo_certification": False,
                    },
                    indent=2,
                )
            )
            assert after == before, "Chart Query changed durable business inventory"
            return OnlyResearchReadiness(
                OnlyResearchReadinessStatus.READY, (OnlyResearchReadinessCheck("fixture_inventory", "UNCHANGED"),), None
            )

        definition_resolver = _denied_authority(OnlyResearchDefinitionResolver)
        definition_resolver.universe_resolver = None
        readiness_probe = create_autospec(OnlyKernelResearchReadinessProjection, instance=True)
        readiness_probe.inspect.side_effect = inspect_fixture
        app = create_product_app(
            reader=_denied_authority(OnlyResearchArtifactReader),
            product_boundary=_denied_authority(OnlyResearchProductBoundary),
            calculation_registry=calculations,
            definition_resolver=definition_resolver,
            readiness_probe=readiness_probe,
            strategy_freeze=_denied_authority(OnlyStrategyFreezeProductService),
            strategy_promotion=_denied_authority(OnlyStrategyPromotionProductService),
            strategy_query=_denied_authority(OnlyStrategyQueryService),
            qualification=_denied_authority(OnlyQualificationProductService),
            qualification_query=_denied_authority(OnlyQualificationQueryService),
            backtest_commands=_denied_authority(OnlyBacktestCommandService),
            backtest_queries=_denied_authority(OnlyBacktestQueryService),
            integration_types=types,
            integration_commands=commands,
            integration_queries=integration_queries,
            integration_probes=integration_probes,
            integration_operational_queries=operational_queries,
            market_data=product,
            market_data_stream=stream,
            local_read_configuration=only_load_local_read_configuration(config_path),
            calculation_composition=composition,
        )
        (artifacts / "before.json").write_text(json.dumps(before, indent=2))
        (artifacts / "source.json").write_text(
            json.dumps(
                dict(
                    source_kind="CAPTURED_REAL_BINANCE_PUBLIC_HISTORY"
                    if recording_path
                    else "DETERMINISTIC_EXTERNAL_PROTOCOL_FIXTURE",
                    capture_sha256=capture_digest,
                    realtime_preview="SYNTHETIC_NON_PERSISTING_PREVIEW",
                    reference=dict(integration_id=str(integration_id), revision=revision),
                    instrument=str(INSTRUMENT),
                    before_ns=str(end),
                    capability=composition.chart_study.admission.fingerprint,
                ),
                indent=2,
            )
        )

        async def observe_quiescent_health(scope: Scope, receive: Receive, send: Send) -> None:
            # Read-only acceptance scheduling barrier, not a changed health/API
            # contract: logout can render before retained IO/stream teardown ends.
            # Observe actual owner Futures; never cancel them, poll or fake READY.
            if scope["type"] == "http" and scope["method"] == "GET" and scope["path"] in {"/health", "/health/ready"}:
                ingress = getattr(app.state, "local_read_ingress", None)
                pending = tuple(ingress._work) if ingress is not None else ()
                if pending:
                    await asyncio.wait(pending, timeout=10)
            await app(scope, receive, send)

        try:
            with (
                patch.object(OnlyBinanceSpotDataSource, "subscribe", preview),
                patch.object(OnlyBinanceSpotDataSource, "unsubscribe", lambda *args: None),
            ):
                uvicorn.run(
                    observe_quiescent_health,
                    host="127.0.0.1",
                    port=8000,
                    ws_max_size=4096,
                    ws_per_message_deflate=False,
                    proxy_headers=False,
                    access_log=False,
                )
        finally:
            stream.close()
            after = dict(database=_inventory(dsn, clickhouse), files=_files(root))
            (artifacts / "after.json").write_text(json.dumps(after, indent=2))
            assert after == before, "Chart Query changed durable business inventory"


if __name__ == "__main__":
    main()
