"""Independent frozen-history documents for the native transport probes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def call(probe: Path, **options: object) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)], input=json.dumps({"op": "node-authority", **options}), text=True, capture_output=True, timeout=25
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def pair(root: Path, source: dict[str, Any]) -> tuple[str, str]:
    # The exact strategy identity is part of the independent source vector.
    identity = cast(str, source["strategy_fingerprint"])
    assert len(identity) == 64 and all(char in "0123456789abcdef" for char in identity)
    relation = {
        "schema_version": 1,
        "strategy_fingerprint": identity,
        "candidate_fingerprint": "a" * 64,
        "research_result_fingerprint": "b" * 64,
        "research_execution_evidence_fingerprints": ["c" * 64, "d" * 64],
        "admission_evidence_fingerprint": "e" * 64,
        "equivalence_evidence_fingerprints": ["f" * 64],
    }
    fingerprint = hashlib.sha256(
        canonical_json({**relation, "domain": "onlyalpha.strategy.freeze-relation"}).encode()
    ).hexdigest()
    for tree, key, value in (
        ("frozen-revisions", identity, {"schema_version": 1, "strategy_fingerprint": identity, "revision": source}),
        ("freeze-relations", fingerprint, {**relation, "relation_fingerprint": fingerprint}),
    ):
        directory = root / "strategy" / tree / "sha256" / key[:2] / key
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.json").write_text(canonical_json(value), encoding="utf-8")
    return identity, fingerprint
