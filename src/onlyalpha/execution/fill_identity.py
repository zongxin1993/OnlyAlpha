"""Stable business identity and payload authority for Broker Fill facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueTradeId,
)

if TYPE_CHECKING:
    from .persistence_ports import OnlyExecutionTransactionQueryPort

ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION = 1


class OnlyExecutionFillIdentityKind(StrEnum):
    VENUE_TRADE_ID = "VENUE_TRADE_ID"
    EXTERNAL_EVENT_ID = "EXTERNAL_EVENT_ID"
    TRADE_ID = "TRADE_ID"


class OnlyExecutionFillClassification(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class OnlyExecutionFillIdentity:
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    venue_trade_id: OnlyVenueTradeId | None
    external_event_id: str | None

    @property
    def canonical_kind(self) -> OnlyExecutionFillIdentityKind:
        if self.venue_trade_id is not None:
            return OnlyExecutionFillIdentityKind.VENUE_TRADE_ID
        if self.external_event_id:
            return OnlyExecutionFillIdentityKind.EXTERNAL_EVENT_ID
        return OnlyExecutionFillIdentityKind.TRADE_ID

    @property
    def canonical_value(self) -> str:
        if self.venue_trade_id is not None:
            return str(self.venue_trade_id)
        if self.external_event_id:
            return self.external_event_id
        return str(self.trade_id)

    @classmethod
    def from_update(cls, update: OnlyBrokerTradeUpdate) -> OnlyExecutionFillIdentity:
        return cls(
            update.runtime_id,
            update.gateway_id,
            update.account_id,
            update.order_id,
            update.fill.trade_id,
            update.fill.venue_trade_id,
            update.fill.external_event_id,
        )


@dataclass(frozen=True, slots=True)
class OnlyExecutionFillAuthority:
    identity: str
    payload_fingerprint: str
    fill_index: int

    def __post_init__(self) -> None:
        if not self.identity.startswith("EFILL-") or len(self.identity) != 70:
            raise ValueError("Fill authority requires a canonical EFILL identity")
        if len(self.payload_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.payload_fingerprint
        ):
            raise ValueError("Fill authority payload fingerprint must be a lowercase SHA-256 digest")
        if self.fill_index < 1:
            raise ValueError("Fill authority index must be positive")


def only_execution_fill_identity(identity: OnlyExecutionFillIdentity) -> str:
    authority = "\x1f".join(
        (
            str(ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION),
            str(identity.runtime_id),
            str(identity.gateway_id),
            str(identity.account_id),
            str(identity.order_id),
            identity.canonical_kind.value,
            identity.canonical_value,
        )
    )
    return f"EFILL-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


def only_execution_fill_identity_from_update(update: OnlyBrokerTradeUpdate) -> str:
    return only_execution_fill_identity(OnlyExecutionFillIdentity.from_update(update))


def only_execution_fill_payload_fingerprint(update: OnlyBrokerTradeUpdate) -> str:
    fill = update.fill
    fee = fill.reported_fee
    payload: dict[str, object] = {
        "account_id": str(update.account_id),
        "external_event_id": fill.external_event_id,
        "external_sequence": fill.external_sequence,
        "fee_external_reference": fill.fee_external_reference,
        "fee_reporting_mode": fill.fee_reporting_mode.value,
        "gateway_id": str(update.gateway_id),
        "liquidity_side": fill.liquidity_side.value,
        "metadata": dict(fill.metadata),
        "order_id": str(update.order_id),
        "price": _decimal(fill.price.value, fill.price.precision),
        "price_precision": fill.price.precision,
        "quantity": _decimal(fill.quantity.value, fill.quantity.precision),
        "quantity_precision": fill.quantity.precision,
        "reference_price": (
            None
            if fill.reference_price is None
            else _decimal(fill.reference_price.value, fill.reference_price.precision)
        ),
        "reference_price_precision": None if fill.reference_price is None else fill.reference_price.precision,
        "reported_fee": None if fee is None else _decimal(fee.amount, fee.currency.precision),
        "reported_fee_currency": None if fee is None else fee.currency.code,
        "reported_fee_currency_precision": None if fee is None else fee.currency.precision,
        "runtime_id": str(update.runtime_id),
        "source_sequence": update.source_sequence,
        "trade_id": str(fill.trade_id),
        "ts_event": update.ts_event.unix_nanos,
        "ts_init": update.ts_init.unix_nanos,
        "venue_order_id": None if fill.venue_order_id is None else str(fill.venue_order_id),
        "venue_trade_id": None if fill.venue_trade_id is None else str(fill.venue_trade_id),
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def only_classify_execution_fill(
    *, existing_payload_fingerprint: str | None, payload_fingerprint: str
) -> OnlyExecutionFillClassification:
    if existing_payload_fingerprint is None:
        return OnlyExecutionFillClassification.NEW
    if existing_payload_fingerprint == payload_fingerprint:
        return OnlyExecutionFillClassification.DUPLICATE
    return OnlyExecutionFillClassification.CONFLICT


def only_capture_execution_fill_authority(
    query: OnlyExecutionTransactionQueryPort,
    update: OnlyBrokerTradeUpdate,
) -> OnlyExecutionFillAuthority:
    identity = only_execution_fill_identity_from_update(update)
    fingerprint = only_execution_fill_payload_fingerprint(update)
    existing = query.get_by_fill_identity(update.runtime_id, identity)
    if existing is not None:
        if existing.fact.fill_payload_fingerprint != fingerprint:
            raise ValueError("FILL_IDENTITY_CONFLICT: durable Fill identity has a different payload")
        return OnlyExecutionFillAuthority(identity, fingerprint, existing.fact.fill_index)
    latest = query.latest_fill_for_order(update.runtime_id, update.order_id)
    fill_index = 1 if latest is None else latest.fact.fill_index + 1
    return OnlyExecutionFillAuthority(identity, fingerprint, fill_index)


def _decimal(value: object, precision: int) -> str:
    return format(value, f".{precision}f")


__all__ = [
    "ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION",
    "OnlyExecutionFillAuthority",
    "OnlyExecutionFillClassification",
    "OnlyExecutionFillIdentity",
    "OnlyExecutionFillIdentityKind",
    "only_classify_execution_fill",
    "only_capture_execution_fill_authority",
    "only_execution_fill_identity",
    "only_execution_fill_identity_from_update",
    "only_execution_fill_payload_fingerprint",
]
