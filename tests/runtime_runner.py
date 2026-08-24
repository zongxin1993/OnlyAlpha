"""Test helper for exercising Runtime through a pre-committed P9 Strategy Revision."""

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import yaml

from onlyalpha.config import OnlyClusterRunConfig, OnlyStrategyReferenceConfig
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.market.product import OnlyMarketProductResolutionContext
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from onlyalpha.runtime.result import OnlyRuntimeResult
from onlyalpha.strategy import (
    OnlyStrategyMarketInputContract,
    OnlyStrategyRevisionStore,
    OnlyStrategyUniverse,
)
from tests.runtime_support.market_product import _NoResources
from tests.strategy.p9_support import p9_strategy_case


def only_run_cluster_runtime(
    config: OnlyClusterRunConfig,
    *,
    services: OnlyEngineServices | None = None,
) -> OnlyRuntimeResult:
    """Build and execute one Runtime without introducing another product entry."""

    selected_services = services or only_default_engine_services()
    temporary = TemporaryDirectory()
    user_data_root = Path(temporary.name)
    config = only_migrate_cluster_to_strategy(config, user_data_root)
    market_product = selected_services.assembler.components.market_products.resolve(
        config.market,
        OnlyMarketProductResolutionContext(_NoResources(), config.reference_data.instruments),
    )
    runtime_plan = (
        OnlyRuntimePlanner()
        .plan(
            OnlyEngineId("runtime-component-test"),
            (config,),
            {config.cluster_id: market_product},
        )
        .runtime_plans[0]
    )
    build = selected_services.assembler.build(runtime_plan, user_data_root)
    if build.runtime is None:
        raise RuntimeError(f"{build.failure_code}: {build.failure_message}")
    runtime = build.runtime
    try:
        runtime.initialize()
        runtime.start()
        result = runtime.run()
        if not hasattr(result, "to_dict"):
            raise TypeError("Runtime.run() returned an invalid result")
        return cast(OnlyRuntimeResult, result)
    finally:
        runtime.close()
        temporary.cleanup()


def only_migrate_cluster_to_strategy(
    config: OnlyClusterRunConfig,
    user_data_root: Path,
) -> OnlyClusterRunConfig:
    """Explicitly seed a P9 test Revision and replace one legacy fixture reference."""

    case = p9_strategy_case(user_data_root / "research")
    subscriptions = tuple(
        subscription for factor in config.factors for subscription in factor.subscriptions.instrument_bars
    )
    instrument_ids = (
        tuple(sorted({item.instrument_id for item in subscriptions}, key=str))
        if subscriptions
        else (config.reference_data.instruments[0].instrument_id,)
    )
    market_input_contract = (
        OnlyStrategyMarketInputContract(
            subscriptions[0].bar_specification.to_bar_type(subscriptions[0].instrument_id).specification,
            subscriptions[0].bar_specification.source,
            OnlyAdjustmentType.RAW,
        )
        if subscriptions
        else case.revision.market_input_contract
    )
    revision = replace(
        case.revision,
        universe=OnlyStrategyUniverse(instrument_ids),
        market_input_contract=market_input_contract,
    )
    OnlyStrategyRevisionStore(user_data_root / "research").commit(revision)
    strategy = OnlyStrategyReferenceConfig(str(revision.strategy_fingerprint))
    config = replace(
        config,
        cluster=replace(config.cluster, strategy=strategy, factors=()),
        strategy=strategy,
        factors=(),
    )
    return config


def only_write_migrated_cluster_config(source: str | Path, user_data_root: Path) -> Path:
    """Write an explicit fingerprint-only test config beside a seeded semantic Store."""

    source_path = Path(source).resolve()
    config = only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load(source_path), user_data_root)
    text = source_path.read_text(encoding="utf-8")
    payload = json.loads(text) if source_path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise TypeError("test Cluster config root must be a mapping")
    payload["strategy"] = {"fingerprint": config.strategy.fingerprint}
    payload["factors"] = []
    for data_source in payload.get("data_sources", []):
        extensions = data_source.get("extensions", {})
        market_config = extensions.get("market_config")
        if market_config is not None:
            extensions["market_config"] = str((source_path.parent / str(market_config)).resolve())
    target = user_data_root / f"p9-{source_path.stem}.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def only_copy_cluster_strategy_revision(
    config: OnlyClusterRunConfig,
    source_user_data_root: Path,
    target_user_data_root: Path,
) -> OnlyClusterRunConfig:
    """Copy one immutable test Revision into an isolated Engine root."""

    revision = OnlyStrategyRevisionStore(source_user_data_root / "research").load_verified(config.strategy.fingerprint)
    OnlyStrategyRevisionStore(target_user_data_root / "research").commit(revision)
    return config
