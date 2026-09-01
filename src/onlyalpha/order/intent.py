"""Narrow Order port for the Runtime-owned durable intent barrier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp

if TYPE_CHECKING:
    from onlyalpha.execution.reference import OnlyExecutionReferenceEvidence


@dataclass(frozen=True, slots=True)
class OnlyRuntimeIntentReference:
    transaction_id: str
    authority_hash: str


@dataclass(frozen=True, slots=True)
class OnlyOrderIntentDurabilityResult:
    ready: bool
    reference: OnlyRuntimeIntentReference | None
    error: str | None = None


class OnlyOrderIntentDurabilityPort(Protocol):
    def begin(
        self,
        request: OnlyOrderRequest,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        prepared_at: OnlyTimestamp,
        *,
        execution_reference: OnlyExecutionReferenceEvidence | None = None,
    ) -> object: ...

    def commit(self, token: object, order: OnlyOrderSnapshot) -> OnlyOrderIntentDurabilityResult: ...


class OnlyRuntimeIntentReferenceSink(Protocol):
    def record_runtime_intent(self, order_id: OnlyOrderId, reference: OnlyRuntimeIntentReference) -> None: ...


__all__ = [
    "OnlyOrderIntentDurabilityPort",
    "OnlyOrderIntentDurabilityResult",
    "OnlyRuntimeIntentReference",
    "OnlyRuntimeIntentReferenceSink",
]
