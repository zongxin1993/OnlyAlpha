"""Definition, canonical content, partition and Snapshot identity authorities."""

from __future__ import annotations

from hashlib import sha256

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.domain.market import OnlyBar

from .codec import only_bars_to_table
from .definition import OnlyResearchDatasetDefinition
from .schema import OnlyResearchBarDatasetSchema


def only_canonical_bar_key(bar: OnlyBar) -> tuple[str, object, object, object, int]:
    return (str(bar.instrument_id), bar.bar_start, bar.bar_end, bar.ts_event, bar.revision)


def only_canonical_bars(bars: tuple[OnlyBar, ...]) -> tuple[OnlyBar, ...]:
    return tuple(sorted(bars, key=only_canonical_bar_key))


def only_content_fingerprint(bars: tuple[OnlyBar, ...]) -> str:
    digest = sha256()
    table = only_bars_to_table(only_canonical_bars(bars))
    for row in table.to_pylist():
        payload = only_canonical_json(row).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def only_snapshot_fingerprint(
    definition: OnlyResearchDatasetDefinition,
    schema: OnlyResearchBarDatasetSchema,
    content_fingerprint: str,
    row_count: int,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": 1,
            "definition_fingerprint": definition.fingerprint,
            "dataset_schema_fingerprint": schema.fingerprint,
            "content_fingerprint": content_fingerprint,
            "row_count": row_count,
        }
    )
