"""Barrier-controlled subprocess client for the canonical PostgreSQL handoff tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_run_admission_store import (
    OnlyPostgresChartCalculationRunAdmissionStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore


def main() -> None:
    root, operation_id, queued_at = sys.argv[1:]
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    runtime = OnlyRuntimeGenerationRegistry(Path(root))
    operation = OnlyPostgresChartCalculationAdmissionStore(dsn).load_verified(OnlyProductCommandId(operation_id))
    assert operation is not None
    compilation = OnlyPostgresChartCalculationCompilationStore(dsn).load_verified(operation)
    assert compilation is not None
    print("READY", flush=True)
    assert sys.stdin.readline().strip() == "COMMIT"
    run = OnlyPostgresChartCalculationRunAdmissionStore(dsn, runtime_generations=runtime).commit_or_replay(
        operation, compilation, queued_at=datetime.fromisoformat(queued_at)
    )
    print(run.run_id.value + ":" + run.admission_resolution_fingerprint, flush=True)


if __name__ == "__main__":
    main()
