from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_suite import LANES, OnlyTestLane

pytestmark = pytest.mark.architecture


def test_architecture_and_agent_rules_freeze_public_private_contract_parity() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "DB-native Example / Private Asset Contract Parity",
        "portable import/demo seeds",
        "no hidden private-only Core integration path",
    ):
        assert required in architecture
    for required in (
        "examples/private-assets/",
        "EXAMPLE_CONTRACT_COVERAGE_REQUIRED",
    ):
        assert required in agents


def test_private_asset_authoring_is_database_native_without_requiring_git_packages() -> None:
    adr = Path("docs/adr/0129-private-l3-l4-database-native-architecture-freeze.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    agent_architecture = Path("docs/agentic_alpha_discovery_architecture.md").read_text(encoding="utf-8")
    work_program = Path("docs/agent_factor_mining_work_program.md").read_text(encoding="utf-8")
    for required in (
        "PostgreSQL-backed Private Asset Authority",
        "Private L3 V1",
        "one exact L3 API Contract",
        "Private L4 V1",
        "Search Projection != Factor Authority",
        "REUSE",
        "GENERATE_NEW_L3",
        "Git, source checkouts, wheels and package distributions remain",
    ):
        assert required in adr
    for document in (architecture, agent_architecture, work_program):
        assert "ADR 0129" in document
        assert "PR-based private-asset admission" not in document


def test_private_examples_are_unpacked_database_import_seeds() -> None:
    root = Path("examples/private-assets")
    assert (root / "alpha/simple_momentum/asset.json").is_file()
    assert (root / "alpha/simple_momentum/source.py").is_file()
    assert (root / "strategy/simple_momentum/strategy.json").is_file()
    assert not tuple(root.rglob("pyproject.toml"))
    assert not tuple(root.rglob("provider.py"))


def test_private_asset_contract_lane_is_provider_neutral_and_executable() -> None:
    lane = LANES[OnlyTestLane.PRIVATE_ASSET_CONTRACT]
    assert "tests/quant_assets/test_private_asset_contract_conformance.py" in lane.paths
    assert "packages/onlyalpha-authoring-execution-worker/tests" in lane.paths
    assert "packages/onlyalpha-runtime-generation-manager/tests" in lane.paths
    assert lane.expression == "not external"
    source = Path("tests/quant_assets/test_private_asset_contract_conformance.py").read_text(encoding="utf-8")
    assert "OnlyPrivateAlphaExecutableClosureV1" in source
    assert "onlyalpha_alpha" not in source
    assert "onlyalpha_strategies" not in source
