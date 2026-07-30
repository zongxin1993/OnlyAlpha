"""Stable identity authority for durable Order terminal operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from onlyalpha.broker.updates import (
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
)
from onlyalpha.domain.enums import OnlyOrderStatus

type OnlyBrokerOrderTerminalUpdate = (
    OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderExpiredUpdate
)


@dataclass(frozen=True, slots=True)
class OnlyExecutionTerminalAuthority:
    terminal_identity: str
    payload_fingerprint: str
    terminal_status: OnlyOrderStatus

    def __post_init__(self) -> None:
        if not self.terminal_identity.startswith("ETERM-"):
            raise ValueError("terminal identity must use the ETERM prefix")
        if len(self.payload_fingerprint) != 64:
            raise ValueError("terminal payload fingerprint must be SHA-256")
        if self.terminal_status not in {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.REJECTED,
            OnlyOrderStatus.EXPIRED,
        }:
            raise ValueError("terminal authority requires a supported terminal status")


def only_capture_execution_terminal_authority(
    update: OnlyBrokerOrderTerminalUpdate,
) -> OnlyExecutionTerminalAuthority:
    status = only_execution_terminal_status(update)
    identity_payload = "\x1f".join(
        (
            str(update.runtime_id),
            str(update.gateway_id),
            str(update.account_id),
            str(update.order_id),
            str(update.update_id),
            status.value,
        )
    )
    identity = f"ETERM-{hashlib.sha256(identity_payload.encode('utf-8')).hexdigest()}"
    payload = json.dumps(update.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return OnlyExecutionTerminalAuthority(identity, fingerprint, status)


def only_execution_terminal_status(update: OnlyBrokerOrderTerminalUpdate) -> OnlyOrderStatus:
    if isinstance(update, OnlyBrokerOrderCancelledUpdate):
        return OnlyOrderStatus.CANCELLED
    if isinstance(update, OnlyBrokerOrderRejectedUpdate):
        return OnlyOrderStatus.REJECTED
    if isinstance(update, OnlyBrokerOrderExpiredUpdate):
        return OnlyOrderStatus.EXPIRED
    raise TypeError(f"unsupported terminal update: {type(update).__name__}")


__all__ = [
    "OnlyBrokerOrderTerminalUpdate",
    "OnlyExecutionTerminalAuthority",
    "only_capture_execution_terminal_authority",
    "only_execution_terminal_status",
]
