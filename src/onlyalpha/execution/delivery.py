"""Runtime-owned execution event delivery boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.ports import (
    OnlyDirectEventPublicationPort,
    OnlyDurableEventPublicationPort,
    OnlyRuntimeEventDisposition,
)

from .event_buffer import OnlyExecutionEventBatch
from .persistence_ports import OnlyExecutionTransactionOutboxPort


class OnlyExecutionEventDeliveryMode(StrEnum):
    NONE = "NONE"
    DIRECT = "DIRECT"
    DURABLE_OUTBOX = "DURABLE_OUTBOX"


@dataclass(frozen=True, slots=True)
class OnlyExecutionEventDeliveryIntent:
    mode: OnlyExecutionEventDeliveryMode
    direct_batch: OnlyExecutionEventBatch | None = None
    committed_execution_sequence: int | None = None

    def __post_init__(self) -> None:
        if self.mode is OnlyExecutionEventDeliveryMode.NONE:
            valid = self.direct_batch is None and self.committed_execution_sequence is None
        elif self.mode is OnlyExecutionEventDeliveryMode.DIRECT:
            valid = self.direct_batch is not None and self.committed_execution_sequence is None
        else:
            valid = self.direct_batch is None and self.committed_execution_sequence is not None
        if not valid:
            raise ValueError(f"invalid {self.mode.value} execution event delivery intent")


@dataclass(frozen=True, slots=True)
class OnlyDirectEventDeliveryResult:
    attempted: int
    published: int
    staged: int
    suppressed: int
    failed: int
    error: str | None


@dataclass(frozen=True, slots=True)
class OnlyOutboxPublishResult:
    attempted: int
    published: int
    failed: int
    remaining: int
    stopped_on_error: bool
    last_error: str | None


@dataclass(frozen=True, slots=True)
class OnlyExecutionEventDeliveryResult:
    mode: OnlyExecutionEventDeliveryMode
    attempted: int
    published: int
    staged: int
    suppressed: int
    failed: int
    remaining: int
    stopped_on_error: bool
    last_error: str | None


@dataclass(frozen=True, slots=True)
class OnlyExecutionDeliveryDiagnostic:
    runtime_id: OnlyRuntimeId
    processing_sequence: int | None
    delivery_mode: OnlyExecutionEventDeliveryMode
    attempted: int
    published: int
    staged: int
    suppressed: int
    failed: int
    remaining: int
    last_error: str | None
    timestamp: OnlyTimestamp


class OnlyDirectExecutionEventPublisher(Protocol):
    def publish(self, batch: OnlyExecutionEventBatch) -> OnlyDirectEventDeliveryResult: ...


class OnlyRoutedDirectExecutionPublisher:
    """Best-effort non-durable publication through the Runtime direct port."""

    def __init__(self, publisher: OnlyDirectEventPublicationPort) -> None:
        self._publisher = publisher

    def publish(self, batch: OnlyExecutionEventBatch) -> OnlyDirectEventDeliveryResult:
        try:
            result = self._publisher.publish_direct_many(batch.events)
        except Exception as exc:
            return OnlyDirectEventDeliveryResult(len(batch.events), 0, 0, 0, 1, f"{type(exc).__name__}: {exc}")
        failed = result.rejected
        return OnlyDirectEventDeliveryResult(
            result.attempted,
            result.published,
            result.staged,
            result.suppressed,
            failed,
            result.error,
        )


class OnlyExecutionOutboxPublisher:
    """Ordered at-least-once publication of already committed events."""

    def __init__(
        self,
        outbox: OnlyExecutionTransactionOutboxPort,
        publisher: OnlyDurableEventPublicationPort,
        now: Callable[[], OnlyTimestamp],
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._now = now

    def publish_pending(self, runtime_id: OnlyRuntimeId, *, limit: int = 100) -> OnlyOutboxPublishResult:
        attempted = published = failed = 0
        last_error: str | None = None
        for record in self._outbox.pending(runtime_id, limit=limit):
            attempted_at = self._now()
            self._outbox.begin_attempt(record.key, attempted_at)
            attempted += 1
            try:
                result = self._publisher.publish_durable(record.event)
                if result.disposition is not OnlyRuntimeEventDisposition.PUBLISHED:
                    raise RuntimeError(f"durable event was not published: {result.disposition.value}")
                self._outbox.mark_published(record.key, self._now())
                published += 1
            except Exception as exc:
                failed += 1
                last_error = f"{type(exc).__name__}: {exc}"
                try:
                    self._outbox.mark_failed(record.key, self._now(), last_error)
                except Exception as mark_exc:
                    last_error = f"{last_error}; mark_failed {type(mark_exc).__name__}: {mark_exc}"
                break
        remaining = self._outbox.pending_count(runtime_id)
        return OnlyOutboxPublishResult(attempted, published, failed, remaining, failed > 0, last_error)


class OnlyExecutionEventDeliveryCoordinator:
    """The sole Runtime scheduler for execution event delivery."""

    def __init__(
        self,
        direct_publisher: OnlyDirectExecutionEventPublisher,
        outbox_publisher: OnlyExecutionOutboxPublisher,
    ) -> None:
        self._direct_publisher = direct_publisher
        self._outbox_publisher = outbox_publisher

    def deliver(
        self, runtime_id: OnlyRuntimeId, intent: OnlyExecutionEventDeliveryIntent
    ) -> OnlyExecutionEventDeliveryResult:
        if intent.mode is OnlyExecutionEventDeliveryMode.NONE:
            return OnlyExecutionEventDeliveryResult(intent.mode, 0, 0, 0, 0, 0, 0, False, None)
        if intent.mode is OnlyExecutionEventDeliveryMode.DIRECT:
            if intent.direct_batch is None:
                raise AssertionError("validated DIRECT intent lost its batch")
            direct_result = self._direct_publisher.publish(intent.direct_batch)
            return OnlyExecutionEventDeliveryResult(
                intent.mode,
                direct_result.attempted,
                direct_result.published,
                direct_result.staged,
                direct_result.suppressed,
                direct_result.failed,
                0,
                direct_result.failed > 0,
                direct_result.error,
            )
        outbox_result = self._outbox_publisher.publish_pending(runtime_id)
        return OnlyExecutionEventDeliveryResult(
            intent.mode,
            outbox_result.attempted,
            outbox_result.published,
            0,
            0,
            outbox_result.failed,
            outbox_result.remaining,
            outbox_result.stopped_on_error,
            outbox_result.last_error,
        )


__all__ = [
    "OnlyDirectEventDeliveryResult",
    "OnlyDirectExecutionEventPublisher",
    "OnlyRoutedDirectExecutionPublisher",
    "OnlyExecutionDeliveryDiagnostic",
    "OnlyExecutionEventDeliveryCoordinator",
    "OnlyExecutionEventDeliveryIntent",
    "OnlyExecutionEventDeliveryMode",
    "OnlyExecutionEventDeliveryResult",
    "OnlyExecutionOutboxPublisher",
    "OnlyOutboxPublishResult",
]
