"""Independent Contract/Arrow vectors; legacy codec defects are not an oracle.

The legacy codec needs an explicit Decimal(38) context and loses fractional
timestamps through float seconds. Reference rows correct that known timestamp
defect independently; only Rust owns the corrected production implementation.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Context, localcontext
from pathlib import Path

from onlyalpha.canonical import only_canonical_json, only_canonical_payload
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.market import OnlyBar
from onlyalpha.research.dataset.codec import only_bars_to_table
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_snapshot_fingerprint
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V2

FIXTURE = Path(__file__).parent.parent / "fixtures/research_dataset.json"


def reference() -> dict[str, object]:
    market = json.loads((FIXTURE.parent / "market_wal_history.json").read_text())
    bundle = json.loads(market["native_bundle_json"])
    raw = bundle["canonical_facts"][0]["canonical_payload"]["payload"]["value"]
    second = json.loads(json.dumps(raw))
    for key in ("bar_start", "bar_end", "ts_event", "ts_init"):
        second[key] = second[key].replace("00:00:", "00:02:").replace("00:01:", "00:03:").replace("00Z", "00.123457Z")
    for key in ("open", "high", "low", "close"):
        second[key]["value"] = "12345678901234567890.123456789012345678"
        second[key]["precision"] = 18
    bars = tuple(OnlyBar.from_dict(row) for row in (raw, second))
    definition = OnlyResearchDatasetDefinition(
        (bars[0].instrument_id,),
        bars[0].bar_type.semantic,
        OnlyTimeRange(bars[0].bar_start, bars[1].bar_end),
    )
    # Half-open event end must include both actual event times.
    from datetime import timedelta

    definition = OnlyResearchDatasetDefinition(
        definition.instruments,
        definition.bar_semantic,
        OnlyTimeRange(definition.time_range.start, definition.time_range.end + timedelta(minutes=1)),
    )
    with localcontext(Context(prec=38)):
        rows = only_bars_to_table(bars).to_pylist()
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for row, bar in zip(rows, bars, strict=True):
        for key in ("bar_start", "bar_end", "ts_event", "ts_init"):
            delta = getattr(bar, key) - epoch
            row[key + "_ns"] = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    digest = hashlib.sha256()
    for row in rows:
        payload = only_canonical_json(row).encode()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    content = digest.hexdigest()
    return {
        "bars": [bar.to_dict() for bar in bars],
        "definition": definition.to_dict(),
        "definition_fingerprint": definition.fingerprint,
        "schema": dict(RESEARCH_BAR_DATASET_SCHEMA_V2.semantic_payload()),
        "schema_fingerprint": RESEARCH_BAR_DATASET_SCHEMA_V2.fingerprint,
        "rows": only_canonical_payload(rows),
        "construction_fingerprint": "a" * 64,
        "content_fingerprint": content,
        "snapshot_fingerprint": only_snapshot_fingerprint(
            definition, RESEARCH_BAR_DATASET_SCHEMA_V2, content, len(bars), "a" * 64
        ),
    }


def test_native_dataset_vector_matches_independent_contract() -> None:
    assert json.loads(FIXTURE.read_text()) == reference()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(reference(), indent=2, ensure_ascii=False) + "\n")
