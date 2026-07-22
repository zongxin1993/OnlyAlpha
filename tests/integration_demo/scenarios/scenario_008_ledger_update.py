from decimal import Decimal

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    ledger = env.runtime.strategy_ledger_manager.list_ledgers()[0]
    assert ledger.cash.cash_balance.amount == Decimal("998999.99")
    assert ledger.cash.cash_reserved.amount == Decimal("0.00")
    return env.report_builder.scenario("008", "Strategy Ledger 更新", "买入本金与费用只记入来源 Cluster")
