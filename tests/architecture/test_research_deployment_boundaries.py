from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_semantic_store_identity_is_namespace_metadata_not_semantic_registry() -> None:
    source = _source("src/onlyalpha/research/operations/deployment.py")
    assert 'SEMANTIC_STORE_IDENTITY_FILE = ".onlyalpha-semantic-store.json"' in source
    for forbidden in (
        "research.artifact",
        "research.result",
        "research.calculation",
        "research.dataset",
        "def list_objects",
        "def find_result",
        "def latest",
        "def update",
        "def invalidate",
    ):
        assert forbidden not in source.lower()


def test_postgres_binding_is_single_purpose_and_has_no_update_or_semantic_content() -> None:
    migration = _source("database/postgres/migrations/0007_research_deployment_semantic_store_binding.sql")
    adapter = _source("src/onlyalpha/persistence/postgres/research_deployment_store.py")
    assert "singleton BOOLEAN PRIMARY KEY" in migration
    assert "semantic_store_id UUID NOT NULL" in migration
    assert "ON CONFLICT (singleton) DO NOTHING" in adapter
    for forbidden in (
        "UPDATE research_deployment_semantic_store_binding",
        "dataset_snapshot_fingerprint",
        "calculation_fingerprint",
        "statistics_fingerprint",
        "research_result_fingerprint",
        "artifact_content_fingerprint",
    ):
        assert forbidden not in migration + adapter


def test_api_and_worker_verify_but_never_initialize_or_rebind_deployment() -> None:
    api = "".join(_source("packages/onlyalpha-http-server/rust/startup.rs").split())
    worker = _source("src/onlyalpha/research/worker_main.py")
    for startup in (worker,):
        assert "OnlyResearchDeploymentCoherenceVerifier(" in startup
        assert "OnlyPostgresResearchDeploymentStore(" in startup
        assert ".initialize(" not in startup
        assert ".migrate(" not in startup
    assert "deployment::verify_binding(client,&self.namespace)" in api
    assert ".initialize(" not in api
    assert ".migrate(" not in api
    assert worker.index("deployment_check=deployment.verify") < worker.index("service.run_forever")


def test_deployment_identity_cannot_enter_research_semantic_fingerprints() -> None:
    semantic_roots = (
        Path("src/onlyalpha/research/calculation"),
        Path("src/onlyalpha/research/specification"),
        Path("src/onlyalpha/research/evaluation"),
        Path("src/onlyalpha/research/result"),
        Path("src/onlyalpha/research/artifact"),
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for root in semantic_roots for path in sorted(root.rglob("*.py"))
    )
    assert "SemanticStoreId" not in source
    assert "semantic_store_id" not in source
    assert "research.operations.deployment" not in source


def test_crash_barriers_are_test_owned_and_production_has_no_crash_mode() -> None:
    helper = _source("tests/certification/research_product/crash_worker.py")
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path("src/onlyalpha/research").rglob("*.py"))
    )
    assert 'choices=("C1", "C2", "C3", "C4")' in helper
    assert "Event().wait()" in helper
    assert "RESEARCH_CRASH_TEST_MODE" not in production
    assert "crash_worker" not in production


def test_native_workstation_browser_harness_uses_the_selected_binary_without_python_http() -> None:
    harness = _source("scripts/native_web_e2e.py")
    browser = _source("packages/onlyalpha-web-console/e2e/factors.spec.ts")
    assert 'resources / "bin/onlyalpha-http-server"' in harness
    assert "onlyalpha_http_server.main" not in harness
    assert "tests.runtime_support.generation_api_main" not in harness
    for source in (harness, browser):
        assert "page.route(" not in source
        assert "route.fulfill(" not in source
    assert 'await page.goto("/")' in browser
    assert 'getByRole("button", { name: "因子", exact: true })' in browser
    assert "expect(commands).toEqual([])" in browser
    assert "NATIVE_WORKSTATION_READY version=" in harness
    assert "child.wait(timeout=20)" in harness
    assert '"remaining_process_group": remaining_processes' in harness
    assert "if remaining_processes:" in harness
