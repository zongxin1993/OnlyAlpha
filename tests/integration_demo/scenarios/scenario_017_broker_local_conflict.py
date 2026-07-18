from dataclasses import replace
from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerAccountUpdate
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney

from ..environment import ACCOUNT_ID, CNY, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.runtime.broker_gateway is not None
    local_before = env.runtime.account_manager.list_accounts()[0]
    broker = env.runtime.broker_gateway.query_account(OnlyAccountId(ACCOUNT_ID))
    conflict = replace(
        broker,
        cash_balance=OnlyMoney(broker.cash_balance.amount - Decimal("1.00"), CNY),
        available_cash=OnlyMoney(broker.available_cash.amount - Decimal("1.00"), CNY),
        equity=OnlyMoney(broker.equity.amount - Decimal("1.00"), CNY),
    )
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    env.runtime.receive_broker_update(
        OnlyBrokerAccountUpdate(
            runtime_id=env.runtime.config.runtime_id,
            gateway_id=conflict.gateway_id,
            account_id=conflict.account_id,
            update_id=OnlyBrokerUpdateId("scenario-account-conflict"),
            source_sequence=999,
            ts_event=now,
            ts_init=now,
            correlation_id=ACCOUNT_ID,
            causation_id="fault-adapter",
            snapshot=conflict,
            quality_flags=("INJECTED_CONFLICT",),
        )
    )
    env.runtime.drain_broker_inbound()
    local_after = env.runtime.account_manager.list_accounts()[0]

    assert local_after.cash.cash_balance == local_before.cash.cash_balance
    assert local_after.status.value == "RECONCILING"
    return env.report_builder.scenario(
        "017", "Broker/Local 冲突", "冲突被显式阻断且 Broker Snapshot 未静默覆盖本地真值"
    )
