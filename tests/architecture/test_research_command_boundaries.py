from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres import OnlyPostgresResearchRunStore
from onlyalpha.research.command.store import OnlyResearchCommandStore
from onlyalpha.research.run import OnlyResearchRunAdmissionService

pytestmark = pytest.mark.architecture


def _imports(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
    return result


def test_command_core_is_transport_and_execution_neutral() -> None:
    imports = _imports(Path("src/onlyalpha/research/command"))
    forbidden = (
        "fastapi",
        "pydantic",
        "uvicorn",
        "psycopg",
        "onlyalpha.persistence",
        "onlyalpha.engine",
        "onlyalpha.runtime",
        "onlyalpha.research.execution",
        "onlyalpha.research.artifact",
        "onlyalpha.research.query",
    )
    assert not {name for name in imports if name.startswith(forbidden)}


def test_run_http_adapter_cannot_start_execution_or_modify_attempt_authority() -> None:
    root = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for forbidden in (
        "OnlyResearchWorkerService",
        "OnlyResearchScheduler",
        "OnlyPostgresResearchExecutionStore",
        "claim_next(",
        "heartbeat(",
        "renew(",
        "expire_next(",
        "OnlyEngine(",
    ):
        assert forbidden not in source


def test_standalone_artifact_composition_is_absent() -> None:
    assert not Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/artifact_main.py").exists()


def test_command_api_does_not_return_artifact_or_result_content() -> None:
    source = "\n".join(
        Path(f"packages/onlyalpha-http-server/src/onlyalpha_http_server/research/{name}").read_text()
        for name in ("run_schema.py", "run_routes.py")
    )
    for forbidden in ("statistics_rows", "series", "parquet", "artifact_manifest", "result_content"):
        assert forbidden not in source.lower()


def test_production_research_command_composition_requires_read_to_act_authorities() -> None:
    source = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py").read_text(encoding="utf-8")
    composition = source[source.index("command = OnlyResearchCommandService(") : source.index("research_queries =")]
    for required in (
        "novelty_decisions=",
        "memory_builder=",
        "memory_revisions=",
        "command_admissions=",
        "runtime_generation_resolver=",
    ):
        assert required in composition
    assert "allow_legacy_ungated=True" not in composition


def test_product_and_search_research_creation_share_the_command_service_gate() -> None:
    product = Path("src/onlyalpha/application/product_boundary.py").read_text(encoding="utf-8")
    symbolic = Path("src/onlyalpha/research/search/symbolic/product.py").read_text(encoding="utf-8")
    parameter = Path("src/onlyalpha/research/search/parameter/integration.py").read_text(encoding="utf-8")
    assert "commands.submit_research_run(" in product
    assert "self.commands.submit_research_run(" in symbolic
    assert "self.commands.submit_research_run(" in parameter
    for source in (product, symbolic, parameter):
        assert "create_queued_with_receipt(" not in source
        assert "create_queued_with_novelty_admission(" not in source
    http = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/research/run_routes.py").read_text(
        encoding="utf-8"
    )
    authoring = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("packages/onlyalpha-authoring-execution-worker/src").rglob("*.py")
    )
    assert "OnlyCreateResearchRun(" in http
    assert "create_queued(" not in authoring
    assert "create_queued_with_receipt(" not in authoring
    assert ".submit(" not in authoring


def test_multi_subject_composition_keeps_scientific_identity_and_member_locks_at_owners() -> None:
    subject = Path("src/onlyalpha/research/evaluation/subject.py").read_text(encoding="utf-8")
    decision = Path("src/onlyalpha/research/novelty/decision.py").read_text(encoding="utf-8")
    store = Path("src/onlyalpha/persistence/postgres/research_run_store.py").read_text(encoding="utf-8")

    assert "class OnlyExactEvaluationIntentSubjectV1" in subject
    assert "class OnlyResearchEvaluationSubjectSetV1" in subject
    assert "subject_set_fingerprint" in decision
    assert "OnlyExactEvaluationIntentSubjectV1.from_dict" in decision
    assert "for guard in guards:" in store
    assert "pg_advisory_xact_lock" in store
    assert "hash(subject_set" not in store


def test_verified_novelty_admission_write_is_not_a_public_store_capability() -> None:
    public_name = "create_queued_with_novelty_admission"
    assert not hasattr(OnlyPostgresResearchRunStore, public_name)
    assert public_name not in vars(OnlyResearchCommandStore)
    assert "_create_queued_with_verified_novelty_admission" not in vars(OnlyResearchCommandStore)

    production_uses = {
        path.relative_to(Path("src"))
        for path in Path("src").rglob("*.py")
        if "_create_queued_with_verified_novelty_admission(" in path.read_text(encoding="utf-8")
    }
    assert production_uses == {
        Path("onlyalpha/persistence/postgres/research_run_store.py"),
        Path("onlyalpha/research/command/service.py"),
        Path("onlyalpha/research/command/store.py"),
    }


def test_ordinary_research_preparation_cannot_create_an_authoritative_run() -> None:
    assert not hasattr(OnlyResearchRunAdmissionService, "submit")
    assert "run_store" not in inspect.signature(OnlyResearchRunAdmissionService).parameters
    assert not hasattr(OnlyPostgresResearchRunStore, "create_queued")
    assert not hasattr(OnlyPostgresResearchRunStore, "create_queued_with_receipt")
    assert "create_queued" not in vars(OnlyResearchCommandStore)
    assert "create_queued_with_receipt" not in vars(OnlyResearchCommandStore)


def test_verified_research_creation_and_sql_have_one_production_owner() -> None:
    roots = (Path("src"), Path("packages"))
    verified_uses = {
        path
        for root in roots
        for path in root.rglob("*.py")
        if "_create_queued_with_verified_novelty_admission(" in path.read_text(encoding="utf-8")
    }
    assert verified_uses == {
        Path("src/onlyalpha/persistence/postgres/research_run_store.py"),
        Path("src/onlyalpha/research/command/service.py"),
        Path("src/onlyalpha/research/command/store.py"),
    }
    sql_owners = {
        path
        for root in roots
        for path in root.rglob("*.py")
        if "INSERT INTO research_run " in path.read_text(encoding="utf-8")
    }
    assert sql_owners == {Path("src/onlyalpha/persistence/postgres/research_run_store.py")}


def test_historical_run_seeder_is_not_in_production_composition() -> None:
    import onlyalpha.persistence.postgres as postgres

    assert not hasattr(postgres, "OnlyPostgresResearchRunSeeder")
    production_importers = {
        path
        for root in (Path("src"), Path("packages"))
        for path in root.rglob("*.py")
        if "research_run_seeder" in path.read_text(encoding="utf-8")
    }
    assert production_importers == set()
