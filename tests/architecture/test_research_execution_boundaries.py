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


def test_worker_startup_composition_is_shared_by_resolution_and_runtime_execution() -> None:
    startup = Path("src/onlyalpha/research/worker_main.py").read_text()
    assert "services = only_default_engine_services(fail_fast=True)" in startup
    assert "calculations = services.assembler.components.calculations" in startup
    assert "OnlyResearchSpecificationResolver(calculations)" in startup
    assert "OnlyEngineResearchRuntimeExecutor(layout.root, services)" in startup
    assert startup.index("services = only_default_engine_services") < startup.index("service.run_forever")


def test_worker_claim_execution_cannot_rediscover_process_composition() -> None:
    worker = Path("src/onlyalpha/research/execution/worker.py").read_text()
    executor = worker[worker.index("class OnlyEngineResearchRuntimeExecutor") : worker.index("class _LeaseControl")]
    assert "services=self._services" in executor
    assert "only_default_engine_services" not in executor
    assert "only_discover_plugins" not in executor


def test_scheduler_worker_have_no_http_web_or_semantic_checkpoint_dependency() -> None:
    source = _source(Path("src/onlyalpha/research/execution"))
    for forbidden in ("fastapi", "pydantic", "onlyalpha_api", "onlyalpha-web", "semantic_checkpoint"):
        assert forbidden not in source.lower()


def test_scheduler_and_postgres_remain_semantics_blind_while_reconciliation_uses_reader_ports() -> None:
    scheduler = Path("src/onlyalpha/research/execution/scheduler.py").read_text()
    postgres = Path("src/onlyalpha/persistence/postgres/research_execution_store.py").read_text()
    for source in (scheduler, postgres):
        assert "research.result.result_store" not in source
        assert "research.artifact.store" not in source
        assert "runtime.research.runtime" not in source
        assert ".load_verified(" not in source
    reconciliation = Path("src/onlyalpha/research/execution/reconciliation.py").read_text()
    assert "class OnlyResearchSemanticCompletionProbe(Protocol)" in reconciliation
    assert "class _ResearchResultReader(Protocol)" in reconciliation
    assert "class _ResearchArtifactReader(Protocol)" in reconciliation
    assert "OnlyEngine(" not in reconciliation
    assert ".commit(" not in reconciliation


def test_attempt_migration_contains_no_research_semantic_content_columns() -> None:
    migration = "\n".join(
        Path(f"database/postgres/migrations/{name}").read_text().lower()
        for name in ("0003_research_run_attempt_authority.sql", "0006_research_worker_presence.sql")
    )
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


def test_operational_diagnostics_are_read_only_and_do_not_expand_run_state() -> None:
    diagnostics = _source(Path("src/onlyalpha/research/operations"))
    run_model = Path("src/onlyalpha/research/run/model.py").read_text()
    for forbidden in ("commit_transition(", "claim_next(", "expire_next(", "reconcile_cancellation("):
        assert forbidden not in diagnostics
    for forbidden_state in ("STUCK", "LOST", "RECOVERING", "ZOMBIE"):
        assert f'{forbidden_state} = "{forbidden_state}"' not in run_model


def test_worker_presence_is_not_attempt_ownership_authority() -> None:
    execution = Path("src/onlyalpha/persistence/postgres/research_execution_store.py").read_text()
    assert "research_worker_presence" not in execution
    migration = Path("database/postgres/migrations/0006_research_worker_presence.sql").read_text().lower()
    for forbidden in ("specification", "dataset", "candidate", "result", "artifact", "strategy"):
        assert forbidden not in migration


def test_api_and_worker_startup_check_compatibility_without_migrating() -> None:
    api = Path("packages/api/onlyalpha-api/src/onlyalpha_api/main.py").read_text()
    worker = Path("src/onlyalpha/research/worker_main.py").read_text()
    startup = "\n".join((api, worker))
    assert startup.count("OnlyPostgresSchemaVerifier(") == 2
    assert "schema_status=schema.status" in api
    assert 'OnlyKernelLifecycleStep("research_product_scope", verification.verify)' in api
    assert "schema.assert_compatible()" in worker
    assert ".migrate(" not in startup
