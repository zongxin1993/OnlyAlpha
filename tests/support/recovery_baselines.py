from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from onlyalpha.result import only_backtest_business_projection
from tests.support.canonical import canonical_value
from tests.support.sqlite_templates import materialize_sqlite_archive

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "recovery"
RECOVERY_CACHE_ROOT = ROOT / ".test-cache" / "recovery"


class OnlyRecoveryResultView(Protocol):
    @property
    def result_fingerprint(self) -> str: ...


@dataclass(frozen=True, slots=True)
class OnlyRecoveryBaseline:
    baseline_id: str
    database_template: Path
    checkpoint_id: str
    canonical_projection: Mapping[str, object]
    result_fingerprint: str
    manifest: Mapping[str, object]


def load_recovery_baseline(baseline_id: str) -> OnlyRecoveryBaseline:
    directory = RECOVERY_FIXTURE_ROOT / baseline_id
    manifest = _object(directory / "manifest.json")
    projection = _object(directory / "canonical_projection.json")
    template_name = str(manifest["database_template"])
    template = RECOVERY_CACHE_ROOT / template_name
    cache_hit = template.is_file()
    if not cache_hit:
        materialize_sqlite_archive(
            directory / str(manifest["database_archive"]),
            template,
            str(manifest["database_fingerprint"]),
        )
    if cache_hit:
        try:
            from scripts.pytest_metrics import record_metric_counter

            record_metric_counter("cache_hit_count")
        except ImportError:
            pass
    return OnlyRecoveryBaseline(
        baseline_id,
        template,
        str(manifest["checkpoint_id"]),
        _freeze_mapping(projection),
        str(manifest["result_fingerprint"]),
        _freeze_mapping(manifest),
    )


def assert_recovery_equivalent(baseline: OnlyRecoveryBaseline, recovered: OnlyRecoveryResultView) -> None:
    """Compare the complete stable business Projection, not only cash/position totals."""

    actual = canonical_value(only_backtest_business_projection(recovered))
    expected = _thaw(baseline.canonical_projection)
    assert recovered.result_fingerprint == baseline.result_fingerprint
    assert actual == expected


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Recovery fixture must contain an object: {path}")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: dict[str, object]) -> Mapping[str, object]:
    result = _freeze(value)
    if not isinstance(result, Mapping):
        raise TypeError("Recovery projection must remain a mapping")
    return result


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


__all__ = [
    "OnlyRecoveryBaseline",
    "assert_recovery_equivalent",
    "load_recovery_baseline",
]
