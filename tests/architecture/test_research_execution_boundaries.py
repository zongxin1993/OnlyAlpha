from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def _source(root: Path) -> str:
    return "\n".join(path.read_text() for path in sorted(root.rglob("*.py")))


def test_research_runtime_is_operational_plane_neutral() -> None:
    runtime = _source(Path("src/onlyalpha/runtime/research"))
    assert "onlyalpha.research.execution" not in runtime
    assert "onlyalpha.persistence.postgres" not in runtime
    assert "ResearchRunAttempt" not in runtime
    assert "worker_instance_id" not in runtime


def test_attempt_domain_policy_and_port_do_not_depend_on_postgres_or_engine() -> None:
    root = Path("src/onlyalpha/research/execution")
    for name in ("model.py", "policy.py", "store.py", "errors.py", "scheduler.py"):
        source = (root / name).read_text()
        assert "psycopg" not in source
        assert "onlyalpha.persistence" not in source
        assert "onlyalpha.engine" not in source


def test_worker_enters_semantic_execution_only_through_engine_runtime_contract() -> None:
    worker = Path("src/onlyalpha/research/execution/worker.py").read_text()
    assert "from onlyalpha.engine import OnlyEngine" in worker
    assert "engine.add_research_workload" in worker
    assert "engine.run_runtime" in worker
    for forbidden in (
        "OnlyResearchJobExecutor(",
        "OnlyResearchStatisticsExecutor(",
        "OnlyResearchResultAssembler(",
        "OnlyResearchArtifactMaterializer(",
    ):
        assert forbidden not in worker


def test_scheduler_worker_have_no_http_web_or_semantic_checkpoint_dependency() -> None:
    source = _source(Path("src/onlyalpha/research/execution"))
    for forbidden in ("fastapi", "pydantic", "onlyalpha_api", "onlyalpha-web", "semantic_checkpoint"):
        assert forbidden not in source.lower()


def test_attempt_migration_contains_no_research_semantic_content_columns() -> None:
    migration = Path("database/postgres/migrations/0003_research_run_attempt_authority.sql").read_text().lower()
    for forbidden in (
        "dataset_row",
        "calculation_value",
        "factor_value",
        "statistics_row",
        "research_result_content",
        "artifact_content",
        "partial_result",
        "progress_percent",
    ):
        assert forbidden not in migration
