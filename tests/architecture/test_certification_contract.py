from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from scripts.certification import REQUIRED_GATES, build_evidence
from scripts.quality_policy import load_quality_policy
from scripts.test_suite import RELEASE_STATIC_COMMANDS

SUBJECT_SHA = "a" * 40
POLICY = load_quality_policy()
CANONICAL_STATIC_COMMAND = "uv run python scripts/test_suite.py release-static"
CANONICAL_GATEWAY_COMMAND = (
    'uv run python scripts/gateway_protocol.py verify-lane --base "${{ steps.baseline.outputs.sha }}"'
)


def _workflow(path: str) -> dict[str, dict[str, object]]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
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


def _named_step(job: dict[str, object], name: str) -> dict[str, object]:
    return next(step for step in _steps(job) if step.get("name") == name)


def _result_variable(gate: str) -> str:
    return gate.replace("-", "_").upper() + "_RESULT"


def _gate_values(**changes: str) -> list[str]:
    results = {name: "success" for name in REQUIRED_GATES}
    results.update(changes)
    return [f"{name}={result}" for name, result in sorted(results.items())]


def test_complete_same_sha_gate_set_is_accepted() -> None:
    evidence = build_evidence(
        subject_sha=SUBJECT_SHA,
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        gate_values=_gate_values(),
    )

    assert evidence["schema_version"] == 2
    assert evidence["quality_policy_schema_version"] == POLICY.schema_version
    assert evidence["subject_sha"] == SUBJECT_SHA
    assert evidence["verdict"] == "ACCEPTED"
    assert set(evidence["required_gates"]) == REQUIRED_GATES  # type: ignore[arg-type]


@pytest.mark.parametrize("result", ("skipped", "failure", "cancelled"))
def test_mandatory_gate_cannot_silently_skip_or_fail(result: str) -> None:
    evidence = build_evidence(
        subject_sha=SUBJECT_SHA,
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        gate_values=_gate_values(**{"gateway-protocol": result}),
    )

    assert evidence["verdict"] == "REJECTED"


@pytest.mark.parametrize("result", ("skipped", "failure", "cancelled"))
def test_dependency_audit_is_a_mandatory_certification_gate(result: str) -> None:
    evidence = build_evidence(
        subject_sha=SUBJECT_SHA,
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        gate_values=_gate_values(**{"dependency-audit": result}),
    )

    assert evidence["verdict"] == "REJECTED"


def test_missing_unexpected_or_duplicate_gate_identity_fails_closed() -> None:
    values = _gate_values()
    with pytest.raises(ValueError, match="gate identity mismatch"):
        build_evidence(
            subject_sha=SUBJECT_SHA,
            workflow_run="123",
            workflow_url="https://example.invalid/actions/runs/123",
            gate_values=values[:-1],
        )
    with pytest.raises(ValueError, match="gate identity mismatch"):
        build_evidence(
            subject_sha=SUBJECT_SHA,
            workflow_run="123",
            workflow_url="https://example.invalid/actions/runs/123",
            gate_values=[*values, "optional=success"],
        )
    with pytest.raises(ValueError, match="duplicate gate result"):
        build_evidence(
            subject_sha=SUBJECT_SHA,
            workflow_run="123",
            workflow_url="https://example.invalid/actions/runs/123",
            gate_values=[*values, values[0]],
        )


def test_subject_identity_must_be_full_immutable_sha() -> None:
    with pytest.raises(ValueError, match="40-character commit SHA"):
        build_evidence(
            subject_sha="main",
            workflow_run="123",
            workflow_url="https://example.invalid/actions/runs/123",
            gate_values=_gate_values(),
        )


def test_machine_policy_is_the_only_mandatory_gate_authority() -> None:
    quality = _workflow(".github/workflows/quality.yml")
    certification = _workflow(".github/workflows/certification.yml")
    quality_gate = quality["quality-gate"]
    certification_verdict = certification["verdict"]

    quality_needs = quality_gate.get("needs")
    certification_needs = certification_verdict.get("needs")
    assert isinstance(quality_needs, list)
    assert isinstance(certification_needs, list)
    assert set(quality_needs) == POLICY.quality_required_gates | POLICY.quality_event_lane_gates
    assert set(certification_needs) == POLICY.certification_required_gates

    quality_step = _named_step(quality_gate, "Require every independent gate")
    quality_env = quality_step.get("env")
    quality_run = quality_step.get("run")
    assert isinstance(quality_env, dict)
    assert isinstance(quality_run, str)
    for gate in POLICY.quality_required_gates | POLICY.quality_event_lane_gates:
        variable = _result_variable(gate)
        assert quality_env.get(variable) == f"${{{{ needs.{gate}.result }}}}"
        assert f'"${variable}"' in quality_run
    for gate in POLICY.quality_required_gates:
        assert f'"${_result_variable(gate)}" = success' in quality_run
    for gate in POLICY.quality_event_lane_gates:
        variable = _result_variable(gate)
        assert f'"${variable}" = success' in quality_run
        assert f'"${variable}" = skipped' in quality_run

    verdict_step = _named_step(certification_verdict, "Require every mandatory final-SHA gate")
    verdict_env = verdict_step.get("env")
    verdict_run = verdict_step.get("run")
    assert isinstance(verdict_env, dict)
    assert isinstance(verdict_run, str)
    for gate in POLICY.certification_required_gates:
        variable = _result_variable(gate)
        assert verdict_env.get(variable) == f"${{{{ needs.{gate}.result }}}}"
        assert f'--gate "{gate}=${variable}"' in verdict_run


def test_coverage_is_manual_but_the_local_capability_and_thresholds_remain() -> None:
    quality = _workflow(".github/workflows/quality.yml")
    certification = _workflow(".github/workflows/certification.yml")
    test_suite = Path("scripts/test_suite.py").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert POLICY.coverage_mode == "manual"
    assert "coverage" not in quality
    assert "coverage" not in certification
    assert "coverage" not in POLICY.quality_required_gates
    assert "coverage" not in POLICY.certification_required_gates
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
        """schema_version = 1
coverage_mode = "manual"
[quality]
required_gates = ["gateway-protocol", "gateway-protocol"]
event_lane_gates = ["pr-lanes"]
[certification]
required_gates = ["gateway-protocol"]
[historical_evidence]
exclusive_owner = "gateway-protocol"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate gates"):
        load_quality_policy(policy)


def test_functional_research_postgres_and_web_jobs_remain_active() -> None:
    required_lanes = {
        "research-definition",
        "research-specification",
        "research-run",
        "research-execution",
        "research-dataset",
        "research-job",
        "research-factor",
        "research-sweep",
        "research-evaluation",
        "research-result",
        "research-artifact",
        "research-runtime",
        "core-full",
    }
    for path in (".github/workflows/quality.yml", ".github/workflows/certification.yml"):
        jobs = _workflow(path)
        lane_job = jobs["main-lanes"] if "main-lanes" in jobs else jobs["lanes"]
        strategy = lane_job.get("strategy")
        assert isinstance(strategy, dict)
        matrix = strategy.get("matrix")
        assert isinstance(matrix, dict)
        lanes = matrix.get("lane")
        assert isinstance(lanes, list)
        assert required_lanes <= set(lanes)
        postgres_runs = _runs(jobs["research-postgres"])
        assert "uv run python scripts/test_suite.py research-product-closure" in postgres_runs
        assert "uv run python scripts/test_suite.py research-postgres" in postgres_runs
        assert all("--coverage" not in run for run in postgres_runs)
        web_runs = _runs(jobs["web"])
        for command in ("static", "unit", "build", "e2e"):
            assert f"uv run python scripts/web_suite.py {command}" in web_runs


def test_gateway_protocol_is_the_only_history_owner_and_uses_one_command() -> None:
    assert POLICY.historical_evidence_owner == "gateway-protocol"
    for path in (".github/workflows/quality.yml", ".github/workflows/certification.yml"):
        gateway = _workflow(path)[POLICY.historical_evidence_owner]
        checkout = next(step for step in _steps(gateway) if step.get("uses") == "actions/checkout@v6")
        checkout_with = checkout.get("with")
        assert isinstance(checkout_with, dict)
        assert checkout_with.get("fetch-depth") == 0
        assert CANONICAL_GATEWAY_COMMAND in _runs(gateway)


def test_static_projections_and_release_use_one_canonical_command_owner() -> None:
    assert ("uv", "run", "mypy") in RELEASE_STATIC_COMMANDS
    root_mypy_targets = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "onlyalpha_market_binance_spot" in root_mypy_targets
    assert "onlyalpha_plugin_binance" in root_mypy_targets
    for path in (".github/workflows/quality.yml", ".github/workflows/certification.yml"):
        runs = _runs(_workflow(path)["static"])
        assert runs.count(CANONICAL_STATIC_COMMAND) == 1
        assert not any(run.startswith("uv run mypy") for run in runs)


def test_task_impact_resolver_cannot_trim_certification_mandatory_matrix() -> None:
    certification = _workflow(".github/workflows/certification.yml")
    verify_source = Path("scripts/verify.py").read_text(encoding="utf-8")

    assert set(certification["verdict"]["needs"]) == POLICY.certification_required_gates  # type: ignore[arg-type]
    assert 'authority": "LOCAL_DEVELOPMENT_VERIFICATION_ONLY' in verify_source


def test_quality_and_certification_require_every_authoritative_lock_dependency_audit() -> None:
    for path in (".github/workflows/quality.yml", ".github/workflows/certification.yml"):
        job = _workflow(path)["dependency-audit"]
        steps = _steps(job)
        scan = next(step for step in steps if str(step.get("uses", "")).startswith("google/osv-scanner-action/"))
        scan_with = scan.get("with")
        assert isinstance(scan_with, dict)
        scan_args = scan_with.get("scan-args")
        assert isinstance(scan_args, str)
        runs = "\n".join(_runs(job))
        assert "--lockfile=uv.lock" in scan_args
        assert "--lockfile=apps/onlyalpha-web/package-lock.json" in scan_args
        assert 'scanner-version "2.5.0"' in runs
        assert all("continue-on-error" not in step for step in steps)


def test_nightly_performance_is_a_same_runner_commit_comparison_with_real_evidence() -> None:
    nightly = Path(".github/workflows/nightly.yml").read_text()
    performance = nightly.split("  performance:", maxsplit=1)[1]
    assert "fetch-depth: 0" in performance
    assert "asv check" in performance
    assert "asv machine --yes" in performance
    assert "asv continuous" in performance
    assert "--interleave-rounds" in performance
    assert "HEAD^ HEAD" in performance
    assert "--quick" not in performance
    assert "--benchmark-json=" in performance
    assert "test-results/performance/asv-continuous.txt" in performance
    assert ".asv/results/" in performance


def test_asv_builds_exactly_the_benchmarked_root_distribution() -> None:
    config = json.loads(Path("asv.conf.json").read_text())
    assert config["project"] == "OnlyAlpha"
    assert config["environment_type"] == "uv"
    assert config["build_command"] == ["python -m pip wheel --no-deps -w {build_cache_dir} {build_dir}"]


def test_readme_and_roadmap_expose_one_truthful_current_increment() -> None:
    readme = Path("README.md").read_text()
    roadmap = Path("docs/roadmap.md").read_text()
    roadmap_fields = dict(
        re.findall(
            r"^(Current Milestone|Milestone State|Current Increment|Next Semantic Direction): (.+)$",
            roadmap,
            re.MULTILINE,
        )
    )
    readme_fields = {
        key: value.replace("**", "").strip()
        for key, value in re.findall(
            r"^\| (Current milestone|Current increment|Next semantic direction) \| (.+) \|$", readme, re.MULTILINE
        )
    }
    assert set(roadmap_fields) == {
        "Current Milestone",
        "Milestone State",
        "Current Increment",
        "Next Semantic Direction",
    }
    assert (
        f"{roadmap_fields['Current Milestone']} — {roadmap_fields['Milestone State']}"
        in readme_fields["Current milestone"]
    )
    assert readme_fields["Current increment"].casefold() == roadmap_fields["Current Increment"].casefold()
    assert readme_fields["Next semantic direction"].casefold() == roadmap_fields["Next Semantic Direction"].casefold()
    assert roadmap.count("P7 Final Certification Verdict: ACCEPTED") == 1
    assert "## 当前阶段：P6" not in roadmap
    assert "| P7 | **DONE / CERTIFIED** — Vectorized Research Runtime |" in readme
