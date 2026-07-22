from decimal import Decimal

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    ledger = env.runtime.strategy_ledger_manager.list_ledgers()[0]
    assert ledger.pnl.realized_pnl.amount == Decimal("200.00")
    assert ledger.pnl.net_pnl.amount == Decimal("199.38")
    return env.report_builder.scenario("011", "已实现收益", "毛收益 200.00，费用后净收益 199.38")
