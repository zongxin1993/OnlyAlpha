from decimal import Decimal

from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    snapshot = env.runtime.position_manager.snapshot_all()[0]
    assert snapshot.total_quantity.value == Decimal("100")
    assert snapshot.unsettled_quantity.value == Decimal("100")
    return env.report_builder.scenario("006", "Position 更新", "账户仓位写入 UNSETTLED Bucket")
