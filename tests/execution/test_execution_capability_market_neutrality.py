from dataclasses import replace

import pytest

from onlyalpha.broker import (
    OnlyBrokerGatewayId,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerTradeUpdate,
    OnlyBrokerUpdateId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import OnlyExecutionCapability
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.planning_context import OnlyTradeExecutionPlanningContext
from onlyalpha.fee import only_cn_a_share_production_fee_pack
from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.position.enums import OnlyPositionSide
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from tests.integration_demo.environment import OnlyIntegrationEnvironment


def _planning_context(
    profile: OnlyMarketProfileId,
) -> tuple[OnlyIntegrationEnvironment, OnlyBrokerTradeUpdate, OnlyTradeExecutionPlanningContext]:
    scenario = OnlyTestGenericT0Scenario(f"semantic-{profile.value.lower()}")
    environment = OnlyIntegrationEnvironment(
        market_profile_id=profile,
        market_fee_pack=(
            only_cn_a_share_production_fee_pack() if profile is OnlyMarketProfileId.CN_A_SHARE_CASH else None
        ),
    )
    _prepare_environment(environment, scenario)
    update = _trade_update(environment, scenario)
    context = only_test_real_trade_planning_context(environment, update)
    return environment, update, context


def test_different_markets_with_same_semantic_shape_have_same_support_decision() -> None:
    _, _, generic = _planning_context(OnlyMarketProfileId.GENERIC_T0_CASH)
    _, _, ashare = _planning_context(OnlyMarketProfileId.CN_A_SHARE_CASH)

    assert (
        generic.trade_instruction.compiled_identity.profile_id != ashare.trade_instruction.compiled_identity.profile_id
    )
    assert generic.support_decision == ashare.support_decision
    assert generic.support_decision.capability is OnlyExecutionCapability.DURABLE_TRADE


def test_same_market_with_different_semantic_shape_has_different_decision() -> None:
    environment, update, supported = _planning_context(OnlyMarketProfileId.CN_A_SHARE_CASH)
    allocation_key = supported.position_scope.allocation_key
    short_scope = replace(
        supported.position_scope,
        position_side=OnlyPositionSide.SHORT,
        position_key=replace(supported.position_scope.position_key, position_side=OnlyPositionSide.SHORT),
        allocation_key=(
            None if allocation_key is None else replace(allocation_key, position_side=OnlyPositionSide.SHORT)
        ),
    )
    unsupported = environment.runtime.execution_processor._resolve_execution_support(update, short_scope)

    assert supported.support_decision.capability is OnlyExecutionCapability.DURABLE_TRADE
    assert unsupported.capability is OnlyExecutionCapability.UNSUPPORTED
    assert supported.support_decision != unsupported


def test_buy_open_terminal_is_durable_and_enters_terminal_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = OnlyTestGenericT0Scenario("buy-open-terminal")
    environment = OnlyIntegrationEnvironment()
    _prepare_environment(environment, scenario)
    assert environment.buy_order is not None and environment.buy_order.order_id is not None
    order = environment.runtime.order_manager.require_snapshot(environment.buy_order.order_id)
    environment.runtime.clock.advance_by(1_000_000_000)
    timestamp = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    update = OnlyBrokerOrderCancelledUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("buy-open-terminal-cancel"),
        source_sequence=(order.last_external_sequence or 0) + 1,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id=str(order.order_id),
        causation_id="buy-open-terminal-test",
        order_id=order.order_id,
    )
    scope = environment.runtime.execution_processor._resolve_position_scope(update)
    assert scope is not None
    decision = environment.runtime.execution_processor._resolve_execution_support(update, scope)
    assert decision.capability is OnlyExecutionCapability.DURABLE_TERMINAL

    original_prepare = environment.runtime.execution_processor._terminal_planner.prepare
    called = False

    def observe_prepare(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(environment.runtime.execution_processor._terminal_planner, "prepare", observe_prepare)
    before = environment.runtime.execution_transaction_query.records(order.runtime_id)
    result = environment.runtime.execution_processor.process(update)
    after = environment.runtime.execution_transaction_query.records(order.runtime_id)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED
    assert called
    assert len(after) == len(before) + 1
