from __future__ import annotations

import json
from pathlib import Path

from scripts.dependency_audit import build_dependency_audit_evidence

SUBJECT_SHA = "a" * 40


def _evidence(tmp_path: Path, payload: object, *, outcome: str = "success") -> dict[str, object]:
    lockfile = tmp_path / "uv.lock"
    result = tmp_path / "osv-results.json"
    lockfile.write_text("version = 1\n", encoding="utf-8")
    result.write_text(json.dumps(payload), encoding="utf-8")
    return build_dependency_audit_evidence(
        subject_sha=SUBJECT_SHA,
        lockfile=lockfile,
        scanner="OSV-Scanner",
        scanner_version="2.5.0",
        scan_time="2026-08-15T01:02:03Z",
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        scan_outcome=outcome,
        scan_result=result,
    )


def test_empty_verified_scan_is_time_scoped_pass_evidence(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, {"results": []})

    assert evidence["status"] == "PASSED"
    assert evidence["audited_authority"] == "uv.lock"
    assert evidence["scanner_version"] == "2.5.0"
    assert evidence["scan_time"] == "2026-08-15T01:02:03Z"
    assert evidence["findings"] == []
    assert evidence["approved_exceptions"] == []
    assert len(str(evidence["uv_lock_sha256"])) == 64


def test_known_vulnerability_fails_closed_without_implicit_exception(tmp_path: Path) -> None:
    evidence = _evidence(
        tmp_path,
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"name": "demo", "version": "1.0", "ecosystem": "PyPI"},
                            "groups": [
                                {
                                    "ids": ["PYSEC-1", "GHSA-1"],
                                    "aliases": ["CVE-1"],
                                    "max_severity": "8.2",
                                }
                            ],
                            "vulnerabilities": [{"id": "PYSEC-1"}],
                        }
                    ]
                }
            ]
        },
        outcome="failure",
    )

    assert evidence["status"] == "VULNERABILITY_FOUND"
    assert evidence["approved_exceptions"] == []
    assert evidence["findings"] == [
        {
            "ecosystem": "PyPI",
            "package": "demo",
            "version": "1.0",
            "ids": ["GHSA-1", "PYSEC-1"],
            "aliases": ["CVE-1"],
            "max_severity": "8.2",
        }
    ]


def test_scanner_failure_without_findings_is_not_reported_as_pass(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, {"results": []}, outcome="failure")

    assert evidence["status"] == "SCAN_INFRASTRUCTURE_FAILURE"


def test_missing_or_invalid_scanner_output_is_infrastructure_failure(tmp_path: Path) -> None:
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("version = 1\n", encoding="utf-8")
    evidence = build_dependency_audit_evidence(
        subject_sha=SUBJECT_SHA,
        lockfile=lockfile,
        scanner="OSV-Scanner",
        scanner_version="2.5.0",
        scan_time="2026-08-15T01:02:03+00:00",
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        scan_outcome="failure",
        scan_result=tmp_path / "missing.json",
    )

    assert evidence["status"] == "SCAN_INFRASTRUCTURE_FAILURE"
    assert evidence["result_error"]


def test_authoritative_python_and_web_locks_are_one_fail_closed_gate(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    python_lock = Path("uv.lock")
    web_lock = Path("apps/onlyalpha-web/package-lock.json")
    python_lock.write_text("version = 1\n", encoding="utf-8")
    web_lock.parent.mkdir(parents=True)
    web_lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    result = Path("result.json")
    result.write_text('{"results":[]}\n', encoding="utf-8")

    evidence = build_dependency_audit_evidence(
        subject_sha=SUBJECT_SHA,
        lockfiles=(python_lock, web_lock),
        scanner="OSV-Scanner",
        scanner_version="2.5.0",
        scan_time="2026-08-15T01:02:03Z",
        workflow_run="123",
        workflow_url="https://example.invalid/actions/runs/123",
        scan_outcome="success",
        scan_result=result,
    )

    assert evidence["status"] == "PASSED"
    assert evidence["audited_authorities"] == ["apps/onlyalpha-web/package-lock.json", "uv.lock"]
    assert set(evidence["lock_sha256"]) == {"uv.lock", "apps/onlyalpha-web/package-lock.json"}
