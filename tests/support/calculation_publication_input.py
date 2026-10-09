"""Source-backed contract fake for Artifact unit/fault tests, not native Chart admission.

Actual PostgreSQL T1/T2/D2 and installed publication are tested separately. This
fixture saves original reference fact-store rows before any publication; recovery
reads those rows, never an Artifact/E1 DTO and never acquires/rebuilds Source data.
Only the internal test composition hook binds a generic Graph/Plan to that input.
"""

import json
from datetime import datetime

from onlyalpha.canonical import only_canonical_json, only_canonical_payload
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.market_data.durable.memory import OnlyInMemoryMarketFactStore
from onlyalpha.market_data.durable.models import (
    OnlyCanonicalMarketFactRecord,
    OnlyIngestSegment,
    OnlyMarketDataPhysicalSegmentProof,
    OnlyMarketDataProvenance,
    OnlyMarketDataQualityState,
)
from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity
from onlyalpha.research.dataset.codec import only_bars_to_table
from onlyalpha.research.dataset.identity import only_canonical_bars
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.dataset.publication_input import _only_issue_verified_sealed_chart_publication_input
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1, _decode
from tests.application.test_chart_calculation_input_export import export_case


def source_dataset(root):
    chart, _, exporter = export_case(root / "owning-input")
    retained = exporter.export(chart.operation.operation_id).retained
    original = chart.market.service._facts
    (root / "source-owner.json").write_text(
        only_canonical_json(
            {
                "retained": retained.to_dict(),
                "raw_rows": [[list(key), value] for key, value in original._raw.items()],
                "canonical_rows": [only_canonical_payload(value) for value in original._facts.values()],
            }
        )
    )
    return chart.dataset, chart.preparation.dataset_snapshot_fingerprint


def verified_test_input(root, plan, graph, generation):
    def read_original():
        with (root / "source-owner.json").open() as stream:
            raw = json.load(stream)
        retained = OnlyRetainedSealedChartInputEvidenceV1.from_dict(raw["retained"])
        payload = retained.to_dict()
        scope, _, _ = _decode(payload)
        original = OnlyInMemoryMarketFactStore()
        segments = []
        for value in payload["segments"]:
            segment = OnlyIngestSegment(
                **(
                    dict(value)
                    | {
                        "created_at": datetime.fromisoformat(value["created_at"]),
                        "sealed_at": datetime.fromisoformat(value["sealed_at"]),
                        "capture_mode": OnlyMarketDataProvenance(value["capture_mode"]),
                        "bar_construction": OnlyBarConstructionIdentity.from_dict(value["bar_construction"]),
                    }
                )
            )
            original._segments[segment.segment_id] = segment
            segments.append(segment)
        original._raw = {tuple(key): value for key, value in raw["raw_rows"]}
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
            original._facts[(fact.segment_id, fact.canonical_fact_id, fact.raw_event_id)] = fact
        proofs = tuple(
            OnlyMarketDataPhysicalSegmentProof.from_dict(item) for item in payload["evidence"]["physical_proofs"]
        )
        facts = original.read_segment_facts(tuple(segments), scope, proofs)
        dataset = OnlyParquetResearchDatasetSnapshotStore(root / "owning-input" / "dataset").load_verified_table(
            payload["dataset_snapshot_fingerprint"]
        )
        retained.verify_snapshot(dataset.snapshot)
        table = only_bars_to_table(
            only_canonical_bars(
                tuple(OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload).payload.bar for fact in facts)
            )
        )
        assert table.equals(dataset.table, check_metadata=True)
        return retained

    return _only_issue_verified_sealed_chart_publication_input(read_original(), plan, graph, generation, read_original)
