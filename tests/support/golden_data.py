from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq

from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.plugin.capabilities import (
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.scenario.data_source import OnlyScenarioHistoricalDataSource

DATASET_SCHEMA_VERSION = 1

REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "dataset_id",
        "dataset_schema_version",
        "provider",
        "plugin_version",
        "xtquant_version",
        "capture_timestamp",
        "instrument_ids",
        "bar_types",
        "start",
        "end",
        "timezone",
        "adjustment",
        "data_version",
        "content_fingerprint",
        "file_fingerprints",
        "available_resources",
        "missing_resources",
    }
)

GOLDEN_DESCRIPTOR = OnlyPluginDescriptor(
    "miniqmt-golden",
    OnlyPluginType.DATA_SOURCE,
    "1.0.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "MiniQMT Frozen Golden Data",
    "OnlyAlpha Tests",
    OnlyDataSourceCapabilities(
        historical_bars=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
    ),
)


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtGoldenManifest:
    values: Mapping[str, object]

    @property
    def content_fingerprint(self) -> str:
        return str(self.values["content_fingerprint"])


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtGoldenDataset:
    root: Path
    manifest: OnlyMiniQmtGoldenManifest
    updates: tuple[OnlyMarketDataInboundUpdate, ...]


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtGoldenConfig:
    dataset_path: str


def load_miniqmt_golden_dataset(root: Path) -> OnlyMiniQmtGoldenDataset:
    manifest_path = root / "capture_manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("MiniQMT Golden manifest must be an object")
    missing = REQUIRED_MANIFEST_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"MiniQMT Golden manifest missing fields: {sorted(missing)}")
    if raw["dataset_schema_version"] != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported MiniQMT Golden dataset schema")
    if raw["provider"] != "MiniQMT" or raw["available_resources"] != ["bars"]:
        raise ValueError("invalid MiniQMT Golden provider/resources")
    fingerprints = raw["file_fingerprints"]
    if not isinstance(fingerprints, dict) or set(fingerprints) != {"bars.parquet"}:
        raise ValueError("MiniQMT Golden file_fingerprints must contain bars.parquet")
    bars = root / "bars.parquet"
    if _file_sha256(bars) != fingerprints["bars.parquet"]:
        raise ValueError("MiniQMT Golden bars.parquet fingerprint mismatch")
    if miniqmt_golden_content_fingerprint(raw) != raw["content_fingerprint"]:
        raise ValueError("MiniQMT Golden content fingerprint mismatch")
    table = pq.read_table(bars, columns=["update_json"])
    updates = tuple(
        OnlyMarketDataInboundUpdate.from_dict(json.loads(str(row["update_json"]))) for row in table.to_pylist()
    )
    return OnlyMiniQmtGoldenDataset(root, OnlyMiniQmtGoldenManifest(raw), updates)


class OnlyMiniQmtGoldenDataSourceFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return GOLDEN_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyMiniQmtGoldenConfig:
        value = extensions.get("dataset_path")
        if not isinstance(value, str) or not value:
            raise ValueError("miniqmt-golden requires extensions.dataset_path")
        return OnlyMiniQmtGoldenConfig(value)

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        config = request.plugin_config
        if not isinstance(config, OnlyMiniQmtGoldenConfig):
            return (OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid MiniQMT Golden config"),)
        path = (request.config_directory / config.dataset_path).resolve()
        return (
            ()
            if (path / "capture_manifest.json").is_file() and (path / "bars.parquet").is_file()
            else (OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "MiniQMT Golden dataset is incomplete"),)
        )

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyDataSource:
        config = request.plugin_config
        if not isinstance(config, OnlyMiniQmtGoldenConfig):
            raise TypeError("MiniQMT Golden Factory requires OnlyMiniQmtGoldenConfig")
        dataset = load_miniqmt_golden_dataset((request.config_directory / config.dataset_path).resolve())
        if any(item.source_id != request.source_id for item in dataset.updates):
            raise ValueError("MiniQMT Golden source_id does not match runtime configuration")
        if any(item.data_version != request.data_version for item in dataset.updates):
            raise ValueError("MiniQMT Golden data_version does not match runtime configuration")
        updates = tuple(replace(item, runtime_id=request.runtime_id) for item in dataset.updates)
        return cast(OnlyDataSource, OnlyScenarioHistoricalDataSource(request, updates))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def miniqmt_golden_content_fingerprint(manifest: Mapping[str, object]) -> str:
    excluded = {"capture_timestamp", "content_fingerprint"}
    payload = {key: value for key, value in manifest.items() if key not in excluded}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "OnlyMiniQmtGoldenDataSourceFactory",
    "OnlyMiniQmtGoldenDataset",
    "OnlyMiniQmtGoldenManifest",
    "load_miniqmt_golden_dataset",
    "miniqmt_golden_content_fingerprint",
]
