from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyTradeId, OnlyVenueTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyExecutionProcessingResult, OnlyExecutionProcessingStatus

from ..environment import ACCOUNT_ID, CNY, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    order = env.runtime.order_manager.snapshot_all()[0]
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    stale = OnlyBrokerTradeUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("scenario-out-of-order-trade"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.order_id),
        causation_id="out-of-order-fault-adapter",
        order_id=order.order_id,
        fill=OnlyOrderFill(
            trade_id=OnlyTradeId("scenario-stale-trade"),
            order_id=order.order_id,
            price=OnlyPrice(Decimal("10.00"), 2),
            quantity=OnlyQuantity(Decimal("1"), 0),
            ts_event=now,
            ts_init=now,
            venue_trade_id=OnlyVenueTradeId("scenario-stale-venue-trade"),
            venue_order_id=order.venue_order_id,
            fee=OnlyMoney(Decimal("0.00"), CNY),
            liquidity_side=OnlyLiquiditySide.TAKER,
        ),
    )
    before = order.version
    env.runtime.receive_broker_update(stale)
    result = env.runtime.drain_broker_inbound()[0]
    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
    assert result.reconciliation_request is not None
    assert env.runtime.order_manager.require_snapshot(order.order_id).version == before
    return env.report_builder.scenario(
        "021",
        "乱序 Trade",
        "旧 sequence Trade 在任何 Manager Mutation 前进入 Execution Reconciliation Queue",
    )
