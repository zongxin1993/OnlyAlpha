"""Prepare deterministic file-backed state before the Compose Web journey."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.output import OnlyUserDataLayout  # noqa: E402
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore  # noqa: E402
from tests.research.calculation.support import snapshot  # noqa: E402

MANIFEST = ROOT / "tests/fixtures/web/research-product-v1.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("fixture_schema_version") != 1:
        raise ValueError("WEB_E2E_FIXTURE_SCHEMA_UNSUPPORTED")

    candidate, partitions = snapshot()
    expected_instruments = {str(item) for item in manifest["instruments"]}
    actual_instruments = {str(item) for item in candidate.definition.instruments}
    if actual_instruments != expected_instruments:
        raise ValueError("WEB_E2E_FIXTURE_INSTRUMENT_MISMATCH")
    if manifest["expected_candidate_count"] != len(candidate.definition.instruments):
        raise ValueError("WEB_E2E_FIXTURE_CANDIDATE_COUNT_MISMATCH")

    root = Path(os.environ.get("ONLYALPHA_USER_DATA_ROOT", "/var/lib/onlyalpha"))
    committed = OnlyParquetResearchDatasetSnapshotStore(OnlyUserDataLayout(root).research_dataset_root).commit(
        candidate, partitions
    )
    print(
        json.dumps(
            {
                "fixture_schema_version": manifest["fixture_schema_version"],
                "fixture_id": manifest["fixture_id"],
                "dataset_snapshot_fingerprint": committed.snapshot_fingerprint,
                "candidate_count": len(candidate.definition.instruments),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
