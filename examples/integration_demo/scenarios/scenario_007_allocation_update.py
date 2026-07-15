from decimal import Decimal

from examples.integration_demo.environment import CLUSTER_ID, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    snapshot = env.runtime.allocation_manager.list_by_cluster(CLUSTER_ID)[0]
    assert snapshot.total_quantity.value == Decimal("100")
    assert snapshot.key.cluster_id == CLUSTER_ID
    return env.report_builder.scenario("007", "Position Allocation 更新", "成交只归因到来源 Cluster")
