from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine.models import OnlyEngineRunResult

ROOT = Path(__file__).resolve().parents[2]
RESULT_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "results"


@dataclass(frozen=True, slots=True)
class OnlyEngineTestResultFixture:
    fixture_id: str
    result: OnlyEngineRunResult
    canonical_projection: Mapping[str, object]
    result_fingerprint: str
    expected_trade_count: int
    expected_fill_count: int
    expected_terminal_count: int
    source_manifest: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class OnlyEngineArtifactFixture:
    result_fixture: OnlyEngineTestResultFixture
    output_directory: Path


def load_engine_result_fixture(fixture_id: str) -> OnlyEngineTestResultFixture:
    directory = RESULT_FIXTURE_ROOT / fixture_id
    manifest = _object(directory / "manifest.json")
    raw_result = _object(directory / "result.json")
    projection = _object(directory / "canonical_projection.json")
    cluster_results = raw_result.get("cluster_results")
    failures = raw_result.get("failures")
    if not isinstance(cluster_results, list) or any(not isinstance(item, dict) for item in cluster_results):
        raise ValueError(f"invalid result fixture cluster_results: {fixture_id}")
    if not isinstance(failures, list) or any(not isinstance(item, str) for item in failures):
        raise ValueError(f"invalid result fixture failures: {fixture_id}")
    result = OnlyEngineRunResult(
        engine_id=OnlyEngineId(str(raw_result["engine_id"])),
        run_id=str(raw_result["run_id"]),
        status=str(raw_result["status"]),
        cluster_results=tuple(cluster_results),
        failures=tuple(failures),
        manifest_path=None,
        determinism_fingerprint=str(raw_result["determinism_fingerprint"]),
        backtest_reports=tuple(_dicts(raw_result.get("backtest_reports", []), "backtest_reports")),
    )
    return OnlyEngineTestResultFixture(
        fixture_id,
        result,
        _freeze_mapping(projection),
        str(manifest["result_fingerprint"]),
        int(str(manifest["expected_trade_count"])),
        int(str(manifest["expected_fill_count"])),
        int(str(manifest["expected_terminal_count"])),
        _freeze_mapping(manifest),
    )


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fixture file must contain an object: {path}")
    return value


def _dicts(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"invalid result fixture {field}")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: dict[str, object]) -> Mapping[str, object]:
    frozen = _freeze(value)
    if not isinstance(frozen, Mapping):
        raise TypeError("canonical fixture projection must remain a mapping")
    return frozen


__all__ = [
    "OnlyEngineArtifactFixture",
    "OnlyEngineTestResultFixture",
    "RESULT_FIXTURE_ROOT",
    "load_engine_result_fixture",
]
