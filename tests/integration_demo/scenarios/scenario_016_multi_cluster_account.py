from decimal import Decimal

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderRequestId
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity

from ..environment import (
    ACCOUNT_ID,
    CLUSTER_ID,
    CNY,
    DAY_ONE,
    INSTRUMENT_ID,
    OnlyIntegrationCluster,
    OnlyIntegrationEnvironment,
    OnlyScenarioReport,
)


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    second_id = OnlyClusterId("integration-cluster-2")
    shared = OnlyIntegrationEnvironment(
        cluster_capitals={
            CLUSTER_ID: OnlyMoney(Decimal("400000.00"), CNY),
            second_id: OnlyMoney(Decimal("600000.00"), CNY),
        }
    )
    second = OnlyIntegrationCluster((shared.bar_1m, shared.bar_3m), second_id)
    shared.runtime.add_cluster(shared.runtime.config.engine_id, second)
    shared.start()
    for minute in range(3):
        shared.process_bar(DAY_ONE, minute, "10.00")

    def request(name: str) -> OnlyOrderRequest:
        return OnlyOrderRequest(
            OnlyOrderRequestId(name),
            INSTRUMENT_ID,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("100"), 0),
            price=OnlyPrice(Decimal("10.00"), 2),
            offset=OnlyOffset.OPEN,
        )

    shared.cluster.pending_order = request("cluster-one-buy")
    second.pending_order = request("cluster-two-buy")
    shared.process_bar(DAY_ONE, 3, "10.00")

    account = shared.runtime.account_manager.require_snapshot(OnlyAccountId(ACCOUNT_ID))
    assert account.cash.frozen_cash.amount == Decimal("2000.02")
    assert {item.key.cluster_id for item in shared.runtime.strategy_ledger_manager.list_ledgers()} == {
        CLUSTER_ID,
        second_id,
    }
    shared.process_bar(DAY_ONE, 4, "10.00")
    assert shared.runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("200")
    assert sum(item.total_quantity.value for item in shared.runtime.allocation_manager.snapshot_all()) == Decimal("200")
    return env.report_builder.scenario(
        "016", "多 Cluster 共享 Account", "Account 合并账户真值，Allocation 与 Ledger 仍按 Cluster 隔离"
    )
