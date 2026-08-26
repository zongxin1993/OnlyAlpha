from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
GOVERNANCE = ROOT / "scripts/openapi_contract.py"
WRAPPER = ROOT / "scripts/export_research_openapi.py"


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return frozenset(
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    )


def test_one_v2_canonical_contract_and_no_mutable_baseline() -> None:
    contract_root = ROOT / "contracts/research-api"
    contracts = sorted(
        path for path in contract_root.rglob("*") if path.is_file() and path.suffix in {".json", ".yaml", ".yml"}
    )
    assert contracts == [ROOT / "contracts/research-api/v2/openapi.json"]
    forbidden = {"baseline.json", "accepted.json", "accepted-openapi.json", "previous.json"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*.json"))


def test_fastapi_app_remains_authoring_authority_and_wrapper_has_no_duplicate_logic() -> None:
    source = GOVERNANCE.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "create_research_app" in source
    assert "app.openapi()" in source
    assert "json.dumps(" in source
    assert "governance_main(argv)" in wrapper
    assert "create_research_app" not in wrapper
    assert "json.dumps(" not in wrapper


def test_governance_has_immutable_git_baseline_and_no_breaking_bypass() -> None:
    source = GOVERNANCE.read_text(encoding="utf-8")
    assert '["git", "show"' in source
    assert "BASE_SHA must be a full lowercase Git object ID" in source
    for forbidden in ("accept-breaking", "ignore-breaking", "force-compatible"):
        assert forbidden not in source


def test_generated_web_client_has_only_canonical_openapi_source() -> None:
    package = (ROOT / "apps/onlyalpha-web/package.json").read_text(encoding="utf-8")
    web_suite = (ROOT / "scripts/web_suite.py").read_text(encoding="utf-8")
    assert package.count("../../contracts/research-api/v2/openapi.json") == 1
    assert "check_generated_client" in web_suite
    assert "openapi-typescript" not in web_suite


def test_core_domain_has_no_api_contract_tooling_dependency() -> None:
    forbidden = {"openapi_contract", "onlyalpha_api", "fastapi", "starlette"}
    for path in (ROOT / "src/onlyalpha").rglob("*.py"):
        assert not (_imports(path) & forbidden), path


def test_k4_does_not_start_v3_k5_k6_or_k7() -> None:
    assert not (ROOT / "contracts/research-api/v3").exists()
    assert not (ROOT / "packages/client/onlyalpha-client").exists()
    changed = "\n".join(path.as_posix() for path in ROOT.rglob("*"))
    assert "scripts/openapi_contract.py" in changed
    source = GOVERNANCE.read_text(encoding="utf-8")
    for forbidden in ("grpc", "protobuf", "asyncapi", "kafka", "nats", "idempotency ledger"):
        assert forbidden not in source.lower()


def test_contract_metadata_does_not_enter_semantic_identity_code() -> None:
    semantic_roots = (
        ROOT / "src/onlyalpha/calculation",
        ROOT / "src/onlyalpha/research",
        ROOT / "src/onlyalpha/strategy",
    )
    forbidden = ("OPENAPI", "operationId", "contract_sha256", "API_MAJOR")
    for root in semantic_roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(token in source for token in forbidden), path
