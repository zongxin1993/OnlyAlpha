from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.pytest_layering import path_marker  # noqa: E402
from scripts.test_suite import LANES, WORKSPACE_TESTS, OnlyTestLane  # noqa: E402


def test_full_lane_covers_every_workspace_test_distribution() -> None:
    assert LANES[OnlyTestLane.FULL].paths == WORKSPACE_TESTS
    assert "external" in LANES[OnlyTestLane.FULL].expression
    assert "performance" in LANES[OnlyTestLane.FULL].expression


def test_external_and_real_order_tests_are_excluded_from_offline_lanes() -> None:
    for name in (OnlyTestLane.FAST, OnlyTestLane.INTEGRATION, OnlyTestLane.ASHARE, OnlyTestLane.FULL):
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
    assert path_marker(Path("tests/architecture/test_gate.py")) == "architecture"
    assert path_marker(Path("tests/integration/test_engine_restart.py")) == "recovery"
    assert path_marker(Path("packages/provider/plugin/tests/test_adapter.py")) == "contract"
