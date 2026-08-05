import hashlib
import json
from pathlib import Path

from onlyalpha.reference import OnlyAshareInstrumentReference, OnlyAshareReferenceRegistry

FIXTURE = Path("tests/fixtures/reference/cn_a_share_v1")


def test_frozen_reference_dataset_manifest_and_coverage() -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    content = (FIXTURE / "references.json").read_bytes()
    assert hashlib.sha256(content).hexdigest() == manifest["files"]["references.json"]
    raw_records = json.loads(content)
    records = tuple(OnlyAshareInstrumentReference.from_mapping(item) for item in raw_records)
    registry = OnlyAshareReferenceRegistry(records)
    assert {item.board.value for item in records} == {"SSE_MAIN", "SZSE_MAIN", "CHINEXT", "STAR"}
    assert any(item.st_status for item in records)
    assert any(item.suspended for item in records)
    assert all(item.previous_close.value > 0 for item in records)
    assert registry.fingerprint == OnlyAshareReferenceRegistry(tuple(reversed(records))).fingerprint
