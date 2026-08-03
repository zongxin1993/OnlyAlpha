from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, date, datetime, time, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha_plugin_miniqmt.data_source.historical import PERIODS, load_bars  # noqa: E402
from onlyalpha_plugin_miniqmt.descriptor import DATA_DESCRIPTOR  # noqa: E402
from onlyalpha_plugin_miniqmt.sdk.loader import load_xtquant  # noqa: E402

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId  # noqa: E402
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange  # noqa: E402
from onlyalpha.data.sources import OnlyParquetHistoricalDataSource  # noqa: E402
from onlyalpha.domain.enums import (  # noqa: E402
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId  # noqa: E402
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType  # noqa: E402

DATASET_SCHEMA_VERSION = 1
DATA_VERSION = "miniqmt-cn-a-share-v1"
MISSING_RESOURCES = (
    "historical_st_status",
    "historical_suspension",
    "effective_reference",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def content_fingerprint(manifest: dict[str, object]) -> str:
    excluded = {"capture_timestamp", "content_fingerprint"}
    payload = {key: value for key, value in manifest.items() if key not in excluded}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _xtquant_version() -> str:
    for distribution in ("xtquant", "xtquant-python"):
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    package = load_xtquant().package
    return str(getattr(package, "__version__", "unknown"))


def _bar_minutes(value: str) -> int:
    normalized = value.lower()
    for minutes, period in PERIODS.items():
        if period == normalized:
            return minutes
    raise ValueError(f"unsupported MiniQMT bar type: {value}")


def capture(args: argparse.Namespace) -> None:
    userdata = Path(args.userdata_mini).expanduser().resolve()
    if not userdata.is_dir():
        raise FileNotFoundError(f"userdata_mini does not exist: {userdata}")
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.force:
        raise FileExistsError(f"output exists; pass --force to replace it: {output}")
    instrument = OnlyInstrumentId.parse(args.instrument)
    minutes = _bar_minutes(args.bar)
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(minutes, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    start_day = date.fromisoformat(args.start)
    end_day = date.fromisoformat(args.end)
    if end_day < start_day:
        raise ValueError("end must not precede start")
    start = datetime.combine(start_day, time.min, shanghai).astimezone(UTC)
    end = datetime.combine(end_day + timedelta(days=1), time.min, shanghai).astimezone(UTC)
    request = OnlyHistoricalBarRequest(
        "capture-miniqmt-golden",
        frozenset({instrument}),
        frozenset({bar_type}),
        OnlyHistoricalDataRange(start, end),
        OnlyDataVersion(DATA_VERSION),
    )
    create_request = SimpleNamespace(
        runtime_id=OnlyRuntimeId("capture-miniqmt-golden"),
        source_id=OnlyMarketDataSourceId("miniqmt-golden"),
    )
    sdk = load_xtquant()
    if hasattr(sdk.xtdata, "enable_hello"):
        sdk.xtdata.enable_hello = False
    records = load_bars(sdk.xtdata, create_request, request)
    if not records:
        raise RuntimeError("MiniQMT returned no bars for the requested range")
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    bars_path = staging / "bars.parquet"
    OnlyParquetHistoricalDataSource.write(bars_path, records)
    manifest: dict[str, object] = {
        "dataset_id": output.name,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "provider": "MiniQMT",
        "plugin_version": DATA_DESCRIPTOR.plugin_version,
        "xtquant_version": _xtquant_version(),
        "capture_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "instrument_ids": [str(instrument)],
        "bar_types": [args.bar.lower()],
        "start": args.start,
        "end": args.end,
        "timezone": "Asia/Shanghai",
        "adjustment": args.adjustment,
        "data_version": DATA_VERSION,
        "file_fingerprints": {"bars.parquet": file_sha256(bars_path)},
        "available_resources": ["bars"],
        "missing_resources": list(MISSING_RESOURCES),
        "record_count": len(records),
    }
    manifest["content_fingerprint"] = content_fingerprint(manifest)
    (staging / "capture_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if output.exists():
        shutil.rmtree(output)
    staging.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a read-only MiniQMT Golden Dataset")
    parser.add_argument("--userdata-mini", required=True)
    parser.add_argument("--instrument", action="append", required=True)
    parser.add_argument("--bar", default="1d")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--adjustment", choices=("none",), default="none")
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if len(args.instrument) != 1:
        parser.error("the P0 capture supports exactly one --instrument; repeat support is reserved for a later schema")
    args.instrument = args.instrument[0]
    capture(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
