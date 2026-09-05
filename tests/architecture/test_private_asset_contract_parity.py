from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.test_suite import LANES, OnlyTestLane

pytestmark = pytest.mark.architecture


def test_architecture_and_agent_rules_freeze_public_private_contract_parity() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "Public Example / Private Asset Contract Parity",
        "compatibility witnesses",
        "PRIVATE_ASSET_IMPACT = YES",
        "no hidden private-only Core integration path",
    ):
        assert required in architecture
    for required in (
        "public example conformance",
        "OnlyAlpha-alpha",
        "OnlyAlpha-strategies",
        "PRIVATE_ASSET_COMPATIBILITY_CERTIFICATION_PENDING",
        "EXAMPLE_CONTRACT_COVERAGE_REQUIRED",
    ):
        assert required in agents


def test_public_examples_do_not_import_or_embed_private_asset_implementations() -> None:
    roots = (Path("examples/onlyalpha-example-alpha"), Path("examples/onlyalpha-example-strategies"))
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
                alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
            }
            assert not any(name.startswith(("onlyalpha_alpha", "onlyalpha_strategies")) for name in imports), path
        content = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".json", ".md", ".toml"}
        )
        assert "private.factor." not in content
        assert "private.strategy." not in content


def test_private_asset_contract_lane_is_provider_neutral_and_executable() -> None:
    lane = LANES[OnlyTestLane.PRIVATE_ASSET_CONTRACT]
    assert "tests/quant_assets/test_private_asset_contract_conformance.py" in lane.paths
    assert "packages/onlyalpha-authoring-execution-worker/tests" in lane.paths
    assert "packages/onlyalpha-runtime-generation-manager/tests" in lane.paths
    assert lane.expression == "not external"
    source = Path("tests/quant_assets/test_private_asset_contract_conformance.py").read_text(encoding="utf-8")
    assert "ONLYALPHA_CONFORMANCE_L3_PROVIDER_ID" in source
    assert "ONLYALPHA_CONFORMANCE_L4_PROVIDER_ID" in source
    assert "onlyalpha_alpha" not in source
    assert "onlyalpha_strategies" not in source
