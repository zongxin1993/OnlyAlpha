from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyAccountId

from ..environment import ACCOUNT_ID, CLUSTER_ID, CNY, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    ledger = env.runtime.strategy_ledger_locator.require_snapshot(
        runtime_id=env.runtime.config.runtime_id,
        account_id=OnlyAccountId(ACCOUNT_ID),
        cluster_id=CLUSTER_ID,
        currency=CNY,
    )
    assert ledger.cash.cash_balance.amount == Decimal("998999.99")
    assert ledger.cash.cash_reserved.amount == Decimal("0.00")
    return env.report_builder.scenario("008", "Strategy Ledger 更新", "买入本金与费用只记入来源 Cluster")
