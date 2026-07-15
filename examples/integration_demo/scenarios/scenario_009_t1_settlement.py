from decimal import Decimal

from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    results = env.settle_next_day()
    assert len(results) == 2
    assert env.runtime.position_manager.snapshot_all()[0].available_quantity.value == Decimal("100")
    return env.report_builder.scenario("009", "第二天 T+1 结算", "账户与 Allocation Bucket 同步结算")
