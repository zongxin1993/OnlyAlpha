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
    assert ledger.pnl.realized_pnl.amount == Decimal("200.00")
    assert ledger.pnl.net_pnl.amount == Decimal("199.38")
    return env.report_builder.scenario("011", "已实现收益", "毛收益 200.00，费用后净收益 199.38")
