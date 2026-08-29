from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.pytest_layering import path_concerns, path_layer  # noqa: E402
from scripts.test_suite import (  # noqa: E402
    LANES,
    RELEASE_LANES,
    RELEASE_STATIC_COMMANDS,
    WORKSPACE_TESTS,
    OnlyTestLane,
    workspace_test_paths,
)


def test_core_full_lane_covers_every_workspace_test_distribution() -> None:
    assert LANES[OnlyTestLane.CORE_FULL].paths == WORKSPACE_TESTS
    assert "external" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "performance" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "recovery" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "conformance" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "exhaustive" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "historical_git" in LANES[OnlyTestLane.CORE_FULL].expression


def test_workspace_tests_are_derived_from_root_pytest_testpaths(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.pytest.ini_options]\ntestpaths = ["tests", "packages/new/tests"]\n')

    assert workspace_test_paths(pyproject) == ("tests", "packages/new/tests")


def test_binance_offline_packages_are_in_core_full_and_network_contract_is_excluded() -> None:
    assert "packages/market/onlyalpha-market-binance-spot/tests" in WORKSPACE_TESTS
    assert "packages/provider/onlyalpha-plugin-binance/tests" in WORKSPACE_TESTS
    assert "external" in LANES[OnlyTestLane.CORE_FULL].expression
    assert "requires_network" in LANES[OnlyTestLane.CORE_FULL].expression
    public_contract = (ROOT / "packages/provider/onlyalpha-plugin-binance/tests/test_public_contract.py").read_text()
    assert "pytest.mark.external" in public_contract
    assert "pytest.mark.requires_network" in public_contract


def test_historical_git_contract_has_one_explicit_history_capable_owner() -> None:
    historical = (ROOT / "tests/contracts/test_p9_k7_task_delta.py").read_text()
    assert "pytest.mark.historical_git" in historical
    assert "historical_git" in LANES[OnlyTestLane.FAST].expression
    assert "historical_git" in LANES[OnlyTestLane.CORE_FULL].expression


def test_release_static_uses_root_mypy_authority_and_package_local_exceptions() -> None:
    assert ("uv", "run", "mypy") in RELEASE_STATIC_COMMANDS
    joined = {" ".join(command) for command in RELEASE_STATIC_COMMANDS}
    assert not any(command.startswith("uv run mypy src/onlyalpha") for command in joined)
    for package in (
        "onlyalpha-plugin-broker-virtual",
        "onlyalpha-market-generic-t0-cash",
        "onlyalpha-market-cn-ashare",
        "onlyalpha-plugin-tushare",
        "onlyalpha-plugin-miniqmt",
    ):
        assert any("packages/" in command and package in command for command in joined)


def test_external_and_real_order_tests_are_excluded_from_offline_lanes() -> None:
    for name in (OnlyTestLane.FAST, OnlyTestLane.INTEGRATION, OnlyTestLane.ASHARE, OnlyTestLane.CORE_FULL):
        assert "external" in LANES[name].expression
    assert "not requires_broker_account" in LANES[OnlyTestLane.MINIQMT_LOCAL].expression


def test_production_sources_have_no_test_performance_switches() -> None:
    forbidden = ("test_mode", "skip_artifact_for_test", "skip_recovery_for_test", "fake_engine_path")
    offenders: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")
    assert offenders == []


def test_xdist_is_a_development_dependency_only() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project, dependency_groups = text.split("[dependency-groups]", maxsplit=1)
    assert "pytest-xdist" not in project
    assert "pytest-xdist" in dependency_groups


def test_unknown_component_paths_are_classified_without_guessing_unit_for_special_layers() -> None:
    assert path_layer(Path("tests/architecture/test_gate.py")) == "architecture"
    assert path_layer(Path("tests/integration/test_engine_restart.py")) == "integration"
    assert path_concerns(Path("tests/integration/test_engine_restart.py")) == {"recovery"}
    assert path_layer(Path("packages/provider/plugin/tests/test_adapter.py")) == "contract"


def test_miniqmt_golden_reader_is_offline_test_support() -> None:
    source = (ROOT / "tests/support/golden_data.py").read_text(encoding="utf-8")
    assert "import xtquant" not in source
    assert "from xtquant" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "socket" not in source
    assert not (ROOT / "src/onlyalpha/golden_data.py").exists()
    assert (ROOT / "tests/fixtures/miniqmt/cn_a_share_v1/bars.parquet").is_file()
    assert (ROOT / "tests/fixtures/miniqmt/cn_a_share_v1/capture_manifest.json").is_file()


def test_ashare_lane_selects_offline_miniqmt_golden_conformance() -> None:
    lane = LANES[OnlyTestLane.ASHARE]
    assert "conformance" in lane.expression
    assert "external" in lane.expression
    source = (ROOT / "tests/conformance/cn_a_share_cash/test_miniqmt_golden.py").read_text(encoding="utf-8")
    assert "pytest.mark.conformance" in source
    assert "pytest.mark.miniqmt" in source


def test_release_and_local_runner_boundaries_are_explicit() -> None:
    source = (ROOT / "scripts/test_suite.py").read_text(encoding="utf-8")
    for lane in (
        "OnlyTestLane.RESEARCH_JOB",
        "OnlyTestLane.CORE_FULL",
        "OnlyTestLane.RECOVERY",
        "OnlyTestLane.ASHARE",
        "OnlyTestLane.MINIQMT_CONTRACT",
    ):
        assert lane in source
    assert LANES[OnlyTestLane.MINIQMT_LOCAL].workers == "0"
    assert "not requires_broker_account" in LANES[OnlyTestLane.MINIQMT_LOCAL].expression


def test_release_runs_each_canonical_lane_exactly_once() -> None:
    assert len(RELEASE_LANES) == len(set(RELEASE_LANES))


def test_miniqmt_read_only_and_order_workflows_are_separate() -> None:
    local = (ROOT / ".github/workflows/miniqmt-local.yml").read_text(encoding="utf-8")
    order = (ROOT / ".github/workflows/miniqmt-order.yml").read_text(encoding="utf-8")
    assert "verify_miniqmt_local.py" in local
    assert "test_suite.py miniqmt-local" in local
    assert "miniqmt-dedicated-test-account" in order
    assert "I_UNDERSTAND" in order
    assert "Order execution is intentionally not enabled in P0" in order
