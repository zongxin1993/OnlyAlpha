from decimal import Decimal

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    account = env.runtime.account_manager.list_accounts()[0]
    assert account.cash.cash_balance.amount == Decimal("1000199.38")
    assert env.cluster.context is not None
    assert env.cluster.context.accounts.current() == account
    return env.report_builder.scenario(
        "013", "Account 初始化与只读 Context", "AccountManager 由 Runtime 独占，Cluster 仅获得 immutable View"
    )
