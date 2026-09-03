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
    strategy_fingerprints: tuple[str, ...]
    manifest: Mapping[str, object]


def load_recovery_baseline(baseline_id: str) -> OnlyRecoveryBaseline:
    directory = RECOVERY_FIXTURE_ROOT / baseline_id
    manifest = _object(directory / "manifest.json")
    strategy_fingerprints = _validate_recovery_manifest(manifest, baseline_id)
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
        strategy_fingerprints,
        _freeze_mapping(manifest),
    )


def assert_recovery_baseline_compatible(
    baseline: OnlyRecoveryBaseline,
    current_strategy_fingerprints: tuple[str, ...] | list[str],
) -> None:
    """Fail before Engine execution when a current scenario no longer matches its Golden."""

    current = tuple(sorted(set(current_strategy_fingerprints)))
    if any(not _is_sha256(value) for value in current):
        raise ValueError("current Recovery scenario contains a malformed Strategy fingerprint")
    if current != baseline.strategy_fingerprints:
        raise AssertionError(
            "RECOVERY_BASELINE_STRATEGY_IDENTITY_MISMATCH\n"
            f"baseline: {list(baseline.strategy_fingerprints)}\n"
            f"current: {list(current)}\n"
            "Regenerate using: uv run python scripts/regenerate_recovery_baselines.py "
            f"--baseline {baseline.baseline_id}"
        )


def assert_recovery_equivalent(baseline: OnlyRecoveryBaseline, recovered: OnlyRecoveryResultView) -> None:
    """Compare the complete stable business Projection, not only cash/position totals."""

    actual = canonical_value(only_backtest_business_projection(recovered))
    expected = _thaw(baseline.canonical_projection)
    assert actual == expected, _first_difference(actual, expected)
    assert recovered.result_fingerprint == baseline.result_fingerprint


def _first_difference(actual: object, expected: object, path: str = "root") -> str:
    if type(actual) is not type(expected):
        return f"{path}: type {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(actual, dict) and isinstance(expected, dict):
        if actual.keys() != expected.keys():
            return f"{path}: keys {actual.keys() ^ expected.keys()}"
        for key in actual:
            if actual[key] != expected[key]:
                return _first_difference(actual[key], expected[key], f"{path}.{key}")
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            if left != right:
                return _first_difference(left, right, f"{path}[{index}]")
    return f"{path}: {actual!r} != {expected!r}"


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Recovery fixture must contain an object: {path}")
    return value


def _validate_recovery_manifest(manifest: Mapping[str, object], baseline_id: str) -> tuple[str, ...]:
    if manifest.get("baseline_schema_version") != 2:
        raise ValueError("unsupported Recovery baseline schema")
    if manifest.get("baseline_id") != baseline_id:
        raise ValueError("Recovery baseline identity differs from its directory")
    raw = manifest.get("strategy_fingerprints")
    if not isinstance(raw, list) or not raw or any(not isinstance(value, str) for value in raw):
        raise ValueError("Recovery baseline strategy_fingerprints must be a non-empty list")
    result = tuple(raw)
    if any(not _is_sha256(value) for value in result):
        raise ValueError("Recovery baseline contains a malformed Strategy fingerprint")
    if result != tuple(sorted(result)):
        raise ValueError("Recovery baseline strategy_fingerprints are not canonically ordered")
    if len(result) != len(set(result)):
        raise ValueError("Recovery baseline strategy_fingerprints contain duplicates")
    return result


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


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
    "assert_recovery_baseline_compatible",
    "assert_recovery_equivalent",
    "load_recovery_baseline",
]
