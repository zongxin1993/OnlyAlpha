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
    scenario_019_broker_rejected,
    scenario_020_execution_audit,
    scenario_021_out_of_order_trade,
    scenario_022_mid_pipeline_failure,
    scenario_023_partial_fill_then_cancel,
    scenario_024_market_data_assembly,
    scenario_025_historical_replay_entry,
    scenario_026_market_data_audit,
    scenario_027_queue_separation,
    scenario_028_source_registry,
    scenario_029_reference_data,
    scenario_030_no_lookahead,
    scenario_031_snapshot_quality,
    scenario_032_market_data_determinism,
    scenario_033_data_full_vertical_slice,
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
    scenario_019_broker_rejected.run,
    scenario_020_execution_audit.run,
    scenario_021_out_of_order_trade.run,
    scenario_022_mid_pipeline_failure.run,
    scenario_023_partial_fill_then_cancel.run,
    scenario_024_market_data_assembly.run,
    scenario_025_historical_replay_entry.run,
    scenario_026_market_data_audit.run,
    scenario_027_queue_separation.run,
    scenario_028_source_registry.run,
    scenario_029_reference_data.run,
    scenario_030_no_lookahead.run,
    scenario_031_snapshot_quality.run,
    scenario_032_market_data_determinism.run,
    scenario_033_data_full_vertical_slice.run,
)


def run_all() -> tuple[OnlyScenarioReport, ...]:
    env = OnlyIntegrationEnvironment()
    return tuple(scenario(env) for scenario in SCENARIOS)


def main() -> None:
    for report in run_all():
        print(f"[{report.scenario_id}] PASS {report.title}")


if __name__ == "__main__":
    main()
