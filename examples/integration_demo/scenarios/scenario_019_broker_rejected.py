from decimal import Decimal

from examples.integration_demo.environment import (
    ACCOUNT_ID,
    DAY_ONE,
    OnlyIntegrationEnvironment,
    OnlyScenarioReport,
)
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerOrderRejectedUpdate
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRejection, OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyExecutionProcessingResult, OnlyExecutionProcessingStatus


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    rejected = OnlyIntegrationEnvironment(virtual_broker=False)
    rejected.start()
    for minute in range(3):
        rejected.process_bar(DAY_ONE, minute, "10.00")
    rejected.cluster.pending_order = OnlyOrderRequest(
        OnlyOrderRequestId("processor-rejected"),
        rejected.instrument.instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("100"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
        offset=OnlyOffset.OPEN,
    )
    rejected.process_bar(DAY_ONE, 3, "10.00")
    submitted = rejected.cluster.submit_results[-1]
    assert submitted.order_id is not None
    now = OnlyTimestamp.from_unix_nanos(rejected.runtime.clock.timestamp_ns())
    rejected.runtime.receive_broker_update(
        OnlyBrokerOrderRejectedUpdate(
            runtime_id=rejected.runtime.config.runtime_id,
            gateway_id=OnlyBrokerGatewayId("placeholder"),
            account_id=OnlyAccountId(ACCOUNT_ID),
            update_id=OnlyBrokerUpdateId("scenario-broker-rejected"),
            source_sequence=1,
            ts_event=now,
            ts_init=now,
            correlation_id=str(submitted.order_id),
            causation_id="explicit-rejection-adapter",
            order_id=submitted.order_id,
            rejection=OnlyOrderRejection("BROKER_REJECT", "deterministic rejection scenario"),
        )
    )
    result = rejected.runtime.drain_broker_inbound()[0]
    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status is OnlyExecutionProcessingStatus.APPLIED
    assert rejected.runtime.order_manager.require_snapshot(submitted.order_id).status is OnlyOrderStatus.REJECTED
    assert not rejected.runtime.risk_service.reservations.snapshot_active()
    assert rejected.runtime.account_manager.list_accounts()[0].cash.frozen_cash.amount == Decimal("0.00")
    return env.report_builder.scenario(
        "019",
        "ExecutionProcessor Broker Rejected",
        "Rejected 经 Runtime Queue 释放所有未消费 Reservation，未修改成交状态域",
    )
