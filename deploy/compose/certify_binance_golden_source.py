#!/usr/bin/env python3
"""Verify downloaded Binance archives before Product Dataset materialization."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_manifest(path: Path) -> tuple[dict[str, object], ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or raw.get("manifest_kind") != "BINANCE_PUBLIC_ARCHIVE_CERTIFICATION_INPUT"
        or not isinstance(raw.get("sources"), list)
    ):
        raise ValueError("BINANCE_GOLDEN_SOURCE_MANIFEST_INVALID")
    sources = tuple(raw["sources"])
    if not all(isinstance(item, dict) for item in sources):
        raise ValueError("BINANCE_GOLDEN_SOURCE_MANIFEST_INVALID")
    return cast(tuple[dict[str, object], ...], sources)


def _data_rows(content: bytes, provider_schema: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))
    if provider_schema.endswith("WITH_HEADER"):
        if not rows or not rows[0] or rows[0][0] not in {"open_time", "calc_time"}:
            raise ValueError("BINANCE_GOLDEN_SOURCE_HEADER_INVALID")
        rows = rows[1:]
    if not rows or any(not row or not row[0].isdigit() for row in rows):
        raise ValueError("BINANCE_GOLDEN_SOURCE_ROWS_INVALID")
    return rows


def certify(manifest_path: Path, archive_root: Path) -> tuple[dict[str, object], ...]:
    certified: list[dict[str, object]] = []
    for source in _load_manifest(manifest_path):
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or re.fullmatch(r"[A-Z0-9_]+", source_id) is None:
            raise ValueError("BINANCE_GOLDEN_SOURCE_ID_INVALID")
        path = archive_root / f"{source_id}.zip"
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"BINANCE_GOLDEN_ARCHIVE_PATH_INVALID: {source_id}")
        archive = path.read_bytes()
        if len(archive) > 32 * 1024 * 1024:
            raise ValueError(f"BINANCE_GOLDEN_ARCHIVE_SIZE_INVALID: {source_id}")
        if _sha256(archive) != source.get("archive_sha256"):
            raise ValueError(f"BINANCE_GOLDEN_ARCHIVE_HASH_MISMATCH: {source_id}")
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = tuple(item for item in bundle.infolist() if not item.is_dir())
            if len(members) != 1:
                raise ValueError(f"BINANCE_GOLDEN_ARCHIVE_SHAPE_INVALID: {source_id}")
            if members[0].file_size > 128 * 1024 * 1024:
                raise ValueError(f"BINANCE_GOLDEN_CONTENT_SIZE_INVALID: {source_id}")
            content = bundle.read(members[0])
        if _sha256(content) != source.get("content_sha256"):
            raise ValueError(f"BINANCE_GOLDEN_CONTENT_HASH_MISMATCH: {source_id}")
        schema = source.get("provider_schema")
        if not isinstance(schema, str):
            raise ValueError("BINANCE_GOLDEN_SOURCE_SCHEMA_INVALID")
        rows = _data_rows(content, schema)
        timestamps = tuple(int(row[0]) for row in rows)
        expected = (
            source.get("record_count"),
            source.get("minimum_timestamp_ms"),
            source.get("maximum_timestamp_ms"),
        )
        actual = (len(rows), min(timestamps), max(timestamps))
        if actual != expected:
            raise ValueError(f"BINANCE_GOLDEN_SOURCE_DOMAIN_MISMATCH: {source_id}")
        certified.append(
            {
                "source_id": source_id,
                "archive_sha256": _sha256(archive),
                "content_sha256": _sha256(content),
                "record_count": len(rows),
                "minimum_timestamp_ms": min(timestamps),
                "maximum_timestamp_ms": max(timestamps),
            }
        )
    return tuple(certified)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = certify(args.manifest, args.archive_root)
    print(json.dumps({"schema_version": 1, "certified_sources": result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
