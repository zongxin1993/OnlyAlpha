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


def test_quality_and_certification_require_research_dataset_lane_and_coverage() -> None:
    quality = Path(".github/workflows/quality.yml").read_text()
    certification = Path(".github/workflows/certification.yml").read_text()
    assert "research-dataset" in quality and "research-dataset --coverage" in quality
    assert "research-dataset" in certification and "research-dataset --coverage" in certification
    assert '"$COVERAGE_RESULT" = success' in quality
