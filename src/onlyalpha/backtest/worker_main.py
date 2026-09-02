"""Dedicated Backtest Worker process composition and lifecycle."""

from __future__ import annotations

import argparse
import signal
from collections.abc import Sequence
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import OnlyPostgresConfig, OnlyPostgresOperationalConnectionOptions
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.dataset import (
    OnlyDatasetEconomicBindingStore,
    OnlyParquetResearchDatasetSnapshotStore,
)
from onlyalpha.research.operations.deployment import (
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.strategy.promotion import OnlyStrategyPromotionService
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .admission import OnlyBacktestAdmissionService
from .deployment import only_load_backtest_deployment_catalog, only_load_backtest_market_product_resources
from .economic_facts import OnlyBacktestEconomicFactStore
from .evidence import OnlyBacktestEvidenceStore
from .execution import OnlyBacktestWorkerInstanceId
from .market_adapter import OnlyMarketProductBacktestAdmissionAdapter
from .presence import OnlyBacktestWorkerPresenceReporter
from .profiles import only_default_backtest_profile_registry
from .worker import OnlyBacktestProductEnginePlanBuilder, OnlyBacktestWorker, OnlyEngineBacktestRuntimeExecutor


def _service_version() -> str:
    try:
        return version("onlyalpha")
    except PackageNotFoundError:
        return "0+unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-backtest-worker")
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--backtest-product-config", action="append", type=Path, required=True)
    parser.add_argument("--backtest-market-resource", action="append", type=Path, default=[])
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.poll_interval <= 0:
        parser.error("--poll-interval must be positive")
    postgres = OnlyPostgresConfig.from_environment()
    options = OnlyPostgresOperationalConnectionOptions()
    layout = OnlyUserDataLayout(args.user_data_root)
    catalog = only_load_backtest_deployment_catalog(tuple(args.backtest_product_config))
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    broker_fees = OnlyBrokerFeeContractRegistry()
    market_products = OnlyMarketProductFactoryRegistry()
    calculations = OnlyCalculationRegistry()
    only_discover_plugins(
        data_sources,
        brokers,
        broker_fees,
        market_products,
        calculations,
        fail_fast=True,
    )
    semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
    strategies = OnlyFrozenStrategyRevisionStore(layout.research_root)
    promotions = OnlyPostgresStrategyProductStore(postgres.dsn, semantic_namespace_id, options)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    bindings = OnlyDatasetEconomicBindingStore(layout.root)
    profiles = only_default_backtest_profile_registry()
    resources = only_load_backtest_market_product_resources(tuple(args.backtest_market_resource))
    admission = OnlyBacktestAdmissionService(
        strategies=strategies,
        promotions=OnlyStrategyPromotionService(strategies, promotions, _unreachable_audit_time),
        dataset_bindings=bindings,
        datasets=datasets,
        market_products=OnlyMarketProductBacktestAdmissionAdapter(
            factories=market_products,
            configurations=catalog.configurations,
            resources=resources,
            instruments=catalog,
        ),
        profiles=profiles,
        kernel_semantics_version="ONLYALPHA_KERNEL_SEMANTICS@1",
    )
    plan_builder = OnlyBacktestProductEnginePlanBuilder(
        user_data_root=layout.root,
        catalog=catalog,
        strategies=strategies,
        datasets=datasets,
        profiles=profiles,
        market_product_resources=resources,
        economic_facts=OnlyBacktestEconomicFactStore(layout.root),
    )
    worker_id = OnlyBacktestWorkerInstanceId.new()
    store = OnlyPostgresBacktestStore(postgres.dsn, options)
    worker = OnlyBacktestWorker(
        worker_instance_id=worker_id,
        store=store,
        admission=admission,
        executor=OnlyEngineBacktestRuntimeExecutor(plan_builder),
        evidence=OnlyBacktestEvidenceStore(layout.root),
    )
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    presence = OnlyBacktestWorkerPresenceReporter(store, worker_id, _service_version(), timedelta(seconds=15))
    presence.start()
    try:
        while not stop.is_set():
            outcome = worker.run_once()
            if outcome is None:
                stop.wait(args.poll_interval)
    finally:
        presence.draining()
        presence.stop()
    return 0


def _unreachable_audit_time() -> datetime:
    raise RuntimeError("Backtest admission must not produce Strategy Promotion facts")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
