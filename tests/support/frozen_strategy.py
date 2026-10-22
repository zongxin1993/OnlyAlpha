"""Controlled immutable-history inputs for actual native startup tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

from onlyalpha.canonical import only_canonical_json
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.revision import OnlyStrategyRevision


def call(probe: Path, **options: object) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)], input=json.dumps({"op": "node-authority", **options}), text=True, capture_output=True, timeout=25
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def pair(root: Path, source: dict[str, Any]) -> tuple[str, str]:
    revision = OnlyStrategyRevision.from_dict(source)
    fingerprint = str(revision.strategy_fingerprint)
    relation = OnlyStrategyFreezeRelation(fingerprint, "a" * 64, "b" * 64, ("c" * 64, "d" * 64), "e" * 64, ("f" * 64,))
    for kind, identity, value in [
        (
            "frozen-revisions",
            fingerprint,
            {"schema_version": 1, "strategy_fingerprint": fingerprint, "revision": source},
        ),
        ("freeze-relations", relation.relation_fingerprint, relation.to_dict()),
    ]:
        target = root / "strategy" / kind / "sha256" / identity[:2] / identity
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(only_canonical_json(value))
    return fingerprint, relation.relation_fingerprint
