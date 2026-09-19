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
_MIGRATION = Path("database/postgres/migrations/0029_private_factor_strategy_vocabulary.sql")
_PRODUCT = Path("src/onlyalpha/application/product_boundary.py")
_HTTP = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/research/run_schema.py")
_HTTP_MAIN = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py")
_PRODUCT_PROJECTION = Path("src/onlyalpha/application/private_asset_product.py")
_PRODUCT_HTTP = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/private_assets.py")
_PRODUCT_STORE = Path("src/onlyalpha/persistence/postgres/private_asset_product_store.py")


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
    assert "UPDATE private_factor_revision" not in source
    assert "UPDATE private_strategy_revision" not in source
    assert "DELETE FROM private_factor_revision" not in source
    assert "DELETE FROM private_strategy_revision" not in source


def test_revision_tables_reject_update_delete_and_truncate() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    strategy_migration = Path("database/postgres/migrations/0028_private_alpha_strategy_vocabulary.sql").read_text(
        encoding="utf-8"
    )
    history = Path("database/postgres/migrations/0027_private_asset_authoring_authority.sql").read_text(
        encoding="utf-8"
    )
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in history
    assert "Private Asset Revisions are immutable" in history
    assert "RENAME TO private_factor_revision_immutable_trigger" in source
    assert "RENAME TO private_strategy_revision_immutable_trigger" in strategy_migration


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
    assert "load_factor_revision" in contract and "load_strategy_revision" in contract
    assert "load_latest" not in generation + contract
    assert "load_current" not in generation + contract
    for path in (_GENERATION, _PRODUCT, _HTTP):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert calls.isdisjoint({"eval", "exec", "compile"}), path


def test_memory_composition_does_not_use_raw_generation_descriptor_store_as_authority() -> None:
    tree = ast.parse(_HTTP_MAIN.read_text(encoding="utf-8"))
    composition = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_compose_experiment_memory_projection_builder"
    )
    calls = {
        node.func.id for node in ast.walk(composition) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "OnlyAuthoringExecutionGenerationStore" not in calls


def test_private_strategy_revision_is_not_a_runtime_strategy_identity() -> None:
    runtime_paths = (
        Path("src/onlyalpha/backtest"),
        Path("src/onlyalpha/runtime"),
        Path("src/onlyalpha/strategy/adapter.py"),
        Path("src/onlyalpha/strategy/execution.py"),
        Path("src/onlyalpha/strategy/store.py"),
    )
    sources = []
    for path in runtime_paths:
        paths = (path,) if path.is_file() else tuple(path.rglob("*.py"))
        sources.extend(item.read_text(encoding="utf-8") for item in paths)
    assert all("OnlyPrivateStrategyRevision" not in source for source in sources)


def test_private_asset_registry_and_search_are_projection_only() -> None:
    from onlyalpha.application.private_asset_product import OnlyProductAssetRegistryEntryV1

    assert {item.name for item in fields(OnlyProductAssetRegistryEntryV1)} == {
        "locator",
        "semantic_version",
        "description",
        "category",
        "tags",
    }
    source = _PRODUCT_PROJECTION.read_text(encoding="utf-8")
    assert "onlyalpha.factor.registry" not in source
    assert "onlyalpha.quant_assets.catalog" not in source
    assert "qualification" not in source.casefold()
    assert "novelty" not in source.casefold()


def test_product_search_store_and_authority_content_have_no_production_bypass() -> None:
    production_roots = (Path("src"), Path("packages"))
    sources = {path: path.read_text(encoding="utf-8") for root in production_roots for path in root.rglob("*.py")}
    projection_store_users = {
        path for path, source in sources.items() if "OnlyPostgresPrivateAssetProductProjectionStore" in source
    }
    assert projection_store_users == {
        _PRODUCT_STORE,
        Path("src/onlyalpha/persistence/postgres/__init__.py"),
        _HTTP_MAIN,
    }
    for path, source in sources.items():
        if "runtime" in path.parts or "onlyalpha-agent-orchestrator" in path.parts:
            assert "onlyalpha.application.private_asset_product" not in source, path
            assert "private_asset_product_store" not in source, path


def test_exact_product_read_has_no_current_latest_or_legacy_fallback() -> None:
    tree = ast.parse(_PRODUCT_PROJECTION.read_text(encoding="utf-8"))
    service = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OnlyPrivateAssetProductService"
    )
    exact_read = next(node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == "read_exact")
    names = {node.attr for node in ast.walk(exact_read) if isinstance(node, ast.Attribute)}
    assert {"load_factor_revision", "load_strategy_revision"} <= names
    assert names.isdisjoint({"current_registry", "list_current_factor_revisions", "list_current_strategy_revisions"})
    assert "source_text" not in _PRODUCT_STORE.read_text(encoding="utf-8")
    assert "definition" not in _PRODUCT_STORE.read_text(encoding="utf-8")
    assert "create_private_asset_router" in _PRODUCT_HTTP.read_text(encoding="utf-8")
