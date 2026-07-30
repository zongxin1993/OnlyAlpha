"""Canonical JSON codec and distinct authority/payload hashes for execution transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent

from .committed import OnlyCommittedExecutionFact
from .projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExecutionProjection,
    OnlyFeeExecutionProjection,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyValuationExecutionProjection,
)
from .transaction import (
    OnlyCommittedExecutionFactDraft,
    OnlyCommittedExecutionTransaction,
    OnlyExecutionPrecondition,
    OnlyPreparedExecutionTransaction,
)

_PROJECTION_TYPES = {
    projection_type.__name__: projection_type
    for projection_type in (
        OnlyOrderExecutionProjection,
        OnlyPositionExecutionProjection,
        OnlyAllocationExecutionProjection,
        OnlySettlementExecutionProjection,
        OnlyMarginExecutionProjection,
        OnlyFeeExecutionProjection,
        OnlyAccountExecutionProjection,
        OnlyStrategyLedgerExecutionProjection,
        OnlyAccountCashReservationExecutionProjection,
        OnlyStrategyCashReservationExecutionProjection,
        OnlyPositionReservationExecutionProjection,
        OnlyMarginReservationExecutionProjection,
        OnlyRiskReservationExecutionProjection,
        OnlyRiskExecutionProjection,
        OnlyValuationExecutionProjection,
    )
}


def only_execution_payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _projection_payload(projection: OnlyExecutionProjection) -> dict[str, object]:
    payload = projection.to_dict()
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("projection identity must encode as an object")
    identity = dict(identity)
    identity.pop("payload_hash", None)
    payload["identity"] = identity
    return payload


def only_execution_projection_payload_hash(projection: OnlyExecutionProjection) -> str:
    return only_execution_payload_hash(_canonical(_projection_payload(projection)))


def only_with_execution_projection_hash(projection: OnlyExecutionProjection) -> OnlyExecutionProjection:
    return replace(
        projection,
        identity=replace(projection.identity, payload_hash=only_execution_projection_payload_hash(projection)),
    )


def _encode_projection(projection: OnlyExecutionProjection) -> dict[str, object]:
    return {"type": type(projection).__name__, "value": projection.to_dict()}


def _decode_projection(payload: object) -> OnlyExecutionProjection:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("value"), Mapping):
        raise ValueError("execution projection envelope is invalid")
    projection_type = _PROJECTION_TYPES.get(str(payload.get("type")))
    if projection_type is None:
        raise ValueError("unknown execution projection type")
    return projection_type.from_dict(cast(Mapping[str, object], payload["value"]))


def only_encode_execution_projection(projection: OnlyExecutionProjection) -> str:
    """Encode one projection union member without constructing a business transaction."""

    return _canonical(_encode_projection(projection))


def only_decode_execution_projection(payload: str) -> OnlyExecutionProjection:
    """Decode one projection union member from its typed envelope."""

    return _decode_projection(_load_object(payload))


def _event_authority(event_sequence: int, event: OnlyEvent) -> dict[str, object]:
    return {
        "event_sequence": event_sequence,
        "event_id": str(event.event_id),
        "event_type": str(event.event_type),
        "source": str(event.source),
        "runtime_id": str(event.runtime_id),
        "cluster_id": None if event.cluster_id is None else str(event.cluster_id),
        "payload": OnlyEvent._encode_payload(event.payload),
        "correlation_id": None if event.correlation_id is None else str(event.correlation_id),
        "causation_id": None if event.causation_id is None else str(event.causation_id),
        "priority": event.priority.value,
    }


def only_execution_transaction_authority_payload(prepared: OnlyPreparedExecutionTransaction) -> Mapping[str, object]:
    fact = prepared.fact_draft.to_dict()
    fact.pop("processing_sequence", None)
    fact.pop("ts_init", None)
    return {
        "schema_version": prepared.schema_version,
        "transaction_id": prepared.transaction_id,
        "runtime_id": str(prepared.runtime_id),
        "gateway_id": str(prepared.gateway_id),
        "account_id": str(prepared.account_id),
        "broker_update_id": str(prepared.broker_update_id),
        "trade_id": str(prepared.trade_id),
        "source_sequence": prepared.source_sequence,
        "fact_draft": fact,
        "projections": [_encode_projection(item) for item in prepared.projections],
        "outbox_events": [_event_authority(index, item) for index, item in enumerate(prepared.outbox_events, start=1)],
        "preconditions": [item.to_dict() for item in prepared.preconditions],
    }


def only_prepared_execution_transaction_authority_hash(
    prepared: OnlyPreparedExecutionTransaction, *, verify: bool = True
) -> str:
    digest = only_execution_payload_hash(_canonical(only_execution_transaction_authority_payload(prepared)))
    if verify and prepared.authority_hash != digest:
        raise ValueError("prepared execution transaction authority hash mismatch")
    return digest


def _prepared_payload(prepared: OnlyPreparedExecutionTransaction) -> dict[str, object]:
    return {
        "schema_version": prepared.schema_version,
        "transaction_id": prepared.transaction_id,
        "runtime_id": str(prepared.runtime_id),
        "gateway_id": str(prepared.gateway_id),
        "account_id": str(prepared.account_id),
        "broker_update_id": str(prepared.broker_update_id),
        "trade_id": str(prepared.trade_id),
        "source_sequence": prepared.source_sequence,
        "prepared_at_ns": prepared.prepared_at.unix_nanos,
        "fact_draft": prepared.fact_draft.to_dict(),
        "projections": [_encode_projection(item) for item in prepared.projections],
        "outbox_events": [item.to_dict() for item in prepared.outbox_events],
        "preconditions": [item.to_dict() for item in prepared.preconditions],
        "authority_hash": prepared.authority_hash,
    }


def only_prepared_execution_transaction_payload_hash(
    prepared: OnlyPreparedExecutionTransaction, *, verify: bool = True
) -> str:
    digest = only_execution_payload_hash(_canonical(_prepared_payload(prepared)))
    if verify and prepared.payload_hash != digest:
        raise ValueError("prepared execution transaction payload hash mismatch")
    return digest


def only_encode_prepared_execution_transaction(prepared: OnlyPreparedExecutionTransaction) -> str:
    only_prepared_execution_transaction_authority_hash(prepared)
    only_prepared_execution_transaction_payload_hash(prepared)
    payload = _prepared_payload(prepared)
    payload["payload_hash"] = prepared.payload_hash
    return _canonical(payload)


def only_decode_prepared_execution_transaction(payload: str) -> OnlyPreparedExecutionTransaction:
    value = _load_object(payload)
    _require_schema(value)
    fact_payload = _mapping(value, "fact_draft")
    historical_fill_authority = "fill_identity" not in fact_payload
    if historical_fill_authority:
        original = dict(value)
        stored_payload_hash = str(original.pop("payload_hash"))
        if stored_payload_hash != only_execution_payload_hash(_canonical(original)):
            raise ValueError("legacy prepared execution transaction payload hash mismatch")
    prepared = OnlyPreparedExecutionTransaction(
        transaction_id=str(value["transaction_id"]),
        runtime_id=OnlyRuntimeId(str(value["runtime_id"])),
        gateway_id=OnlyBrokerGatewayId(str(value["gateway_id"])),
        account_id=OnlyAccountId(str(value["account_id"])),
        broker_update_id=OnlyBrokerUpdateId(str(value["broker_update_id"])),
        trade_id=OnlyTradeId(str(value["trade_id"])),
        source_sequence=int(str(value["source_sequence"])),
        prepared_at=OnlyTimestamp.from_unix_nanos(int(str(value["prepared_at_ns"]))),
        fact_draft=OnlyCommittedExecutionFactDraft.from_dict(fact_payload),
        projections=tuple(_decode_projection(item) for item in _list(value, "projections")),
        outbox_events=tuple(OnlyEvent.from_dict(_as_mapping(item)) for item in _list(value, "outbox_events")),
        preconditions=tuple(
            OnlyExecutionPrecondition.from_dict(_as_mapping(item)) for item in _list(value, "preconditions")
        ),
        authority_hash="" if historical_fill_authority else str(value["authority_hash"]),
        payload_hash="" if historical_fill_authority else str(value["payload_hash"]),
    )
    return prepared


def _committed_payload(transaction: OnlyCommittedExecutionTransaction) -> dict[str, object]:
    return {
        "schema_version": transaction.schema_version,
        "runtime_id": str(transaction.runtime_id),
        "execution_sequence": transaction.execution_sequence,
        "transaction_id": transaction.transaction_id,
        "fact": transaction.fact.to_dict(),
        "projections": [_encode_projection(item) for item in transaction.projections],
        "outbox_events": [item.to_dict() for item in transaction.outbox_events],
        "committed_at_ns": transaction.committed_at.unix_nanos,
        "prepared_authority_hash": transaction.prepared_authority_hash,
        "prepared_payload_hash": transaction.prepared_payload_hash,
        "projection_ready": transaction.projection_ready,
        "projected_at_ns": None if transaction.projected_at is None else transaction.projected_at.unix_nanos,
        "projection_error": transaction.projection_error,
        "projection_failed_at_ns": None
        if transaction.projection_failed_at is None
        else transaction.projection_failed_at.unix_nanos,
    }


def only_committed_execution_transaction_payload_hash(transaction: OnlyCommittedExecutionTransaction) -> str:
    return only_execution_payload_hash(_canonical(_committed_payload(transaction)))


def only_encode_committed_execution_transaction(transaction: OnlyCommittedExecutionTransaction) -> str:
    if transaction.committed_payload_hash != only_committed_execution_transaction_payload_hash(transaction):
        raise ValueError("committed execution transaction payload hash mismatch")
    payload = _committed_payload(transaction)
    payload["committed_payload_hash"] = transaction.committed_payload_hash
    return _canonical(payload)


def only_decode_committed_execution_transaction(payload: str) -> OnlyCommittedExecutionTransaction:
    value = _load_object(payload)
    _require_schema(value)
    fact_payload = _mapping(value, "fact")
    historical_fill_authority = "fill_identity" not in fact_payload
    if historical_fill_authority:
        original = dict(value)
        stored_payload_hash = str(original.pop("committed_payload_hash"))
        if stored_payload_hash != only_execution_payload_hash(_canonical(original)):
            raise ValueError("legacy committed execution transaction payload hash mismatch")
    transaction = OnlyCommittedExecutionTransaction(
        runtime_id=OnlyRuntimeId(str(value["runtime_id"])),
        execution_sequence=int(str(value["execution_sequence"])),
        transaction_id=str(value["transaction_id"]),
        fact=OnlyCommittedExecutionFact.from_dict(fact_payload),
        projections=tuple(_decode_projection(item) for item in _list(value, "projections")),
        outbox_events=tuple(OnlyEvent.from_dict(_as_mapping(item)) for item in _list(value, "outbox_events")),
        committed_at=OnlyTimestamp.from_unix_nanos(int(str(value["committed_at_ns"]))),
        prepared_authority_hash=str(value["prepared_authority_hash"]),
        prepared_payload_hash=str(value["prepared_payload_hash"]),
        committed_payload_hash="" if historical_fill_authority else str(value["committed_payload_hash"]),
        projection_ready=bool(value["projection_ready"]),
        projected_at=_optional_timestamp(value.get("projected_at_ns")),
        projection_error=None if value.get("projection_error") is None else str(value["projection_error"]),
        projection_failed_at=_optional_timestamp(value.get("projection_failed_at_ns")),
    )
    if historical_fill_authority:
        transaction = replace(
            transaction,
            committed_payload_hash=only_committed_execution_transaction_payload_hash(transaction),
        )
    elif transaction.committed_payload_hash != only_committed_execution_transaction_payload_hash(transaction):
        raise ValueError("committed execution transaction payload hash mismatch")
    return transaction


class OnlyExecutionTransactionCodec:
    encode_prepared = staticmethod(only_encode_prepared_execution_transaction)
    decode_prepared = staticmethod(only_decode_prepared_execution_transaction)
    encode_committed = staticmethod(only_encode_committed_execution_transaction)
    decode_committed = staticmethod(only_decode_committed_execution_transaction)


def _load_object(payload: str) -> Mapping[str, object]:
    value = json.loads(payload)
    if not isinstance(value, Mapping):
        raise ValueError("execution transaction payload must be an object")
    return cast(Mapping[str, object], value)


def _require_schema(value: Mapping[str, object]) -> None:
    if value.get("schema_version") != 4:
        raise ValueError("unsupported execution transaction schema version")


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _as_mapping(value[key])


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("execution transaction nested payload must be an object")
    return cast(Mapping[str, object], value)


def _list(value: Mapping[str, object], key: str) -> list[object]:
    result = value[key]
    if not isinstance(result, list):
        raise ValueError(f"execution transaction {key} must be an array")
    return cast(list[object], result)


def _optional_timestamp(value: object) -> OnlyTimestamp | None:
    return None if value is None else OnlyTimestamp.from_unix_nanos(int(str(value)))


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
