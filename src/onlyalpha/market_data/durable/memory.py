"""Deterministic reference fact store used for fault/recovery proofs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from hashlib import sha256

from onlyalpha.canonical import only_canonical_fingerprint

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyIngestSegment,
    OnlyMarketDataPhysicalPartitionProof,
    OnlyMarketDataPhysicalSegmentProof,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataScope,
    OnlyVerifiedSegmentBatch,
)
from .revision import OnlyMarketDataConflictError


class OnlyInMemoryMarketFactStore:
    def __init__(self, fault: Callable[[str], None] | None = None) -> None:
        self._raw: dict[tuple[str, str], str] = {}
        self._facts: dict[tuple[str, str, str], OnlyCanonicalMarketFactRecord] = {}
        self._segments: dict[str, OnlyIngestSegment] = {}
        self._fault = fault or (lambda _: None)

    def inspect_segment(self, segment: OnlyIngestSegment) -> str:
        raw = [key for key in self._raw if key[0] == segment.segment_id]
        facts = [key for key in self._facts if key[0] == segment.segment_id]
        if not raw and not facts:
            return "ABSENT"
        stored = self._segments.get(segment.segment_id)
        if stored is not None and stored.content_hash != segment.content_hash:
            return "CONFLICT"
        if len(raw) == segment.raw_count and len(facts) == segment.canonical_count:
            return "EXACT"
        if len(raw) <= segment.raw_count and len(facts) <= segment.canonical_count:
            return "PARTIAL"
        return "CONFLICT"

    def write_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        self.write_segments((segment,), {segment.segment_id: records})

    def write_segments(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        records_by_segment: Mapping[str, tuple[OnlyMarketDataRecordBundle, ...]],
    ) -> None:
        OnlyVerifiedSegmentBatch.build(segments, records_by_segment, None)
        states = {segment.segment_id: self.inspect_segment(segment) for segment in segments}
        if any(state in {"PARTIAL", "CONFLICT"} for state in states.values()):
            failed = next(state for state in states.values() if state in {"PARTIAL", "CONFLICT"})
            raise RuntimeError(f"MARKET_DATA_STORE_{failed}")
        for segment in segments:
            if states[segment.segment_id] == "EXACT":
                continue
            prior = self._segments.get(segment.segment_id)
            if prior is not None and prior.content_hash != segment.content_hash:
                raise OnlyMarketDataConflictError("SEGMENT_ID_CONTENT_CONFLICT")
        for segment in segments:
            if states[segment.segment_id] == "EXACT":
                continue
            self._segments.setdefault(segment.segment_id, segment)
            for bundle in records_by_segment[segment.segment_id]:
                raw_key = (segment.segment_id, bundle.evidence.raw_event_id)
                prior_hash = self._raw.setdefault(raw_key, bundle.evidence.raw_sha256)
                if prior_hash != bundle.evidence.raw_sha256:
                    raise OnlyMarketDataConflictError("RAW_EVIDENCE_CONFLICT")
        self._fault("AFTER_RAW_WRITE")
        for segment in segments:
            if states[segment.segment_id] == "EXACT":
                continue
            for bundle in records_by_segment[segment.segment_id]:
                for fact in bundle.canonical_facts:
                    fact_key = (segment.segment_id, fact.canonical_fact_id, fact.raw_event_id)
                    prior_fact = self._facts.setdefault(fact_key, fact)
                    if prior_fact.canonical_payload_hash != fact.canonical_payload_hash:
                        raise OnlyMarketDataConflictError("CANONICAL_FACT_CONFLICT")
        self._fault("AFTER_CANONICAL_WRITE")

    def verify_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        self.verify_segments(
            (segment,),
            {segment.segment_id: records},
            segment.recovery_scope() if segment.canonical_count else None,
        )

    def verify_segments(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        records_by_segment: Mapping[str, tuple[OnlyMarketDataRecordBundle, ...]],
        scope: OnlyMarketDataScope | None = None,
    ) -> OnlyVerifiedSegmentBatch:
        verified = OnlyVerifiedSegmentBatch.build(segments, records_by_segment, scope)
        for segment in segments:
            if self.inspect_segment(segment) != "EXACT":
                raise RuntimeError("MARKET_DATA_SEGMENT_NOT_EXACT")
            records = records_by_segment[segment.segment_id]
            expected_raw = {
                (segment.segment_id, bundle.evidence.raw_event_id): bundle.evidence.raw_sha256 for bundle in records
            }
            expected_facts = {
                (segment.segment_id, fact.canonical_fact_id, fact.raw_event_id): fact
                for bundle in records
                for fact in bundle.canonical_facts
            }
            stored_facts = {key: fact for key, fact in self._facts.items() if key[0] == segment.segment_id}
            stored_raw = {key: value for key, value in self._raw.items() if key[0] == segment.segment_id}
            if stored_raw != expected_raw or stored_facts != expected_facts:
                raise RuntimeError("MARKET_DATA_SEGMENT_CONTENT_NOT_EXACT")
        return replace(
            verified,
            physical_proofs=tuple(
                self._physical_proof(item) for item in sorted(segments, key=lambda item: item.segment_id)
            ),
        )

    def read_segment_facts(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        scope: OnlyMarketDataScope,
        proofs: tuple[OnlyMarketDataPhysicalSegmentProof, ...],
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        by_id = {item.segment_id: item for item in proofs}
        if len(by_id) != len(proofs) or set(by_id) != {item.segment_id for item in segments}:
            raise OnlyMarketDataConflictError("MARKET_DATA_PHYSICAL_PROOF_UNPROVABLE")
        if any(
            self.inspect_segment(item) != "EXACT" or self._physical_proof(item) != by_id[item.segment_id]
            for item in segments
        ):
            raise OnlyMarketDataConflictError("MARKET_DATA_SEGMENT_NOT_EXACT")
        return self._read_selected({item.segment_id for item in segments}, scope)

    def _physical_proof(self, segment: OnlyIngestSegment) -> OnlyMarketDataPhysicalSegmentProof:
        rows: dict[str, list[str]] = {
            "market_raw_event": [
                only_canonical_fingerprint((key, value))
                for key, value in self._raw.items()
                if key[0] == segment.segment_id
            ],
            "market_trade": [],
            "market_bar": [],
            "market_reference_price": [],
        }
        for (segment_id, _, _), fact in self._facts.items():
            if segment_id == segment.segment_id:
                rows[
                    {"TRADE": "market_trade", "BAR": "market_bar", "MARKET_REFERENCE": "market_reference_price"}[
                        fact.data_kind
                    ]
                ].append(only_canonical_fingerprint(fact))
        return OnlyMarketDataPhysicalSegmentProof.build(
            segment,
            tuple(
                OnlyMarketDataPhysicalPartitionProof(
                    table, len(values), sha256("".join(sorted(values)).encode()).hexdigest()
                )
                for table, values in rows.items()
            ),
        )

    def _read_selected(
        self, selected: set[str], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        return tuple(
            sorted(
                (
                    fact
                    for (segment_id, _, _), fact in self._facts.items()
                    if segment_id in selected
                    and fact.instrument_id == scope.instrument_id
                    and fact.data_kind == scope.data_kind
                    and (
                        scope.start_ns < fact.ts_event_ns
                        if scope.data_kind == "BAR"
                        else scope.start_ns <= fact.ts_event_ns
                    )
                    and fact.ts_event_ns <= scope.end_ns
                ),
                key=lambda item: (item.ts_event_ns, item.canonical_fact_id, item.raw_event_id),
            )
        )


__all__ = ["OnlyInMemoryMarketFactStore"]
