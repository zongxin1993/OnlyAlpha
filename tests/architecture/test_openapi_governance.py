from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
GOVERNANCE = ROOT / "scripts/openapi_contract.py"
WRAPPER = ROOT / "scripts/export_research_openapi.py"


def test_one_v2_canonical_contract_and_one_bounded_pre_freeze_authorization() -> None:
    contract_root = ROOT / "contracts/product-api"
    contracts = sorted(
        path for path in contract_root.rglob("*") if path.is_file() and path.suffix in {".json", ".yaml", ".yml"}
    )
    authorization = ROOT / "contracts/product-api/v2/authorized-a0-corrections.json"
    assert contracts == [authorization, ROOT / "contracts/product-api/v2/openapi.json"]
    manifest = json.loads(authorization.read_text(encoding="utf-8"))
    assert manifest["classification"] == "REQUIRED_A0_CONTRACT_CORRECTION"
    assert manifest["adr"] == "docs/adr/0109-product-api-v2-a0-pre-freeze-contract-correction.md"
    assert manifest["base_git_sha"] == "8901fec27faf8599c965df792d07a84b902583f3"
    forbidden = {"baseline.json", "accepted.json", "accepted-openapi.json", "previous.json"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*.json"))


def test_fastapi_app_remains_authoring_authority_and_wrapper_has_no_duplicate_logic() -> None:
    source = GOVERNANCE.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "create_product_app" in source
    assert "app.openapi()" in source
    assert "json.dumps(" in source
    assert "governance_main(argv)" in wrapper
    assert "create_product_app" not in wrapper
    assert "json.dumps(" not in wrapper


def test_governance_has_immutable_git_baseline_and_no_breaking_bypass() -> None:
    source = GOVERNANCE.read_text(encoding="utf-8")
    assert '["git", "show"' in source
    assert "BASE_SHA must be a full lowercase Git object ID" in source
    for forbidden in ("accept-breaking", "ignore-breaking", "force-compatible"):
        assert forbidden not in source


def test_generated_web_client_has_only_canonical_openapi_source() -> None:
    package = (ROOT / "packages/onlyalpha-web-console/package.json").read_text(encoding="utf-8")
    web_suite = (ROOT / "scripts/web_suite.py").read_text(encoding="utf-8")
    assert package.count("../../contracts/product-api/v2/openapi.json") == 1
    assert "check_generated_client" in web_suite
    assert "openapi-typescript" not in web_suite


def test_core_domain_has_no_api_contract_tooling_dependency() -> None:
    forbidden = {"openapi_contract", "onlyalpha_http_server", "fastapi", "starlette"}
    for path in (ROOT / "src/onlyalpha").rglob("*.py"):
        assert not (imported_modules_for_path(path, ROOT) & forbidden), path


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
