from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
QUALITY_POLICY_PATH = ROOT / "quality-policy.toml"


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    schema_version: int
    coverage_mode: str
    quality_required_gates: frozenset[str]
    quality_event_lane_gates: frozenset[str]


def _require_table(document: dict[str, object], name: str) -> dict[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"quality policy {name} must be a table")
    return cast(dict[str, object], value)


def _require_gate_set(table: dict[str, object], name: str) -> frozenset[str]:
    value = table.get(name)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"quality policy {name} must be a non-empty string array")
    gates = frozenset(str(item) for item in value)
    if len(gates) != len(value):
        raise ValueError(f"quality policy {name} contains duplicate gates")
    return gates


def load_quality_policy(path: Path = QUALITY_POLICY_PATH) -> QualityPolicy:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    configured_schema_version = document.get("schema_version")
    if configured_schema_version != 3:
        raise ValueError(f"unsupported quality policy schema_version: {configured_schema_version!r}")

    configured_coverage_mode = document.get("coverage_mode")
    if configured_coverage_mode != "manual":
        raise ValueError(f"unsupported quality policy coverage_mode: {configured_coverage_mode!r}")

    quality = _require_table(document, "quality")
    quality_required = _require_gate_set(quality, "required_gates")
    event_lanes = _require_gate_set(quality, "event_lane_gates")
    if quality_required & event_lanes:
        raise ValueError("quality required gates and event lane gates must be disjoint")
    if "coverage" in quality_required:
        raise ValueError("manual coverage cannot be a mandatory workflow gate")

    unexpected_tables = set(document) - {"schema_version", "coverage_mode", "quality"}
    if unexpected_tables:
        names = ", ".join(sorted(unexpected_tables))
        raise ValueError(f"quality policy contains unsupported top-level entries: {names}")

    return QualityPolicy(
        schema_version=3,
        coverage_mode="manual",
        quality_required_gates=quality_required,
        quality_event_lane_gates=event_lanes,
    )
