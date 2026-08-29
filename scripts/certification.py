from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quality_policy import load_quality_policy  # noqa: E402

QUALITY_POLICY = load_quality_policy()
REQUIRED_GATES = QUALITY_POLICY.certification_required_gates
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def build_evidence(
    *,
    subject_sha: str,
    workflow_run: str,
    workflow_url: str,
    gate_values: Sequence[str],
) -> dict[str, object]:
    if _FULL_SHA.fullmatch(subject_sha) is None:
        raise ValueError("subject_sha must be a lowercase 40-character commit SHA")
    gates: dict[str, str] = {}
    for value in gate_values:
        name, separator, result = value.partition("=")
        if not separator or not name or not result:
            raise ValueError(f"invalid gate result: {value}")
        if name in gates:
            raise ValueError(f"duplicate gate result: {name}")
        gates[name] = result
    missing = REQUIRED_GATES - gates.keys()
    unexpected = gates.keys() - REQUIRED_GATES
    if missing or unexpected:
        raise ValueError(
            f"certification gate identity mismatch: missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    passed = all(gates[name] == "success" for name in REQUIRED_GATES)
    return {
        "schema_version": 2,
        "quality_policy_schema_version": QUALITY_POLICY.schema_version,
        "subject_sha": subject_sha,
        "workflow_run": workflow_run,
        "workflow_url": workflow_url,
        "required_gates": dict(sorted(gates.items())),
        "verdict": "ACCEPTED" if passed else "REJECTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-sha", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-url", required=True)
    parser.add_argument("--gate", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = build_evidence(
        subject_sha=args.subject_sha,
        workflow_run=args.workflow_run,
        workflow_url=args.workflow_url,
        gate_values=args.gate,
    )
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["verdict"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
