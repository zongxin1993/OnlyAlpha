import json
from pathlib import Path

import pytest

from scripts.certification import REQUIRED_GATES, build_evidence

SUBJECT_SHA = "a" * 40


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

    assert evidence["subject_sha"] == SUBJECT_SHA
    assert evidence["verdict"] == "ACCEPTED"
    assert set(evidence["required_gates"]) == REQUIRED_GATES  # type: ignore[arg-type]


@pytest.mark.parametrize("result", ("skipped", "failure", "cancelled"))
def test_mandatory_gate_cannot_silently_skip_or_fail(result: str) -> None:
    evidence = build_evidence(
        subject_sha=SUBJECT_SHA,
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        gate_values=_gate_values(coverage=result),
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


def test_missing_or_unexpected_gate_identity_fails_closed() -> None:
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


def test_subject_identity_must_be_full_immutable_sha() -> None:
    with pytest.raises(ValueError, match="40-character commit SHA"):
        build_evidence(
            subject_sha="main",
            workflow_run="123",
            workflow_url="https://example.invalid/actions/runs/123",
            gate_values=_gate_values(),
        )


def test_quality_and_certification_require_research_authority_lanes_and_coverage() -> None:
    quality = Path(".github/workflows/quality.yml").read_text()
    certification = Path(".github/workflows/certification.yml").read_text()
    assert "research-specification" in quality and "research-specification --coverage" in quality
    assert "research-specification" in certification and "research-specification --coverage" in certification
    assert "research-run" in quality and "research-run --coverage" in quality
    assert "research-run" in certification and "research-run --coverage" in certification
    assert "research-execution" in quality and "research-execution --coverage" in quality
    assert "research-execution" in certification and "research-execution --coverage" in certification
    for workflow in (quality, certification):
        assert "image: postgres:16.10" in workflow
        assert "ONLYALPHA_TEST_POSTGRES_DSN" in workflow
        assert "research-postgres --coverage" in workflow
    assert "research-dataset" in quality and "research-dataset --coverage" in quality
    assert "research-dataset" in certification and "research-dataset --coverage" in certification
    assert "research-job" in quality and "research-job --coverage" in quality
    assert "research-job" in certification and "research-job --coverage" in certification
    assert "research-factor" in quality and "research-factor --coverage" in quality
    assert "research-factor" in certification and "research-factor --coverage" in certification
    assert "research-sweep" in quality and "research-sweep --coverage" in quality
    assert "research-sweep" in certification and "research-sweep --coverage" in certification
    assert "research-evaluation" in quality and "research-evaluation --coverage" in quality
    assert "research-evaluation" in certification and "research-evaluation --coverage" in certification
    assert "research-result" in quality and "research-result --coverage" in quality
    assert "research-result" in certification and "research-result --coverage" in certification
    assert "research-artifact" in quality and "research-artifact --coverage" in quality
    assert "research-artifact" in certification and "research-artifact --coverage" in certification
    assert "research-runtime" in quality and "research-runtime --coverage" in quality
    assert "research-runtime" in certification and "research-runtime --coverage" in certification
    assert '"$COVERAGE_RESULT" = success' in quality
    for workflow in (quality, certification):
        assert 'node-version: "24"' in workflow
        assert "web-static" in workflow
        assert "web-unit" in workflow
        assert "web-build" in workflow
        assert "web-e2e" in workflow


def test_task_impact_resolver_cannot_trim_certification_mandatory_matrix() -> None:
    certification = Path(".github/workflows/certification.yml").read_text()
    verify_source = Path("scripts/verify.py").read_text()

    assert "scripts/verify.py" not in certification
    assert "subject_sha" in certification
    for mandatory in ("static", "build", "coverage", "semgrep", "dependency-audit", "codeql"):
        assert mandatory in certification
    assert 'authority": "LOCAL_DEVELOPMENT_VERIFICATION_ONLY' in verify_source


def test_quality_and_certification_require_every_authoritative_lock_dependency_audit() -> None:
    quality = Path(".github/workflows/quality.yml").read_text()
    certification = Path(".github/workflows/certification.yml").read_text()
    for workflow in (quality, certification):
        assert "dependency-audit:" in workflow
        assert "--lockfile=uv.lock" in workflow
        assert "--lockfile=apps/onlyalpha-web/package-lock.json" in workflow
        assert 'scanner-version "2.5.0"' in workflow
        assert "continue-on-error" not in workflow
    assert (
        "needs: [static, semgrep, dependency-audit, coverage, pr-lanes, main-lanes, research-postgres, build, web]"
        in quality
    )
    assert '"$DEPENDENCY_AUDIT_RESULT" = success' in quality
    assert (
        "needs: [subject, static, build, web, lanes, research-postgres, coverage, semgrep, dependency-audit, codeql]"
        in certification
    )
    assert '--gate "research-postgres=$POSTGRES_RESULT"' in certification
    assert '--gate "dependency-audit=$DEPENDENCY_AUDIT_RESULT"' in certification
    assert '--gate "web=$WEB_RESULT"' in certification


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
    assert roadmap.count("Current Milestone: P8") == 1
    assert roadmap.count("Milestone State: IN_PROGRESS") == 1
    assert roadmap.count("Current Increment: P8.4.0.1 — IMPLEMENTED / VERIFIED LOCALLY") == 1
    assert roadmap.count("P7 Final Certification Verdict: ACCEPTED") == 1
    assert "## 当前阶段：P6" not in roadmap
    assert "| P7 | **DONE / CERTIFIED** — Vectorized Research Runtime |" in readme
    assert "| Current increment | **P8.4.0.1 — IMPLEMENTED / VERIFIED locally**" in readme
