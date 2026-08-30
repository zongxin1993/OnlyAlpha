"""Exact versioned JSON codec used inside WAL frames."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyMarketDataProvenance,
    OnlyMarketDataQualityState,
    OnlyMarketDataRecordBundle,
    OnlyRawProviderEvidence,
)


def only_encode_record_bundle(bundle: OnlyMarketDataRecordBundle) -> bytes:
    for fact in bundle.canonical_facts:
        if only_canonical_fingerprint(fact.canonical_payload) != fact.canonical_payload_hash:
            raise ValueError("CANONICAL_PAYLOAD_HASH_MISMATCH")
    evidence = bundle.evidence
    value = {
        "schema_version": 1,
        "evidence": {
            "raw_event_id": evidence.raw_event_id,
            "source_id": evidence.source_id,
            "capture_session_id": evidence.capture_session_id,
            "provider": evidence.provider,
            "venue": evidence.venue,
            "market": evidence.market,
            "stream": evidence.stream,
            "provider_event_type": evidence.provider_event_type,
            "provider_event_id": evidence.provider_event_id,
            "provider_sequence": evidence.provider_sequence,
            "ts_event_ns": evidence.ts_event_ns,
            "ts_receive_ns": evidence.ts_receive_ns,
            "payload_codec": evidence.payload_codec,
            "provider_schema": evidence.provider_schema,
            "payload_base64": base64.b64encode(evidence.payload).decode("ascii"),
            "raw_sha256": evidence.raw_sha256,
            "provenance": evidence.provenance.value,
        },
        "canonical_facts": [
            {
                "canonical_fact_id": fact.canonical_fact_id,
                "raw_event_id": fact.raw_event_id,
                "source_id": fact.source_id,
                "segment_id": fact.segment_id,
                "capture_session_id": fact.capture_session_id,
                "data_kind": fact.data_kind,
                "instrument_id": fact.instrument_id,
                "ts_event_ns": fact.ts_event_ns,
                "ts_receive_ns": fact.ts_receive_ns,
                "ts_ingest_ns": fact.ts_ingest_ns,
                "canonical_payload": fact.canonical_payload,
                "canonical_payload_hash": fact.canonical_payload_hash,
                "normalizer_id": fact.normalizer_id,
                "normalizer_version": fact.normalizer_version,
                "quality_state": fact.quality_state.value,
                "provenance": fact.provenance.value,
            }
            for fact in bundle.canonical_facts
        ],
    }
    return only_canonical_json(value).encode("utf-8")


def only_decode_record_bundle(payload: bytes) -> OnlyMarketDataRecordBundle:
    raw = json.loads(payload)
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise ValueError("WAL_RECORD_SCHEMA_UNSUPPORTED")
    evidence_raw = raw.get("evidence")
    facts_raw = raw.get("canonical_facts")
    if not isinstance(evidence_raw, Mapping) or not isinstance(facts_raw, list):
        raise ValueError("WAL_RECORD_SHAPE_INVALID")
    evidence = OnlyRawProviderEvidence(
        raw_event_id=str(evidence_raw["raw_event_id"]),
        source_id=str(evidence_raw["source_id"]),
        capture_session_id=str(evidence_raw["capture_session_id"]),
        provider=str(evidence_raw["provider"]),
        venue=str(evidence_raw["venue"]),
        market=str(evidence_raw["market"]),
        stream=str(evidence_raw["stream"]),
        provider_event_type=str(evidence_raw["provider_event_type"]),
        provider_event_id=_optional_str(evidence_raw.get("provider_event_id")),
        provider_sequence=_optional_int(evidence_raw.get("provider_sequence")),
        ts_event_ns=_optional_int(evidence_raw.get("ts_event_ns")),
        ts_receive_ns=int(str(evidence_raw["ts_receive_ns"])),
        payload_codec=str(evidence_raw["payload_codec"]),
        provider_schema=str(evidence_raw["provider_schema"]),
        payload=base64.b64decode(str(evidence_raw["payload_base64"]), validate=True),
        raw_sha256=str(evidence_raw["raw_sha256"]),
        provenance=OnlyMarketDataProvenance(str(evidence_raw["provenance"])),
    )
    facts: list[OnlyCanonicalMarketFactRecord] = []
    for value in facts_raw:
        if not isinstance(value, Mapping) or not isinstance(value.get("canonical_payload"), dict):
            raise ValueError("WAL_CANONICAL_FACT_SHAPE_INVALID")
        facts.append(
            OnlyCanonicalMarketFactRecord(
                canonical_fact_id=str(value["canonical_fact_id"]),
                raw_event_id=str(value["raw_event_id"]),
                source_id=str(value["source_id"]),
                segment_id=str(value["segment_id"]),
                capture_session_id=str(value["capture_session_id"]),
                data_kind=str(value["data_kind"]),
                instrument_id=str(value["instrument_id"]),
                ts_event_ns=int(str(value["ts_event_ns"])),
                ts_receive_ns=int(str(value["ts_receive_ns"])),
                ts_ingest_ns=int(str(value["ts_ingest_ns"])),
                canonical_payload=dict(value["canonical_payload"]),
                canonical_payload_hash=str(value["canonical_payload_hash"]),
                normalizer_id=str(value["normalizer_id"]),
                normalizer_version=str(value["normalizer_version"]),
                quality_state=OnlyMarketDataQualityState(str(value["quality_state"])),
                provenance=OnlyMarketDataProvenance(str(value["provenance"])),
            )
        )
    return OnlyMarketDataRecordBundle(evidence, tuple(facts))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


__all__ = ["only_decode_record_bundle", "only_encode_record_bundle"]
