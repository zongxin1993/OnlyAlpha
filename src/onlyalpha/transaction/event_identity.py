"""Deterministic identities and construction for durable execution events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid5

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.model import (
    OnlyCausationId,
    OnlyCorrelationId,
    OnlyEvent,
    OnlyEventId,
    OnlyEventPriority,
    OnlyEventSource,
    OnlyEventType,
)

_EXECUTION_EVENT_NAMESPACE = UUID("c7f52042-c48f-5ef2-9f3b-75373a72dc77")


def only_runtime_transaction_event_id(
    *, transaction_id: str, event_sequence: int, event_type: OnlyEventType
) -> OnlyEventId:
    if not transaction_id.strip() or event_sequence < 1:
        raise ValueError("durable execution event identity requires transaction and positive sequence")
    return OnlyEventId(uuid5(_EXECUTION_EVENT_NAMESPACE, f"{transaction_id}\x1f{event_sequence}\x1f{event_type}"))


class OnlyExecutionTransactionEventFactory:
    """Create a durable Event envelope with its deterministic identity installed."""

    def create(
        self,
        *,
        transaction_id: str,
        event_sequence: int,
        event_type: OnlyEventType,
        timestamp: datetime,
        engine_id: OnlyEngineId,
        runtime_id: OnlyRuntimeId,
        source: OnlyEventSource,
        payload: object,
        cluster_id: OnlyClusterId | None = None,
        metadata: Mapping[str, str] | None = None,
        ts_init: datetime | None = None,
        correlation_id: OnlyCorrelationId | None = None,
        causation_id: OnlyCausationId | None = None,
        priority: OnlyEventPriority = OnlyEventPriority.NORMAL,
    ) -> OnlyEvent:
        return OnlyEvent(
            event_type=event_type,
            timestamp=timestamp,
            engine_id=engine_id,
            runtime_id=runtime_id,
            source=source,
            sequence=event_sequence,
            payload=payload,
            cluster_id=cluster_id,
            metadata={} if metadata is None else metadata,
            event_id=only_runtime_transaction_event_id(
                transaction_id=transaction_id,
                event_sequence=event_sequence,
                event_type=event_type,
            ),
            ts_init=ts_init,
            correlation_id=correlation_id,
            causation_id=causation_id,
            priority=priority,
        )


__all__ = [
    "OnlyExecutionTransactionEventFactory",
    "only_runtime_transaction_event_id",
]
