"""Stable identity authority for durable Broker Order Accepted facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate


@dataclass(frozen=True, slots=True)
class OnlyExecutionOrderAcceptedAuthority:
    accepted_identity: str
    payload_fingerprint: str

    def __post_init__(self) -> None:
        if not self.accepted_identity.startswith("EACK-"):
            raise ValueError("accepted identity must use the EACK prefix")
        if len(self.payload_fingerprint) != 64:
            raise ValueError("accepted payload fingerprint must be SHA-256")


def only_capture_execution_order_accepted_authority(
    update: OnlyBrokerOrderAcceptedUpdate,
) -> OnlyExecutionOrderAcceptedAuthority:
    identity_payload = "\x1f".join(
        (
            str(update.runtime_id),
            str(update.gateway_id),
            str(update.account_id),
            str(update.order_id),
            str(update.update_id),
            OnlyBrokerOrderAcceptedUpdate.__name__,
        )
    )
    identity = f"EACK-{hashlib.sha256(identity_payload.encode('utf-8')).hexdigest()}"
    payload = json.dumps(update.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return OnlyExecutionOrderAcceptedAuthority(
        identity,
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


__all__ = [
    "OnlyExecutionOrderAcceptedAuthority",
    "only_capture_execution_order_accepted_authority",
]
