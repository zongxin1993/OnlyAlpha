from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.quality_policy import load_quality_policy
from scripts.test_suite import RELEASE_STATIC_COMMANDS

POLICY = load_quality_policy()
CANONICAL_STATIC_COMMAND = "uv run python scripts/test_suite.py release-static"
CANONICAL_GATEWAY_COMMAND = (
    'uv run python scripts/gateway_protocol.py verify-lane --base "${{ steps.baseline.outputs.sha }}"'
)


def _workflow() -> dict[str, dict[str, object]]:
    document = yaml.safe_load(Path(".github/workflows/quality.yml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _runs(job: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(step["run"]) for step in _steps(job) if "run" in step)


def _result_variable(gate: str) -> str:
    return gate.replace("-", "_").upper() + "_RESULT"


def test_only_task_and_phase_gate_authorities_remain() -> None:
    root = Path(".")
    assert not (root / ".github/workflows/certification.yml").exists()
    assert not (root / "scripts/certification.py").exists()
    assert "certification" not in (root / "quality-policy.toml").read_text(encoding="utf-8")
    assert "[certification]" not in (root / "project-state.toml").read_text(encoding="utf-8")


def test_machine_policy_is_the_only_quality_gate_authority() -> None:
    quality = _workflow()
    quality_gate = quality["quality-gate"]
    needs = quality_gate.get("needs")
    assert isinstance(needs, list)
    assert set(needs) == POLICY.quality_required_gates | POLICY.quality_event_lane_gates

    step = next(step for step in _steps(quality_gate) if step.get("name") == "Require every independent gate")
    env = step.get("env")
    run = step.get("run")
    assert isinstance(env, dict)
    assert isinstance(run, str)
    for gate in POLICY.quality_required_gates | POLICY.quality_event_lane_gates:
        variable = _result_variable(gate)
        assert env.get(variable) == f"${{{{ needs.{gate}.result }}}}"
        assert f'"${variable}"' in run
    for gate in POLICY.quality_required_gates:
        assert f'"${_result_variable(gate)}" = success' in run
    for gate in POLICY.quality_event_lane_gates:
        variable = _result_variable(gate)
        assert f'"${variable}" = success' in run
        assert f'"${variable}" = skipped' in run


def test_coverage_is_manual_but_capability_and_thresholds_remain() -> None:
    quality = _workflow()
    test_suite = Path("scripts/test_suite.py").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert POLICY.coverage_mode == "manual"
    assert "coverage" not in quality
    assert "coverage" not in POLICY.quality_required_gates
    assert "--coverage" in test_suite
    assert "--cov-fail-under=" in test_suite
    assert "fail_under = 82" in pyproject
    assert "pytest-cov" in pyproject


def test_commented_yaml_cannot_satisfy_an_active_job_contract() -> None:
    document = yaml.safe_load("jobs:\n  static: {}\n  # coverage:\n  #   runs-on: ubuntu-latest\n")
    assert set(document["jobs"]) == {"static"}


def test_quality_policy_rejects_duplicate_gate_identity(tmp_path: Path) -> None:
    policy = tmp_path / "quality-policy.toml"
    policy.write_text(
        """schema_version = 2
coverage_mode = "manual"
[quality]
required_gates = ["gateway-protocol", "gateway-protocol"]
event_lane_gates = ["pr-lanes"]
[historical_evidence]
exclusive_owner = "gateway-protocol"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate gates"):
        load_quality_policy(policy)


def test_functional_postgres_web_and_broad_lanes_remain_active() -> None:
    jobs = _workflow()
    matrix = jobs["main-lanes"]["strategy"]["matrix"]  # type: ignore[index]
    assert isinstance(matrix, dict)
    lanes = matrix.get("lane")
    assert isinstance(lanes, list)
    assert {"core-full", "recovery", "research-runtime", "research-dataset"} <= set(lanes)
    assert "uv run python scripts/test_suite.py research-product-closure" in _runs(jobs["research-postgres"])
    assert "uv run python scripts/test_suite.py research-postgres" in _runs(jobs["research-postgres"])
    for command in ("static", "unit", "build", "e2e"):
        assert f"uv run python scripts/web_suite.py {command}" in _runs(jobs["web"])


def test_gateway_protocol_is_the_only_history_owner() -> None:
    gateway = _workflow()[POLICY.historical_evidence_owner]
    checkout = next(step for step in _steps(gateway) if step.get("uses") == "actions/checkout@v6")
    checkout_with = checkout.get("with")
    assert isinstance(checkout_with, dict)
    assert checkout_with.get("fetch-depth") == 0
    assert CANONICAL_GATEWAY_COMMAND in _runs(gateway)


def test_static_projection_uses_canonical_root_mypy_owner() -> None:
    assert ("uv", "run", "mypy") in RELEASE_STATIC_COMMANDS
    root_mypy_targets = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "onlyalpha_market_binance_spot" in root_mypy_targets
    assert "onlyalpha_plugin_binance" in root_mypy_targets
    runs = _runs(_workflow()["static"])
    assert runs.count(CANONICAL_STATIC_COMMAND) == 1
    assert not any(run.startswith("uv run mypy") for run in runs)


def test_quality_dependency_audit_uses_every_authoritative_lock() -> None:
    job = _workflow()["dependency-audit"]
    steps = _steps(job)
    scan = next(step for step in steps if str(step.get("uses", "")).startswith("google/osv-scanner-action/"))
    scan_with = scan.get("with")
    assert isinstance(scan_with, dict)
    scan_args = scan_with.get("scan-args")
    assert isinstance(scan_args, str)
    assert "--lockfile=uv.lock" in scan_args
    assert "--lockfile=apps/onlyalpha-web/package-lock.json" in scan_args
    assert all("continue-on-error" not in step for step in steps)
