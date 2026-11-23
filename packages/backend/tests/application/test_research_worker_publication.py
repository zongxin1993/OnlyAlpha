"""真实调度器从原受理 Run 完成有限 Research 与 PG 发布；不代替正式 Web 验收。"""
from pathlib import Path
from typing import Any

import pytest

from packages.backend.tests.application import test_market_storage_postgres_clickhouse as scenarios
from packages.backend.tests.application.test_market_storage_postgres_clickhouse import database as database
from packages.backend.tests.application.test_strategy_research_evidence import (
    backtest_fault_environment as backtest_fault_environment,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]


@pytest.mark.parametrize("mode",["finite-service","finite-service-cancel-preparing","finite-service-cancel-child","finite-service-cancel-finished","finite-service-cancel-after-complete","finite-service-recompute"])
def test_actual_scheduler_publishes_original_research_run_without_file_evidence(
    backtest_fault_environment: dict[str, Any],
    database: scenarios.ClickHouseObservations,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
) -> None:
    scenarios.test_strategy_submission_reuses_original_command_and_run_with_physical_session_fencing(
        backtest_fault_environment,backtest_fault_environment["executable"],database,postgres_dsn,tmp_path,
        mode,build_programs=True,frozen_faults=False,
    )


@pytest.mark.parametrize("mode",[
    "finite-complete","finite-rebound","finite-drain","heartbeat-guard-loss",
    "finite-recovery-cancel","finite-recovery-exhausted",
])
def test_finite_control_and_recovery_with_the_actual_scheduler_image(
    backtest_fault_environment:dict[str,Any],database:scenarios.ClickHouseObservations,
    postgres_dsn:str,tmp_path:Path,mode:str,
)->None:
    # The same real image supplies admission, public finite ownership and the
    # internal scheduler. Recheck lifecycle controls after the join refactor.
    scenarios.test_strategy_submission_reuses_original_command_and_run_with_physical_session_fencing(
        backtest_fault_environment,backtest_fault_environment["executable"],database,postgres_dsn,tmp_path,
        mode,build_programs=True,frozen_faults=mode!="finite-complete",
    )
