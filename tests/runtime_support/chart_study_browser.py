"""Protected Shipping acceptance over real Product, plugins and isolated PG/CH.

By default external Binance wire payloads and preview delivery are deterministic
contract fakes. An explicit recorded-wire input instead replays hash-bound public
Binance history; neither mode certifies live transport or deployment. All setup
writes precede the browser interval; queries use actual owning readers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import os
import resource
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import create_autospec, patch

import uvicorn
from onlyalpha_http_server.app import create_product_app
from onlyalpha_http_server.composition import only_configure_product_registries
from onlyalpha_http_server.health import OnlyKernelResearchReadinessProjection
from onlyalpha_http_server.local_read_access import only_load_local_read_configuration
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
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
from onlyalpha.application.watchlists import OnlyWatchlistService
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
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.clickhouse import OnlyClickHouseMarketFactStore, OnlyClickHouseMigrationAuthority
from onlyalpha.persistence.postgres import (
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationProductStore,
    OnlyPostgresMarketDataCatalog,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.research_deployment_store import OnlyPostgresResearchDeploymentStore
from onlyalpha.persistence.postgres.watchlist_store import OnlyPostgresWatchlistStore
from onlyalpha.plugin.data_source import OnlyDataSourceFactory
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreIdentity
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessCheck,
    OnlyResearchReadinessStatus,
)
from onlyalpha.research.query import OnlyResearchArtifactReader
from scripts.database import _initialize_deployment
from tests.market_data_durable.test_real_database_acceptance import _clickhouse
from tests.runtime_support.binance_market_wire import (
    NOW,
    _recorded_wire,
    _watchlist_wire,
    _WatchlistWireFactory,
    _wire,
)
from tests.runtime_support.local_read_browser import _inventory
from tests.support.browser_database import reset_dev_browser_test_namespace

INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
ORIGIN = "http://127.0.0.1:4173"
TOKEN = "ee" * 32  # Synthetic acceptance credential only.


def _assert_slice_inventory(before: dict[str, Any], after: dict[str, Any]) -> None:
    """Only market ingestion and Watchlist Commands belong to this UI journey."""
    allowed = ("postgres:market_", "postgres:watchlist_", "clickhouse:market_")
    commands = {"postgres:product_command_admission", "postgres:product_command_receipt"}
    assert set(before["database"]) == set(after["database"])
    for name, value in before["database"].items():
        if not name.startswith(allowed) and name not in commands:
            assert after["database"][name] == value, name
    protected_before = {
        name: value for name, value in before["files"].items() if not name.startswith(("history/", "live/"))
    }
    protected_after = {
        name: value for name, value in after["files"].items() if not name.startswith(("history/", "live/"))
    }
    assert protected_after == protected_before


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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


def main(*, watchlist_slice: bool = False) -> None:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    clickhouse = _clickhouse("onlyalpha_test_chart_study_browser")
    if os.environ.get("ONLYALPHA_DEV_SOURCE_ROOT"):
        reset_dev_browser_test_namespace(dsn, clickhouse)
    OnlyPostgresMigrationAuthority(dsn).migrate()
    OnlyClickHouseMigrationAuthority(clickhouse).migrate()
    artifacts = Path("test-results/symbol-search-browser" if watchlist_slice else "test-results/chart-study-browser")
    artifacts.mkdir(parents=True, exist_ok=True)
    recording_path = os.environ.get("ONLYALPHA_CHART_STUDY_RECORDED_WIRE")
    if watchlist_slice and recording_path:
        raise ValueError("SYMBOL_SLICE_REQUIRES_DECLARED_SYNTHETIC_WIRE")
    external_wire, capture_digest, preview_price = (
        _recorded_wire(Path(recording_path))
        if recording_path
        else (_watchlist_wire if watchlist_slice else _wire, None, "105.00")
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
        controlled = OnlyDataSourceFactoryRegistry()
        for record in data_sources.records():
            factory = (
                _WatchlistWireFactory(quotes_enabled=watchlist_slice, recording_path=recording_path)
                if isinstance(record.factory, OnlyBinanceSpotDataSourceFactory)
                else record.factory
            )
            controlled.register(cast(OnlyDataSourceFactory, factory), origin=record.origin)
        data_sources = controlled
        if watchlist_slice:
            _initialize_deployment(dsn, root)
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
        if watchlist_slice:
            second = OnlyIntegrationId("00000000-0000-4000-8000-000000000704")
            commands.create_integration(
                OnlyCreateIntegration(command(704), second, "binance.spot.market_data", "Other Binance Spot")
            )
            second_draft = store.load_draft(second)
            commands.publish_integration_revision(
                OnlyPublishIntegrationRevision(command(705), second, second_draft.draft_version)
            )
            second_integration = store.load_integration(second)
            if second_integration.lifecycle_state is not OnlyIntegrationLifecycleState.ACTIVE:
                commands.set_integration_lifecycle(
                    OnlySetIntegrationLifecycle(
                        command(706),
                        second,
                        store.load_integration(second).lifecycle_state,
                        OnlyIntegrationLifecycleState.ACTIVE,
                    )
                )

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
        if not watchlist_slice:
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
        before: dict[str, Any] = dict(database=_inventory(dsn, clickhouse), files=_files(root))

        def inspect_fixture() -> OnlyResearchReadiness:
            ingress = getattr(app.state, "local_read_ingress", None)
            if (ingress is None and not watchlist_slice) or (ingress is not None and ingress._work) or stream._sessions:
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
            if watchlist_slice:
                _assert_slice_inventory(before, after)
            else:
                assert after == before, "Chart Query changed durable business inventory"
            return OnlyResearchReadiness(
                OnlyResearchReadinessStatus.READY, (OnlyResearchReadinessCheck("fixture_inventory", "UNCHANGED"),), None
            )

        definition_resolver = _denied_authority(OnlyResearchDefinitionResolver)
        definition_resolver.universe_resolver = None
        readiness_probe = create_autospec(OnlyKernelResearchReadinessProjection, instance=True)
        readiness_probe.inspect.side_effect = inspect_fixture
        dev_configuration = None
        dev_credential = None
        watchlists = None
        if watchlist_slice:
            from onlyalpha_http_server.dev_web import only_dev_web_configuration

            dev_configuration, dev_credential = only_dev_web_configuration(
                "http://127.0.0.1:5173", product.list_sources()
            )
            identity = OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(root).research_root).load_verified()
            assert OnlyPostgresResearchDeploymentStore(dsn).load_semantic_store_id() == identity
            watchlists = OnlyWatchlistService(OnlyPostgresWatchlistStore(dsn, identity), product)
            assert watchlists.read().version == 0
            assert before["database"]["postgres:market_data_revision"]["count"] == 0
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
            local_read_configuration=None if watchlist_slice else only_load_local_read_configuration(config_path),
            dev_web_configuration=dev_configuration,
            watchlists=watchlists,
            calculation_composition=composition,
        )
        if watchlist_slice:
            from onlyalpha_http_server.dev_web import only_mount_dev_web

            assert dev_credential is not None
            only_mount_dev_web(app, Path("packages/onlyalpha-web-console/dist"), dev_credential)
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
                    port=5173 if watchlist_slice else 8000,
                    ws_max_size=4096,
                    ws_per_message_deflate=False,
                    proxy_headers=False,
                    access_log=False,
                )
        finally:
            stream.close()
            after = dict(database=_inventory(dsn, clickhouse), files=_files(root))
            (artifacts / "after.json").write_text(json.dumps(after, indent=2))
            if watchlist_slice:
                _assert_slice_inventory(before, after)
            else:
                assert after == before, "Chart Query changed durable business inventory"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist-slice", action="store_true")
    arguments = parser.parse_args()
    main(watchlist_slice=arguments.watchlist_slice)
