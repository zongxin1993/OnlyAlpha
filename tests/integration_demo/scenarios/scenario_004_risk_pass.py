from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.buy_order is not None and env.buy_order.risk_decision is not None
    assert env.buy_order.risk_decision.is_accepted
    assert len(env.runtime.risk_service.reservations.snapshot_active()) == 1
    return env.report_builder.scenario("004", "Risk 通过", "Risk ACCEPT 后同步建立 Reservation")
