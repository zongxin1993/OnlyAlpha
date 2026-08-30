"""Deterministic reference fact store used for fault/recovery proofs."""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyIngestSegment,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
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
        prior = self._segments.setdefault(segment.segment_id, segment)
        if prior.content_hash != segment.content_hash:
            raise OnlyMarketDataConflictError("SEGMENT_ID_CONTENT_CONFLICT")
        for bundle in records:
            raw_key = (segment.segment_id, bundle.evidence.raw_event_id)
            prior_hash = self._raw.setdefault(raw_key, bundle.evidence.raw_sha256)
            if prior_hash != bundle.evidence.raw_sha256:
                raise OnlyMarketDataConflictError("RAW_EVIDENCE_CONFLICT")
        self._fault("AFTER_RAW_WRITE")
        for bundle in records:
            for fact in bundle.canonical_facts:
                fact_key = (segment.segment_id, fact.canonical_fact_id, fact.raw_event_id)
                prior_fact = self._facts.setdefault(fact_key, fact)
                if prior_fact.canonical_payload_hash != fact.canonical_payload_hash:
                    raise OnlyMarketDataConflictError("CANONICAL_FACT_CONFLICT")
        self._fault("AFTER_CANONICAL_WRITE")

    def verify_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        if self.inspect_segment(segment) != "EXACT":
            raise RuntimeError("MARKET_DATA_SEGMENT_NOT_EXACT")
        expected_raw = {
            (segment.segment_id, bundle.evidence.raw_event_id): bundle.evidence.raw_sha256 for bundle in records
        }
        expected_facts = {
            (segment.segment_id, fact.canonical_fact_id, fact.raw_event_id): fact.canonical_payload_hash
            for bundle in records
            for fact in bundle.canonical_facts
        }
        stored_facts = {
            key: fact.canonical_payload_hash for key, fact in self._facts.items() if key[0] == segment.segment_id
        }
        stored_raw = {key: value for key, value in self._raw.items() if key[0] == segment.segment_id}
        if stored_raw != expected_raw or stored_facts != expected_facts:
            raise RuntimeError("MARKET_DATA_SEGMENT_CONTENT_NOT_EXACT")

    def read_revision_facts(
        self, revision: OnlyMarketDataRevision, scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        selected = {item[0] for item in revision.segment_refs}
        return tuple(
            sorted(
                (
                    fact
                    for (segment_id, _, _), fact in self._facts.items()
                    if segment_id in selected
                    and fact.instrument_id == scope.instrument_id
                    and fact.data_kind == scope.data_kind
                    and scope.start_ns <= fact.ts_event_ns <= scope.end_ns
                ),
                key=lambda item: (item.ts_event_ns, item.canonical_fact_id, item.raw_event_id),
            )
        )


__all__ = ["OnlyInMemoryMarketFactStore"]
