"""Atomic, versioned Parquet storage for normalized historical Bars."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.cache.historical.fingerprint import only_cache_key_payload, only_content_fingerprint
from onlyalpha.cache.historical.models import (
    OnlyCacheInspection,
    OnlyCacheManifest,
    OnlyCacheWriteResult,
    OnlyHistoricalCacheKey,
    OnlyHistoricalTradeCacheKey,
    OnlyTypedHistoricalCacheKey,
)
from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges, only_missing_ranges
from onlyalpha.data.historical import (
    OnlyDataQualityIssue,
    OnlyDataQualitySeverity,
    OnlyHistoricalFetchResult,
    OnlyHistoricalTradeFetchResult,
)
from onlyalpha.domain.market import OnlyBar, OnlyTradeTick


class OnlyParquetHistoricalCacheStore:
    """Year-partitioned store whose manifest and files are replaced atomically."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def inspect(self, key: OnlyTypedHistoricalCacheKey, requested_range: OnlyTimeRange) -> OnlyCacheInspection:
        manifest_path = self._manifest_path(key)
        if not manifest_path.exists():
            if self._key_root(key).exists():
                issue = OnlyDataQualityIssue(
                    "MANIFEST_MISSING",
                    OnlyDataQualitySeverity.ERROR,
                    "cache files exist without a manifest",
                    key.instrument_id,
                )
                self._quarantine(key, issue.message)
                return OnlyCacheInspection(True, False, key, (), (), (requested_range,), None, (issue,))
            return OnlyCacheInspection(False, False, key, (), (), (requested_range,), None)
        try:
            manifest = self._load_manifest(key)
            if manifest.key != key:
                raise ValueError("manifest key mismatch")
            for relative, expected in manifest.partition_hashes.items():
                path = self._key_root(key) / relative
                if not path.is_file() or self._hash(path) != expected:
                    raise ValueError(f"partition hash mismatch: {relative}")
                pq.read_metadata(path)
            missing = only_missing_ranges(requested_range, manifest.resolved_ranges)
            return OnlyCacheInspection(
                True, not missing, key, manifest.resolved_ranges, manifest.observed_ranges, missing, manifest
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError, pa.ArrowException) as exc:
            issue = OnlyDataQualityIssue("CORRUPT_CACHE", OnlyDataQualitySeverity.ERROR, str(exc), key.instrument_id)
            self._quarantine(key, str(exc))
            return OnlyCacheInspection(True, False, key, (), (), (requested_range,), None, (issue,))

    def read(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange) -> tuple[OnlyBar, ...]:
        manifest = self._load_manifest(key)
        records: list[OnlyBar] = []
        for relative in sorted(manifest.partition_hashes):
            table = pq.read_table(self._key_root(key) / relative, columns=["event_time_ns", "bar_json"])
            for event_ns, payload in zip(
                table["event_time_ns"].to_pylist(), table["bar_json"].to_pylist(), strict=True
            ):
                bar = OnlyBar.from_json(payload)
                timestamp = (
                    bar.bar_start
                    if key.timestamp_semantics.value == "bar_open"
                    else datetime.fromtimestamp(event_ns / 1_000_000_000, UTC)
                )
                if time_range.contains(timestamp):
                    records.append(bar)
        return tuple(sorted(records, key=lambda item: (item.ts_event, item.to_json())))

    def write(self, key: OnlyHistoricalCacheKey, result: OnlyHistoricalFetchResult) -> OnlyCacheWriteResult:
        root = self._key_root(key)
        root.mkdir(parents=True, exist_ok=True)
        existing: list[OnlyBar] = []
        old_manifest: OnlyCacheManifest | None = None
        if self._manifest_path(key).exists():
            old_manifest = self._load_manifest(key)
            for covered in old_manifest.observed_ranges:
                existing.extend(self.read(key, covered))
        merged = {bar.ts_event: bar for bar in existing}
        merged.update({bar.ts_event: bar for bar in result.records})
        records = tuple(sorted(merged.values(), key=lambda item: (item.ts_event, item.to_json())))
        by_year: dict[int, list[OnlyBar]] = {}
        for bar in records:
            by_year.setdefault(bar.ts_event.year, []).append(bar)
        token = uuid.uuid4().hex
        stage = root.parent / f".stage-{token}"
        backup = root.parent / f".backup-{token}"
        stage.mkdir()
        hashes: dict[str, str] = {}
        try:
            for year, bars in sorted(by_year.items()):
                relative = f"bars/{year}.parquet"
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                table = pa.table(
                    {
                        "schema_version": pa.array([key.schema_version] * len(bars), type=pa.int16()),
                        "event_time_ns": pa.array(
                            [int(item.ts_event.timestamp() * 1_000_000_000) for item in bars], type=pa.int64()
                        ),
                        "bar_json": pa.array([item.to_json() for item in bars], type=pa.string()),
                    }
                )
                pq.write_table(table, target, compression="zstd")
                pq.read_table(target)
                hashes[relative] = self._hash(target)
            resolved = only_merge_ranges(
                (*(old_manifest.resolved_ranges if old_manifest else ()), *result.resolved_ranges)
            )
            observed = only_merge_ranges(
                (*(old_manifest.observed_ranges if old_manifest else ()), *result.observed_ranges)
            )
            audit_time = old_manifest.updated_at if old_manifest else datetime(1970, 1, 1, tzinfo=UTC)
            manifest = OnlyCacheManifest(
                key,
                resolved,
                observed,
                len(records),
                hashes,
                only_content_fingerprint(key, hashes),
                key.schema_version,
                key.time_semantics_version,
                old_manifest.created_at if old_manifest else audit_time,
                audit_time,
                result.source_metadata,
            )
            manifest_temp = stage / "manifest.json"
            manifest_temp.write_text(self._dump_manifest(manifest), encoding="utf-8")
            if root.exists():
                os.replace(root, backup)
            os.replace(stage, root)
            shutil.rmtree(backup, ignore_errors=True)
            return OnlyCacheWriteResult(manifest, len(hashes))
        except Exception:
            if backup.exists():
                if root.exists():
                    shutil.rmtree(root)
                os.replace(backup, root)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def read_trades(self, key: OnlyHistoricalTradeCacheKey, time_range: OnlyTimeRange) -> tuple[OnlyTradeTick, ...]:
        manifest = self._load_manifest(key)
        records: list[OnlyTradeTick] = []
        for relative in sorted(manifest.partition_hashes):
            table = pq.read_table(self._key_root(key) / relative, columns=["trade_json"])
            for payload in table["trade_json"].to_pylist():
                trade = OnlyTradeTick.from_json(payload)
                if time_range.contains(trade.ts_event):
                    records.append(trade)
        return tuple(sorted(records, key=lambda item: (item.ts_event, str(item.trade_id))))

    def write_trades(
        self, key: OnlyHistoricalTradeCacheKey, result: OnlyHistoricalTradeFetchResult
    ) -> OnlyCacheWriteResult:
        root = self._key_root(key)
        root.mkdir(parents=True, exist_ok=True)
        existing: list[OnlyTradeTick] = []
        old_manifest: OnlyCacheManifest | None = None
        if self._manifest_path(key).exists():
            old_manifest = self._load_manifest(key)
            for covered in old_manifest.observed_ranges:
                existing.extend(self.read_trades(key, covered))
        merged = {str(trade.trade_id): trade for trade in existing}
        for trade in result.records:
            identity = str(trade.trade_id)
            previous = merged.get(identity)
            if previous is not None and previous != trade:
                raise ValueError("conflicting historical Trade identity")
            merged[identity] = trade
        records = tuple(sorted(merged.values(), key=lambda item: (item.ts_event, str(item.trade_id))))
        by_month: dict[str, list[OnlyTradeTick]] = {}
        for trade in records:
            by_month.setdefault(trade.ts_event.strftime("%Y-%m"), []).append(trade)
        token = uuid.uuid4().hex
        stage = root.parent / f".stage-{token}"
        backup = root.parent / f".backup-{token}"
        stage.mkdir()
        hashes: dict[str, str] = {}
        try:
            for month, trades in sorted(by_month.items()):
                relative = f"trades/{month}.parquet"
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                table = pa.table(
                    {
                        "schema_version": pa.array([key.schema_version] * len(trades), type=pa.int16()),
                        "event_time_ns": pa.array(
                            [int(item.ts_event.timestamp() * 1_000_000_000) for item in trades],
                            type=pa.int64(),
                        ),
                        "trade_json": pa.array([item.to_json() for item in trades], type=pa.string()),
                    }
                )
                pq.write_table(table, target, compression="zstd")
                pq.read_table(target)
                hashes[relative] = self._hash(target)
            resolved = only_merge_ranges(
                (*(old_manifest.resolved_ranges if old_manifest else ()), *result.resolved_ranges)
            )
            observed = only_merge_ranges(
                (*(old_manifest.observed_ranges if old_manifest else ()), *result.observed_ranges)
            )
            audit_time = old_manifest.updated_at if old_manifest else datetime(1970, 1, 1, tzinfo=UTC)
            manifest = OnlyCacheManifest(
                key,
                resolved,
                observed,
                len(records),
                hashes,
                only_content_fingerprint(key, hashes),
                key.schema_version,
                key.time_semantics_version,
                old_manifest.created_at if old_manifest else audit_time,
                audit_time,
                result.source_metadata,
            )
            (stage / "manifest.json").write_text(self._dump_manifest(manifest), encoding="utf-8")
            if root.exists():
                os.replace(root, backup)
            os.replace(stage, root)
            shutil.rmtree(backup, ignore_errors=True)
            return OnlyCacheWriteResult(manifest, len(hashes))
        except Exception:
            if backup.exists():
                if root.exists():
                    shutil.rmtree(root)
                os.replace(backup, root)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def manifest(self, key: OnlyTypedHistoricalCacheKey) -> OnlyCacheManifest:
        return self._load_manifest(key)

    def invalidate(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange | None = None) -> None:
        if time_range is not None:
            raise NotImplementedError("partial invalidation is intentionally not exposed in the first version")
        if self._key_root(key).exists():
            self._quarantine(key, "invalidated")

    def _key_root(self, key: OnlyTypedHistoricalCacheKey) -> Path:
        digest = hashlib.sha256(json.dumps(only_cache_key_payload(key), sort_keys=True).encode()).hexdigest()[:24]
        return self._root / key.source_id / f"v{key.schema_version}" / key.dataset_type / digest

    def _manifest_path(self, key: OnlyTypedHistoricalCacheKey) -> Path:
        return self._key_root(key) / "manifest.json"

    def _load_manifest(self, key: OnlyTypedHistoricalCacheKey) -> OnlyCacheManifest:
        raw = json.loads(self._manifest_path(key).read_text(encoding="utf-8"))
        if (
            raw.get("schema_version") != key.schema_version
            or raw.get("time_semantics_version") != key.time_semantics_version
        ):
            raise ValueError("unsupported cache manifest version")
        if raw.get("key") != only_cache_key_payload(key):
            raise ValueError("cache manifest key mismatch")
        manifest = OnlyCacheManifest(
            key,
            tuple(
                OnlyTimeRange(datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"]))
                for item in raw["resolved_ranges"]
            ),
            tuple(
                OnlyTimeRange(datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"]))
                for item in raw["observed_ranges"]
            ),
            int(raw["row_count"]),
            dict(raw["partition_hashes"]),
            str(raw["content_fingerprint"]),
            int(raw["schema_version"]),
            int(raw["time_semantics_version"]),
            datetime.fromisoformat(raw["created_at"]),
            datetime.fromisoformat(raw["updated_at"]),
            dict(raw["metadata"]),
        )
        if manifest.content_fingerprint != only_content_fingerprint(key, dict(manifest.partition_hashes)):
            raise ValueError("cache manifest content fingerprint mismatch")
        return manifest

    @staticmethod
    def _dump_manifest(value: OnlyCacheManifest) -> str:
        payload = {
            "key": only_cache_key_payload(value.key),
            "resolved_ranges": [
                {"start": item.start.isoformat(), "end": item.end.isoformat()} for item in value.resolved_ranges
            ],
            "observed_ranges": [
                {"start": item.start.isoformat(), "end": item.end.isoformat()} for item in value.observed_ranges
            ],
            "row_count": value.row_count,
            "partition_hashes": dict(value.partition_hashes),
            "content_fingerprint": value.content_fingerprint,
            "schema_version": value.schema_version,
            "time_semantics_version": value.time_semantics_version,
            "created_at": value.created_at.isoformat(),
            "updated_at": value.updated_at.isoformat(),
            "metadata": dict(value.metadata),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _quarantine(self, key: OnlyTypedHistoricalCacheKey, reason: str) -> None:
        source = self._key_root(key)
        if not source.exists():
            return
        destination = self._root / "quarantine" / f"{source.name}-{uuid.uuid4().hex}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
        (destination / "reason.txt").write_text(reason, encoding="utf-8")
