"""Canonical JSON codec and distinct authority/payload hashes for execution transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.execution.terminal_fact import (
    OnlyCommittedTerminalExecutionFact,
    OnlyCommittedTerminalExecutionFactDraft,
)
from onlyalpha.execution.trade_fact import OnlyCommittedExecutionFactDraft
from onlyalpha.fee.facts import OnlyCommittedFeeReconciliationFact, OnlyFeeReconciliationFactDraft
from onlyalpha.settlement.facts import OnlyCommittedSettlementMaturityFact, OnlySettlementMaturityFactDraft
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyFeeApplicationProjection,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyOrderFeeAccrualProjection,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyValuationExecutionProjection,
)
from onlyalpha.transaction.transaction import (
    OnlyCommittedRuntimeTransaction,
    OnlyPreparedRuntimeTransaction,
    OnlyRuntimePrecondition,
)

from .enums import OnlyRuntimeOperationKind

_PROJECTION_TYPES = {
    projection_type.__name__: projection_type
    for projection_type in (
        OnlyOrderExecutionProjection,
        OnlyOrderTerminalExecutionProjection,
        OnlyPositionExecutionProjection,
        OnlyAllocationExecutionProjection,
        OnlySettlementExecutionProjection,
        OnlyMarginExecutionProjection,
        OnlyFeeApplicationProjection,
        OnlyOrderFeeAccrualProjection,
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


def _projection_payload(projection: OnlyRuntimeProjection) -> dict[str, object]:
    payload = projection.to_dict()
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("projection identity must encode as an object")
    identity = dict(identity)
    identity.pop("payload_hash", None)
    payload["identity"] = identity
    return payload


def only_runtime_projection_payload_hash(projection: OnlyRuntimeProjection) -> str:
    return only_execution_payload_hash(_canonical(_projection_payload(projection)))


def only_with_execution_projection_hash(projection: OnlyRuntimeProjection) -> OnlyRuntimeProjection:
    return replace(
        projection,
        identity=replace(projection.identity, payload_hash=only_runtime_projection_payload_hash(projection)),
    )


def _encode_projection(projection: OnlyRuntimeProjection) -> dict[str, object]:
    return {"type": type(projection).__name__, "value": projection.to_dict()}


def _decode_projection(payload: object) -> OnlyRuntimeProjection:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("value"), Mapping):
        raise ValueError("execution projection envelope is invalid")
    projection_type = _PROJECTION_TYPES.get(str(payload.get("type")))
    if projection_type is None:
        raise ValueError("unknown execution projection type")
    return projection_type.from_dict(cast(Mapping[str, object], payload["value"]))


def only_encode_execution_projection(projection: OnlyRuntimeProjection) -> str:
    """Encode one projection union member without constructing a business transaction."""

    return _canonical(_encode_projection(projection))


def only_decode_execution_projection(payload: str) -> OnlyRuntimeProjection:
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


def only_runtime_transaction_authority_payload(prepared: OnlyPreparedRuntimeTransaction) -> Mapping[str, object]:
    fact = prepared.fact_draft.to_dict()
    fact.pop("processing_sequence", None)
    fact.pop("ts_init", None)
    return {
        "schema_version": prepared.schema_version,
        "transaction_id": prepared.transaction_id,
        "runtime_id": str(prepared.runtime_id),
        "operation_kind": prepared.operation_kind.value,
        "operation_identity": prepared.operation_identity,
        "account_id": None if prepared.account_id is None else str(prepared.account_id),
        "effective_time_ns": prepared.effective_time.unix_nanos,
        "fact_draft": fact,
        "projections": [_encode_projection(item) for item in prepared.projections],
        "outbox_events": [_event_authority(index, item) for index, item in enumerate(prepared.outbox_events, start=1)],
        "preconditions": [item.to_dict() for item in prepared.preconditions],
    }


def only_prepared_runtime_transaction_authority_hash(
    prepared: OnlyPreparedRuntimeTransaction, *, verify: bool = True
) -> str:
    digest = only_execution_payload_hash(_canonical(only_runtime_transaction_authority_payload(prepared)))
    if verify and prepared.authority_hash != digest:
        raise ValueError("prepared execution transaction authority hash mismatch")
    return digest


def _prepared_payload(prepared: OnlyPreparedRuntimeTransaction) -> dict[str, object]:
    return {
        "schema_version": prepared.schema_version,
        "transaction_id": prepared.transaction_id,
        "runtime_id": str(prepared.runtime_id),
        "operation_kind": prepared.operation_kind.value,
        "operation_identity": prepared.operation_identity,
        "account_id": None if prepared.account_id is None else str(prepared.account_id),
        "effective_time_ns": prepared.effective_time.unix_nanos,
        "prepared_at_ns": prepared.prepared_at.unix_nanos,
        "fact_draft": prepared.fact_draft.to_dict(),
        "projections": [_encode_projection(item) for item in prepared.projections],
        "outbox_events": [item.to_dict() for item in prepared.outbox_events],
        "preconditions": [item.to_dict() for item in prepared.preconditions],
        "authority_hash": prepared.authority_hash,
    }


def only_prepared_runtime_transaction_payload_hash(
    prepared: OnlyPreparedRuntimeTransaction, *, verify: bool = True
) -> str:
    digest = only_execution_payload_hash(_canonical(_prepared_payload(prepared)))
    if verify and prepared.payload_hash != digest:
        raise ValueError("prepared execution transaction payload hash mismatch")
    return digest


def only_encode_prepared_execution_transaction(prepared: OnlyPreparedRuntimeTransaction) -> str:
    only_prepared_runtime_transaction_authority_hash(prepared)
    only_prepared_runtime_transaction_payload_hash(prepared)
    payload = _prepared_payload(prepared)
    payload["payload_hash"] = prepared.payload_hash
    return _canonical(payload)


def only_decode_prepared_execution_transaction(payload: str) -> OnlyPreparedRuntimeTransaction:
    value = _load_object(payload)
    _require_schema(value)
    fact_payload = _mapping(value, "fact_draft")
    operation_kind = OnlyRuntimeOperationKind(str(value.get("operation_kind", "TRADE_FILL")))
    prepared = OnlyPreparedRuntimeTransaction(
        transaction_id=str(value["transaction_id"]),
        runtime_id=OnlyRuntimeId(str(value["runtime_id"])),
        operation_kind=operation_kind,
        operation_identity=str(value["operation_identity"]),
        account_id=None if value.get("account_id") is None else OnlyAccountId(str(value["account_id"])),
        effective_time=OnlyTimestamp.from_unix_nanos(int(str(value["effective_time_ns"]))),
        prepared_at=OnlyTimestamp.from_unix_nanos(int(str(value["prepared_at_ns"]))),
        fact_draft=(
            OnlyCommittedExecutionFactDraft.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.TRADE_FILL
            else OnlyCommittedTerminalExecutionFactDraft.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.ORDER_TERMINAL
            else OnlyFeeReconciliationFactDraft.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.FEE_RECONCILIATION
            else OnlySettlementMaturityFactDraft.from_dict(fact_payload)
        ),
        projections=tuple(_decode_projection(item) for item in _list(value, "projections")),
        outbox_events=tuple(OnlyEvent.from_dict(_as_mapping(item)) for item in _list(value, "outbox_events")),
        preconditions=tuple(
            OnlyRuntimePrecondition.from_dict(_as_mapping(item)) for item in _list(value, "preconditions")
        ),
        authority_hash=str(value["authority_hash"]),
        payload_hash=str(value["payload_hash"]),
    )
    return prepared


def _committed_payload(transaction: OnlyCommittedRuntimeTransaction) -> dict[str, object]:
    return {
        "schema_version": transaction.schema_version,
        "runtime_id": str(transaction.runtime_id),
        "execution_sequence": transaction.execution_sequence,
        "transaction_id": transaction.transaction_id,
        "operation_kind": transaction.operation_kind.value,
        "operation_identity": transaction.operation_identity,
        "account_id": None if transaction.account_id is None else str(transaction.account_id),
        "effective_time_ns": transaction.effective_time.unix_nanos,
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


def only_committed_runtime_transaction_payload_hash(transaction: OnlyCommittedRuntimeTransaction) -> str:
    return only_execution_payload_hash(_canonical(_committed_payload(transaction)))


def only_encode_committed_execution_transaction(transaction: OnlyCommittedRuntimeTransaction) -> str:
    if transaction.committed_payload_hash != only_committed_runtime_transaction_payload_hash(transaction):
        raise ValueError("committed execution transaction payload hash mismatch")
    payload = _committed_payload(transaction)
    payload["committed_payload_hash"] = transaction.committed_payload_hash
    return _canonical(payload)


def only_decode_committed_execution_transaction(payload: str) -> OnlyCommittedRuntimeTransaction:
    value = _load_object(payload)
    _require_schema(value)
    fact_payload = _mapping(value, "fact")
    operation_kind = OnlyRuntimeOperationKind(str(value.get("operation_kind", "TRADE_FILL")))
    transaction = OnlyCommittedRuntimeTransaction(
        runtime_id=OnlyRuntimeId(str(value["runtime_id"])),
        execution_sequence=int(str(value["execution_sequence"])),
        transaction_id=str(value["transaction_id"]),
        operation_kind=operation_kind,
        operation_identity=str(value["operation_identity"]),
        account_id=None if value.get("account_id") is None else OnlyAccountId(str(value["account_id"])),
        effective_time=OnlyTimestamp.from_unix_nanos(int(str(value["effective_time_ns"]))),
        fact=(
            OnlyCommittedExecutionFact.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.TRADE_FILL
            else OnlyCommittedTerminalExecutionFact.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.ORDER_TERMINAL
            else OnlyCommittedFeeReconciliationFact.from_dict(fact_payload)
            if operation_kind is OnlyRuntimeOperationKind.FEE_RECONCILIATION
            else OnlyCommittedSettlementMaturityFact.from_dict(fact_payload)
        ),
        projections=tuple(_decode_projection(item) for item in _list(value, "projections")),
        outbox_events=tuple(OnlyEvent.from_dict(_as_mapping(item)) for item in _list(value, "outbox_events")),
        committed_at=OnlyTimestamp.from_unix_nanos(int(str(value["committed_at_ns"]))),
        prepared_authority_hash=str(value["prepared_authority_hash"]),
        prepared_payload_hash=str(value["prepared_payload_hash"]),
        committed_payload_hash=str(value["committed_payload_hash"]),
        projection_ready=bool(value["projection_ready"]),
        projected_at=_optional_timestamp(value.get("projected_at_ns")),
        projection_error=None if value.get("projection_error") is None else str(value["projection_error"]),
        projection_failed_at=_optional_timestamp(value.get("projection_failed_at_ns")),
    )
    if transaction.committed_payload_hash != only_committed_runtime_transaction_payload_hash(transaction):
        raise ValueError("committed execution transaction payload hash mismatch")
    return transaction


class OnlyRuntimeTransactionCodec:
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
    if value.get("schema_version") != 6:
        raise ValueError("UNSUPPORTED_RUNTIME_TRANSACTION_SCHEMA: unsupported schema version")


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


def _identifier_text(value: object) -> str:
    return str(value["value"]) if isinstance(value, Mapping) else str(value)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
