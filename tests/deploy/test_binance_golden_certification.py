from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).parents[2] / "deploy/compose/certify_binance_golden_source.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_binance_golden_certification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_certification_verifies_archive_content_count_and_timestamp_domain(tmp_path: Path) -> None:
    module = _module()
    content = b"open_time,open\n1704067200000,1\n1704067260000,2\n"
    archive = tmp_path / "SOURCE.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("source.csv", content)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_kind": "BINANCE_PUBLIC_ARCHIVE_CERTIFICATION_INPUT",
                "sources": [
                    {
                        "source_id": "SOURCE",
                        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "content_sha256": hashlib.sha256(content).hexdigest(),
                        "record_count": 2,
                        "minimum_timestamp_ms": 1704067200000,
                        "maximum_timestamp_ms": 1704067260000,
                        "provider_schema": "FIXTURE_WITH_HEADER",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert module.certify(manifest, tmp_path)[0]["record_count"] == 2

    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="ARCHIVE_HASH_MISMATCH"):
        module.certify(manifest, tmp_path)


def test_committed_source_manifest_freezes_required_spot_and_usdm_feeds() -> None:
    manifest = json.loads(
        (Path(__file__).parents[2] / "tests/fixtures/a0_binance_golden/source-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    sources = manifest["sources"]

    assert manifest["utc_range"] == {
        "start": "2024-01-01T00:00:00Z",
        "end_exclusive": "2024-02-01T00:00:00Z",
    }
    assert {(item["instrument_id"], item["feed_type"]) for item in sources} == {
        ("BTCUSDT.BINANCE", "BAR_1M"),
        ("ETHUSDT.BINANCE", "BAR_1M"),
        ("BTCUSDT-PERP.BINANCE", "BAR_1M"),
        ("BTCUSDT-PERP.BINANCE", "MARK_PRICE_1M"),
        ("BTCUSDT-PERP.BINANCE", "FUNDING_RATE"),
    }
    assert all(len(item["archive_sha256"]) == 64 and len(item["content_sha256"]) == 64 for item in sources)


def test_certification_rejects_manifest_path_escape(tmp_path: Path) -> None:
    module = _module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_kind": "BINANCE_PUBLIC_ARCHIVE_CERTIFICATION_INPUT",
                "sources": [{"source_id": "../ESCAPE"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SOURCE_ID_INVALID"):
        module.certify(manifest, tmp_path)
