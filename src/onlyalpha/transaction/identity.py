"""Deterministic business identities for durable execution transactions."""

from __future__ import annotations

import hashlib

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId

ONLY_EXECUTION_TRANSACTION_IDENTITY_SCHEMA_VERSION = 1


def only_runtime_transaction_id(
    *,
    runtime_id: OnlyRuntimeId,
    gateway_id: OnlyBrokerGatewayId,
    account_id: OnlyAccountId,
    broker_update_id: OnlyBrokerUpdateId,
    trade_id: OnlyTradeId,
) -> str:
    """Derive the sole durable transaction identity from broker business identity."""
    authority = "\x1f".join(
        (
            str(ONLY_EXECUTION_TRANSACTION_IDENTITY_SCHEMA_VERSION),
            str(runtime_id),
            str(gateway_id),
            str(account_id),
            str(broker_update_id),
            str(trade_id),
        )
    )
    return f"ETX-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


__all__ = ["ONLY_EXECUTION_TRANSACTION_IDENTITY_SCHEMA_VERSION", "only_runtime_transaction_id"]
