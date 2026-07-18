from ..environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    updates = tuple(env.process_bar(DAY_ONE, minute, "10.00") for minute in range(3))
    assert not updates[0].derived_bars and not updates[1].derived_bars
    assert len(updates[2].derived_bars) == 1
    assert env.bar_3m in updates[2].snapshot.updated_bar_types
    return env.report_builder.scenario("002", "1m→3m Bar 聚合", "Runtime Pipeline 生成唯一共享 3m Bar")
