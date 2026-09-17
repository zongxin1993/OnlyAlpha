from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_CONTRACT = Path("src/onlyalpha/quant_assets/private.py")
_PERSISTENCE = Path("src/onlyalpha/persistence/postgres/private_asset_store.py")
_PROVENANCE = Path("src/onlyalpha/research/provenance.py")
_GENERATION = Path(
    "packages/onlyalpha-authoring-execution-worker/src/onlyalpha_authoring_execution_worker/generation.py"
)
_MIGRATION = Path("database/postgres/migrations/0027_private_asset_authoring_authority.sql")
_PRODUCT = Path("src/onlyalpha/application/product_boundary.py")
_HTTP = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/research/run_schema.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_private_asset_contract_owns_no_postgres_web_agent_or_evidence_dependency() -> None:
    imports = _imports(_CONTRACT)
    assert not any(
        name.startswith(
            (
                "psycopg",
                "onlyalpha.persistence",
                "onlyalpha.web",
                "onlyalpha.research.agent",
                "onlyalpha.research.result",
                "onlyalpha.strategy.qualification",
            )
        )
        for name in imports
    )
    assert "onlyalpha.quant_assets.private" in _imports(_PERSISTENCE)


def test_pa1_private_asset_boundary_contains_no_source_execution_path() -> None:
    for path in (_CONTRACT, _PERSISTENCE, _PROVENANCE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert calls.isdisjoint({"eval", "exec", "compile", "__import__"}), path


def test_revision_store_has_no_semantic_update_or_delete_api() -> None:
    source = _PERSISTENCE.read_text(encoding="utf-8")
    assert "UPDATE private_l3_revision" not in source
    assert "UPDATE private_l4_revision" not in source
    assert "DELETE FROM private_l3_revision" not in source
    assert "DELETE FROM private_l4_revision" not in source


def test_revision_tables_reject_update_delete_and_truncate() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE ON private_l3_revision" in source
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE ON private_l4_revision" in source
    assert "Private Asset Revisions are immutable" in source


def test_authoring_provenance_is_db_native_and_rejects_git_shape() -> None:
    source = _PROVENANCE.read_text(encoding="utf-8")
    assert all(
        field not in source for field in ("source_repository", "source_revision", "source_tree", "source_locator")
    )
    assert "private_asset_revision_fingerprint" in source
    assert "private_asset_content_fingerprint" in source


def test_private_authoring_has_no_git_checkout_or_package_resource_authority() -> None:
    for path in (_CONTRACT, _PERSISTENCE, _PROVENANCE, _GENERATION):
        source = path.read_text(encoding="utf-8")
        assert "importlib.resources" not in source
        assert "git checkout" not in source
        assert "source_repository" not in source


def test_reference_product_and_http_intent_exclude_authority_derived_provenance() -> None:
    from onlyalpha_http_server.research.run_schema import SubmitResearchRunRequest

    from onlyalpha.application.product_boundary import OnlyCreateResearchRun
    from onlyalpha.quant_assets import OnlyPrivateAssetRevisionReferenceV1

    assert {item.name for item in fields(OnlyPrivateAssetRevisionReferenceV1)} == {
        "private_asset_kind",
        "private_asset_id",
        "private_asset_revision_fingerprint",
    }
    assert "authoring_provenance" not in {item.name for item in fields(OnlyCreateResearchRun)}
    assert "authoring_provenance" not in SubmitResearchRunRequest.model_fields
    assert "authoring_generation_fingerprint" in SubmitResearchRunRequest.model_fields


def test_generation_factory_and_reader_reanchor_without_latest_or_source_execution() -> None:
    generation = _GENERATION.read_text(encoding="utf-8")
    contract = _CONTRACT.read_text(encoding="utf-8")
    assert "create_verified" in generation
    assert "OnlyPrivateAssetRevisionBindingResolver" in generation
    assert "OnlyVerifiedAuthoringGenerationReader" in generation
    assert "load_l3_revision" in contract and "load_l4_revision" in contract
    assert "load_latest" not in generation + contract
    assert "load_current" not in generation + contract
    for path in (_GENERATION, _PRODUCT, _HTTP):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert calls.isdisjoint({"eval", "exec", "compile"}), path
