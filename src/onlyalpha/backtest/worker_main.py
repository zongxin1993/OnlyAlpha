"""Dedicated Backtest Worker process composition and lifecycle."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event

from onlyalpha.application.runtime_generation import (
    OnlyNoClaimRuntimeGenerationWorkAuthority,
    OnlyRuntimeGenerationWorkAuthority,
)
from onlyalpha.application.stop_controller import (
    OnlyApplicationShutdownReason,
    OnlyApplicationStopController,
)
from onlyalpha.application.strategy_product import OnlyStrategyQueryService
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
from onlyalpha.runtime.work_binding import only_load_runtime_generation_work_authority
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .admission import OnlyBacktestAdmissionService
from .deployment import only_load_backtest_deployment_catalog, only_load_backtest_market_product_resources
from .economic_facts import OnlyBacktestEconomicFactStore
from .evidence import OnlyBacktestEvidenceStore
from .execution import OnlyBacktestWorkerInstanceId
from .market_adapter import OnlyMarketProductBacktestAdmissionAdapter
from .presence import OnlyBacktestWorkerPresenceReporter
from .profiles import only_default_backtest_profile_registry
from .worker import (
    OnlyBacktestProductEnginePlanBuilder,
    OnlyBacktestRuntimeExecutor,
    OnlyBacktestWorker,
    OnlyEngineBacktestRuntimeExecutor,
)


class _AcceptanceBarrierExecutor:
    """Operational crash-test barrier; absent unless the Compose lane opts in."""

    def __init__(self, delegate: OnlyBacktestRuntimeExecutor, release_path: Path) -> None:
        self._delegate = delegate
        self._release_path = release_path
        self._wait = Event()

    def execute(self, run):  # type: ignore[no-untyped-def]
        while not self._release_path.is_file():
            self._wait.wait(0.1)
        return self._delegate.execute(run)


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
    parser.add_argument("--runtime-generation-authority-root", type=Path)
    parser.add_argument("--runtime-generation-fingerprint")
    args = parser.parse_args(argv)
    if args.poll_interval <= 0:
        parser.error("--poll-interval must be positive")
    postgres = OnlyPostgresConfig.from_environment()
    options = OnlyPostgresOperationalConnectionOptions()
    layout = OnlyUserDataLayout(args.user_data_root)
    if (args.runtime_generation_authority_root is None) != (args.runtime_generation_fingerprint is None):
        parser.error("RuntimeGeneration authority root and fingerprint must be supplied together")
    process_generation_fingerprint = args.runtime_generation_fingerprint or "0" * 64
    runtime_generations: OnlyRuntimeGenerationWorkAuthority
    if args.runtime_generation_authority_root is None:
        runtime_generations = OnlyNoClaimRuntimeGenerationWorkAuthority()
    else:
        runtime_generations = only_load_runtime_generation_work_authority(args.runtime_generation_authority_root)
        runtime_generations.verify_hosted_generation(process_generation_fingerprint)
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
        promotions=OnlyStrategyQueryService(strategies, promotions),
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
    executor: OnlyBacktestRuntimeExecutor = OnlyEngineBacktestRuntimeExecutor(plan_builder)
    barrier_path = os.environ.get("ONLYALPHA_BACKTEST_ACCEPTANCE_BARRIER_PATH")
    if barrier_path:
        executor = _AcceptanceBarrierExecutor(executor, Path(barrier_path))
    worker = OnlyBacktestWorker(
        worker_instance_id=worker_id,
        store=store,
        admission=admission,
        executor=executor,
        evidence=OnlyBacktestEvidenceStore(layout.root),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=process_generation_fingerprint,
    )
    stop = OnlyApplicationStopController()
    presence = OnlyBacktestWorkerPresenceReporter(store, worker_id, _service_version(), timedelta(seconds=15))
    stop.install()
    first_failure: BaseException | None = None
    try:
        presence.start()
        while not stop.stop_requested:
            outcome = worker.run_once()
            if outcome is None:
                stop.wait(args.poll_interval)
    except KeyboardInterrupt:
        stop.request_stop(OnlyApplicationShutdownReason.KEYBOARD_INTERRUPT)
    except BaseException as exc:
        first_failure = exc
    try:
        _shutdown_presence(presence)
    except BaseException as exc:
        if first_failure is None:
            first_failure = exc
    try:
        stop.restore()
    except BaseException as exc:
        if first_failure is None:
            first_failure = exc
    if first_failure is not None:
        raise first_failure
    return stop.exit_code


def _shutdown_presence(presence: OnlyBacktestWorkerPresenceReporter) -> None:
    first_failure: BaseException | None = None
    for action in (presence.draining, presence.stop):
        try:
            action()
        except BaseException as exc:
            if first_failure is None:
                first_failure = exc
    if first_failure is not None:
        raise first_failure


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
