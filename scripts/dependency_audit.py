from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_SUCCESS = "PASSED"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lock_authority(path: Path) -> str:
    if path.name == "uv.lock":
        return "uv.lock"
    if path.name == "package-lock.json" and path.parent.name == "onlyalpha-web":
        return "apps/onlyalpha-web/package-lock.json"
    return path.as_posix()


def _scan_time(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("scan_time must be an ISO-8601 UTC timestamp")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        return ()
    return tuple(sorted(set(value)))


def _findings(payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    findings: list[dict[str, object]] = []
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("OSV result must contain a results array")
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("OSV result entry must be an object")
        packages = result.get("packages", [])
        if not isinstance(packages, list):
            raise ValueError("OSV packages must be an array")
        for package_entry in packages:
            if not isinstance(package_entry, Mapping) or not isinstance(package_entry.get("package"), Mapping):
                raise ValueError("OSV package entry must contain package metadata")
            package = cast(Mapping[str, object], package_entry["package"])
            name, version, ecosystem = package.get("name"), package.get("version"), package.get("ecosystem")
            if not all(isinstance(item, str) and item for item in (name, version, ecosystem)):
                raise ValueError("OSV package identity is incomplete")
            groups = package_entry.get("groups", [])
            vulnerabilities = package_entry.get("vulnerabilities", [])
            if not isinstance(groups, list) or not isinstance(vulnerabilities, list):
                raise ValueError("OSV finding collections must be arrays")
            if groups:
                for group in groups:
                    if not isinstance(group, Mapping) or not (ids := _strings(group.get("ids"))):
                        raise ValueError("OSV vulnerability group must contain ids")
                    findings.append(
                        {
                            "ecosystem": ecosystem,
                            "package": name,
                            "version": version,
                            "ids": list(ids),
                            "aliases": list(_strings(group.get("aliases"))),
                            "max_severity": group.get("max_severity"),
                        }
                    )
            else:
                for vulnerability in vulnerabilities:
                    if not isinstance(vulnerability, Mapping) or not isinstance(vulnerability.get("id"), str):
                        raise ValueError("OSV vulnerability must contain an id")
                    findings.append(
                        {
                            "ecosystem": ecosystem,
                            "package": name,
                            "version": version,
                            "ids": [vulnerability["id"]],
                            "aliases": list(_strings(vulnerability.get("aliases"))),
                            "max_severity": None,
                        }
                    )
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                cast(str, item["ecosystem"]),
                cast(str, item["package"]),
                cast(str, item["version"]),
                cast(list[str], item["ids"]),
            ),
        )
    )


def build_dependency_audit_evidence(
    *,
    subject_sha: str,
    lockfile: Path | None = None,
    lockfiles: tuple[Path, ...] | None = None,
    scanner: str,
    scanner_version: str,
    scan_time: str,
    workflow_run: str,
    workflow_url: str,
    scan_outcome: str,
    scan_result: Path,
) -> dict[str, object]:
    if _FULL_SHA.fullmatch(subject_sha) is None:
        raise ValueError("subject_sha must be a lowercase 40-character commit SHA")
    authorities = lockfiles if lockfiles is not None else (() if lockfile is None else (lockfile,))
    expected = {"uv.lock", "apps/onlyalpha-web/package-lock.json"}
    normalized = {_lock_authority(path) for path in authorities}
    if not authorities or any(not path.is_file() for path in authorities):
        raise ValueError("dependency audit authorities must be existing lockfiles")
    if len(authorities) == 1 and normalized != {"uv.lock"}:
        raise ValueError("single-lock compatibility mode requires uv.lock")
    if len(authorities) > 1 and normalized != expected:
        raise ValueError("dependency audit requires the exact Python and Web authoritative locks")
    if not scanner or not scanner_version:
        raise ValueError("scanner identity and version are required")

    findings: tuple[dict[str, object], ...] = ()
    result_digest: str | None = None
    result_error: str | None = None
    try:
        result_digest = _sha256(scan_result)
        raw = json.loads(scan_result.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("OSV result root must be an object")
        findings = _findings(cast(Mapping[str, object], raw))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result_error = str(exc)

    if findings:
        status = "VULNERABILITY_FOUND"
    elif scan_outcome == "success" and result_error is None:
        status = _SUCCESS
    else:
        status = "SCAN_INFRASTRUCTURE_FAILURE"

    evidence = {
        "schema_version": 1,
        "subject_sha": subject_sha,
        "audited_authorities": sorted(normalized),
        "lock_sha256": {_lock_authority(path): _sha256(path) for path in authorities},
        "scanner": scanner,
        "scanner_version": scanner_version,
        "scan_time": _scan_time(scan_time),
        "workflow_run": workflow_run,
        "workflow_url": workflow_url,
        "scan_outcome": scan_outcome,
        "scan_result_sha256": result_digest,
        "status": status,
        "findings": list(findings),
        "approved_exceptions": [],
        "result_error": result_error,
    }
    if len(authorities) == 1:
        evidence["audited_authority"] = "uv.lock"
        evidence["uv_lock_sha256"] = _sha256(authorities[0])
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-sha", required=True)
    parser.add_argument("--lockfile", type=Path, required=True, action="append")
    parser.add_argument("--scanner", required=True)
    parser.add_argument("--scanner-version", required=True)
    parser.add_argument("--scan-time", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-url", required=True)
    parser.add_argument("--scan-outcome", required=True)
    parser.add_argument("--scan-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = build_dependency_audit_evidence(
        subject_sha=args.subject_sha,
        lockfiles=tuple(args.lockfile),
        scanner=args.scanner,
        scanner_version=args.scanner_version,
        scan_time=args.scan_time,
        workflow_run=args.workflow_run,
        workflow_url=args.workflow_url,
        scan_outcome=args.scan_outcome,
        scan_result=args.scan_result,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["status"] == _SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
