"""验证原正式 READY 回测由实际调度器发布；不替代 Web 验收。"""

from pathlib import Path
from typing import Any

import pytest

from packages.backend.tests.application import test_strategy_research_evidence as scenarios
from packages.backend.tests.application.test_strategy_research_evidence import (
    backtest_fault_environment as backtest_fault_environment,
)
from packages.backend.tests.application.test_strategy_research_evidence import (
    database as database,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]


def test_actual_backtest_scheduler_publishes_original_run_without_file_results(
    database: Any,
    postgres_dsn: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenarios.test_actual_strategy_science_producer_report_historical_reader_and_freeze(
        database,
        postgres_dsn,
        tmp_path,
        "backtest-owner:finite-publication",
        request,
        monkeypatch,
    )
