"""Test helper for exercising Runtime directly through the formal planner/factory path."""

from typing import cast

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.market.product import OnlyMarketProductResolutionContext
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from onlyalpha.runtime.result import OnlyRuntimeResult
from tests.runtime_support.market_product import _NoResources


def only_run_cluster_runtime(
    config: OnlyClusterRunConfig,
    *,
    services: OnlyEngineServices | None = None,
) -> OnlyRuntimeResult:
    """Build and execute one Runtime without introducing another product entry."""

    selected_services = services or only_default_engine_services()
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
    build = selected_services.assembler.build(runtime_plan)
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
