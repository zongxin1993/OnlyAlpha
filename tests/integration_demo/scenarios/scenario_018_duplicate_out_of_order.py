from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate
from onlyalpha.domain.time import OnlyTimestamp
from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.runtime.broker_gateway is not None
    order = env.runtime.order_manager.snapshot_all()[0]
    broker_order = env.runtime.broker_gateway.query_orders(order.account_id)[0]
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    stale = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=env.runtime.broker_gateway.config.gateway_id,
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("scenario-stale-accepted"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.order_id),
        causation_id="fault-adapter",
        order_id=order.order_id,
        venue_order_id=broker_order.venue_order_id,
        quality_flags=("OUT_OF_ORDER",),
    )
    before = env.runtime.order_manager.require_snapshot(order.order_id)
    env.runtime.receive_broker_update(stale)
    env.runtime.receive_broker_update(stale)
    env.runtime.drain_broker_inbound()
    after = env.runtime.order_manager.require_snapshot(order.order_id)

    assert after.status == before.status
    assert after.filled_quantity == before.filled_quantity
    return env.report_builder.scenario(
        "018", "重复与乱序 Broker Update", "update_id 去重且迟到 Accepted 不令终态 Order 回退"
    )
