from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from tests.support.golden_data import (
    OnlyMiniQmtGoldenDataSourceFactory,
    load_miniqmt_golden_dataset,
    miniqmt_golden_content_fingerprint,
)

pytestmark = [pytest.mark.conformance, pytest.mark.miniqmt]

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "tests" / "fixtures" / "miniqmt" / "cn_a_share_v1"
BASE_CONFIG = ROOT / "tests" / "fixtures" / "legacy_macd" / "cluster_fast.json"


def _config() -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load(BASE_CONFIG)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["market"] = {"profile": "CN_A_SHARE_CASH"}
    payload["runtime"]["start_time"] = "2025-01-02T01:30:00Z"
    payload["runtime"]["end_time"] = "2025-01-13T01:30:00Z"
    instrument = payload["reference_data"]["instruments"][0]
    instrument.update(
        {
            "instrument_id": "600000.XSHG",
            "asset_class": "EQUITY",
            "board": "MAIN",
            "st_status": False,
            "price_precision": 2,
            "price_increment": "0.01",
            "quantity_increment": "100",
            "lot_size": "100",
            "minimum_quantity": "100",
        }
    )
    payload["universes"][0]["instruments"] = ["600000.XSHG"]
    payload["data_sources"] = [
        {
            "source_id": "miniqmt-golden",
            "plugin": "miniqmt-golden",
            "data_version": "miniqmt-cn-a-share-v1",
            "batch_size": 16,
            "coverage": {"universe_ids": ["macd-demo-universe"]},
            "extensions": {"dataset_path": str(DATASET)},
        }
    ]
    payload["strategy"]["extensions"]["instrument_id"] = "600000.XSHG"
    payload["strategy"]["extensions"]["trade_quantity"] = "100"
    subscription = payload["factors"][0]["subscriptions"]["instrument_bars"][0]
    subscription["instrument_id"] = "600000.XSHG"
    subscription["bar_specification"]["step"] = 1440
    return OnlyClusterRunConfig.from_mapping(payload, source_path=BASE_CONFIG)


def _services() -> OnlyEngineServices:
    services = only_default_engine_services()
    services.data_sources.register(
        OnlyMiniQmtGoldenDataSourceFactory(),
        origin=OnlyPluginOrigin(OnlyPluginOriginType.TEST, "tests.support.golden_data"),
    )
    return services


def _run(target: Path):  # type: ignore[no-untyped-def]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("miniqmt-golden-smoke"), target), services=_services())
    engine.add_cluster(_config())
    return engine.run()


def test_miniqmt_golden_manifest_and_bar_contract() -> None:
    dataset = load_miniqmt_golden_dataset(DATASET)
    manifest = dataset.manifest.values

    assert manifest["provider"] == "MiniQMT"
    assert manifest["instrument_ids"] == ["600000.XSHG"]
    assert manifest["bar_types"] == ["1d"]
    assert manifest["record_count"] == len(dataset.updates) == 7
    assert manifest["available_resources"] == ["bars"]
    assert manifest["missing_resources"] == [
        "historical_st_status",
        "historical_suspension",
        "effective_reference",
    ]
    events = tuple(item.ts_event for item in dataset.updates)
    assert events == tuple(sorted(events))
    assert len(set(events)) == len(events)
    assert all(str(item.instrument_id) == "600000.XSHG" for item in dataset.updates)
    assert [item.source_sequence.value for item in dataset.updates] == list(range(1, 8))
    for update in dataset.updates:
        bar = update.payload.bar  # type: ignore[union-attr]
        assert bar.high.value >= max(bar.open.value, bar.low.value, bar.close.value)
        assert bar.low.value <= min(bar.open.value, bar.high.value, bar.close.value)


def test_capture_timestamp_is_not_part_of_content_fingerprint() -> None:
    raw = json.loads((DATASET / "capture_manifest.json").read_text(encoding="utf-8"))
    raw["capture_timestamp"] = "2099-01-01T00:00:00Z"
    assert miniqmt_golden_content_fingerprint(raw) == raw["content_fingerprint"]


def test_miniqmt_golden_tampering_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "dataset"
    shutil.copytree(DATASET, copied)
    bars = copied / "bars.parquet"
    payload = bytearray(bars.read_bytes())
    payload[-1] ^= 0x01
    bars.write_bytes(payload)

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        load_miniqmt_golden_dataset(copied)


def test_miniqmt_golden_runs_through_engine_and_virtual_broker(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.status == "COMPLETED", result.failures
    assert result.cluster_results[0]["data"]["processed_bar_count"] == 7  # type: ignore[index]
    assert result.runtime_results[0].result_fingerprint  # type: ignore[attr-defined]


def test_miniqmt_golden_engine_result_is_deterministic(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")

    assert first.status == second.status == "COMPLETED"
    assert first.determinism_fingerprint == second.determinism_fingerprint
    assert first.runtime_results[0].result_fingerprint == second.runtime_results[0].result_fingerprint  # type: ignore[attr-defined]
