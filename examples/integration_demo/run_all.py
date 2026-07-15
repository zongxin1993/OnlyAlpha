"""Run all integration scenarios in one shared environment."""

from collections.abc import Callable

from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport
from examples.integration_demo.scenarios import (
    scenario_001_runtime_start,
    scenario_002_bar_aggregation,
    scenario_003_order_submit,
    scenario_004_risk_pass,
    scenario_005_buy_fill,
    scenario_006_position_update,
    scenario_007_allocation_update,
    scenario_008_ledger_update,
    scenario_009_t1_settlement,
    scenario_010_sell,
    scenario_011_realized_pnl,
    scenario_012_final_snapshot,
    scenario_013_account_initialization,
    scenario_014_partial_fill,
    scenario_015_cancel,
    scenario_016_multi_cluster_account,
    scenario_017_broker_local_conflict,
    scenario_018_duplicate_out_of_order,
)

SCENARIOS: tuple[Callable[[OnlyIntegrationEnvironment], OnlyScenarioReport], ...] = (
    scenario_001_runtime_start.run,
    scenario_002_bar_aggregation.run,
    scenario_003_order_submit.run,
    scenario_004_risk_pass.run,
    scenario_005_buy_fill.run,
    scenario_006_position_update.run,
    scenario_007_allocation_update.run,
    scenario_008_ledger_update.run,
    scenario_009_t1_settlement.run,
    scenario_010_sell.run,
    scenario_011_realized_pnl.run,
    scenario_012_final_snapshot.run,
    scenario_013_account_initialization.run,
    scenario_014_partial_fill.run,
    scenario_015_cancel.run,
    scenario_016_multi_cluster_account.run,
    scenario_017_broker_local_conflict.run,
    scenario_018_duplicate_out_of_order.run,
)


def run_all() -> tuple[OnlyScenarioReport, ...]:
    env = OnlyIntegrationEnvironment()
    return tuple(scenario(env) for scenario in SCENARIOS)


def main() -> None:
    for report in run_all():
        print(f"[{report.scenario_id}] PASS {report.title}")


if __name__ == "__main__":
    main()
