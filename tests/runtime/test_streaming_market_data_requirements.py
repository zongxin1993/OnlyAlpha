import pytest

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.runtime.streaming.requirements import (
    OnlyRuntimeMarketDataRequirement,
    only_compose_runtime_market_data_requirements,
)


def test_strategy_bar_and_execution_trade_requirements_compose_without_identity_conflation(runtime_types) -> None:
    bar_1m = runtime_types[0]
    strategy = OnlyRuntimeMarketDataRequirement(
        "STRATEGY_REVISION",
        frozenset({OnlyMarketDataType.BAR}),
        frozenset({bar_1m}),
    )
    execution = OnlyRuntimeMarketDataRequirement(
        "EXECUTION_RISK_REFERENCE",
        frozenset({OnlyMarketDataType.TRADE}),
    )

    plan = only_compose_runtime_market_data_requirements(execution, strategy)

    assert plan.data_types == frozenset({OnlyMarketDataType.BAR, OnlyMarketDataType.TRADE})
    assert plan.bar_types == frozenset({bar_1m})
    assert tuple(item.authority for item in plan.requirements) == (
        "EXECUTION_RISK_REFERENCE",
        "STRATEGY_REVISION",
    )
    assert strategy.data_types == frozenset({OnlyMarketDataType.BAR})


def test_requirement_contract_rejects_trade_disguised_as_strategy_bar(runtime_types) -> None:
    bar_1m = runtime_types[0]
    with pytest.raises(ValueError, match="BAR_REQUIREMENT_INVALID"):
        OnlyRuntimeMarketDataRequirement(
            "STRATEGY_REVISION",
            frozenset({OnlyMarketDataType.TRADE}),
            frozenset({bar_1m}),
        )
