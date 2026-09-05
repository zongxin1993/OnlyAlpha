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
    api = _source("packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py")
    worker = _source("src/onlyalpha/research/worker_main.py")
    for startup in (api, worker):
        assert "OnlyResearchDeploymentCoherenceVerifier(" in startup
        assert "OnlyPostgresResearchDeploymentStore(" in startup
        assert ".initialize(" not in startup
        assert ".migrate(" not in startup
    assert "OnlyResearchFrozenDeploymentCheck(" in api
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


def test_real_browser_certification_has_no_route_mock_and_uses_process_barrier() -> None:
    browser = _source("packages/onlyalpha-web-console/e2e-real/research-product.spec.ts")
    harness = _source("tests/certification/p8_6/test_real_browser_product.py")
    worker_harness = _source("tests/runtime_generation_worker_main.py")
    assert "page.route(" not in browser
    assert "route.fulfill(" not in browser
    assert "browser-closed.barrier" in harness
    assert "tests.runtime_generation_worker_main" in harness
    assert "onlyalpha.research.worker_main import main" in worker_harness
    for semantic_word in ("recompute", "parquet", "psycopg"):
        assert semantic_word not in browser.lower()


def test_crash_barriers_are_test_owned_and_production_has_no_crash_mode() -> None:
    helper = _source("tests/certification/p8_6/crash_worker.py")
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path("src/onlyalpha/research").rglob("*.py"))
    )
    assert 'choices=("C1", "C2", "C3", "C4")' in helper
    assert "Event().wait()" in helper
    assert "P8_TEST" not in production
    assert "crash_worker" not in production
