from datetime import date
from decimal import Decimal

from onlyalpha_plugin_broker_virtual import OnlyFixedLatencyModel, OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillScheduleMode, OnlyVirtualFillScheduleStepSpec

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerTradeUpdate
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.value import OnlyMoney
from tests.support.virtual_broker import ACCOUNT, CNY, START, bar, order


def test_broker_execute_before_publish_checkpoint_restores_publish_only() -> None:
    clock = OnlyBacktestClock(START)
    updates = []
    config = OnlyVirtualBrokerConfig(
        OnlyBrokerGatewayId("publish-checkpoint"),
        ACCOUNT,
        CNY,
        OnlyMoney(Decimal("100000.00"), CNY),
        fill_schedule_mode=OnlyVirtualFillScheduleMode.SCHEDULE,
        fill_schedule_steps=(OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("100")),),
        latency_model=OnlyFixedLatencyModel(0, 0, 60_000_000_000, 0),
    )
    gateway = OnlyVirtualBrokerGateway(config, OnlyRuntimeId("runtime"), clock, updates.append)
    gateway.connect()
    gateway.authenticate()
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(order(1))
    gateway.run_due()
    second = bar(date(2026, 1, 5), 1)
    clock.advance_to(second.ts_event)
    gateway.on_bar(second)
    assert len(gateway.query_trades(ACCOUNT)) == 1
    assert not any(isinstance(item, OnlyBrokerTradeUpdate) for item in updates)
    checkpoint = gateway.capture_checkpoint()
    restored_updates = []
    restored = OnlyVirtualBrokerGateway(config, OnlyRuntimeId("runtime"), clock, restored_updates.append)
    restored.restore_checkpoint(checkpoint)
    clock.advance_to(clock.timestamp_ns() + 61_000_000_000)
    restored.run_due()
    assert len(restored.query_trades(ACCOUNT)) == 1
    assert len(tuple(item for item in restored_updates if isinstance(item, OnlyBrokerTradeUpdate))) == 1
