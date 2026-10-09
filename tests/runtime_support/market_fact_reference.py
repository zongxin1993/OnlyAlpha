"""Disk-backed reference fact reader for cross-process, offline physical tests.

Only fixture setup writes original reference-store rows. Reads recompute the
existing canonical physical proof; no acquisition or Artifact restoration.
"""

import json

from onlyalpha.canonical import only_canonical_json, only_canonical_payload
from onlyalpha.market_data.durable.memory import OnlyInMemoryMarketFactStore
from onlyalpha.market_data.durable.models import (
    OnlyCanonicalMarketFactRecord,
    OnlyMarketDataProvenance,
    OnlyMarketDataQualityState,
)


def save_reference_facts(path, store):
    path.write_text(
        only_canonical_json(
            {
                "raw_rows": [[list(key), value] for key, value in store._raw.items()],
                "canonical_rows": [only_canonical_payload(value) for value in store._facts.values()],
            }
        )
    )


class ReferenceFactReader:
    def __init__(self, path):
        self.path = path

    def read_segment_facts(self, segments, scope, proofs):
        raw = json.loads(self.path.read_text())
        store = OnlyInMemoryMarketFactStore()
        store._segments = {segment.segment_id: segment for segment in segments}
        store._raw = {tuple(key): value for key, value in raw["raw_rows"]}
        for value in raw["canonical_rows"]:
            fact = OnlyCanonicalMarketFactRecord(
                **(
                    value
                    | {
                        "quality_state": OnlyMarketDataQualityState(value["quality_state"]),
                        "provenance": OnlyMarketDataProvenance(value["provenance"]),
                    }
                )
            )
            store._facts[(fact.segment_id, fact.canonical_fact_id, fact.raw_event_id)] = fact
        return store.read_segment_facts(segments, scope, proofs)
