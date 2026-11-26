"""原 Research 受理 Source 选择：真实 PG/CH、正式受理 owner、原 Command 重放。

复用既有受理场景及断言，仅将本场景固定为实际 release 工件，避免原生
执行器的工件预算受 debug 符号影响；各请求和场景的既有超时保持不变。
"""
from pathlib import Path
from typing import Any

import pytest

from packages.backend.tests.application import test_market_storage_postgres_clickhouse as scenarios
from packages.backend.tests.application.support.native_research_market_fixture import (
    _build_market_probe,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    native_environment_case as native_environment_case,
)
from packages.backend.tests.application.test_market_storage_postgres_clickhouse import database as database

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]


@pytest.fixture(scope="session")
def market_probe() -> Path:
    return _build_market_probe(release=True)


@pytest.mark.parametrize("mode", ["normal", "source-denied", "binding-denied", "finite-complete", "finite-rebound", "finite-drain", "heartbeat-guard-loss", "finite-recovery-cancel", "finite-recovery-exhausted"])
def test_original_source_selection_survives_receipt_replay(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: scenarios.ClickHouseObservations,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
) -> None:
    scenarios.test_strategy_submission_reuses_original_command_and_run_with_physical_session_fencing(
        native_environment_case, market_probe, database, postgres_dsn, tmp_path, mode, build_programs=True, frozen_faults=mode != "finite-complete",
    )
