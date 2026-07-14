"""Bounded synchronous FIFO event propagation with scoped subscriptions."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.event.model import OnlyEvent, OnlyEventPriority, OnlyEventScope, OnlyEventType

type OnlyEventHandler = Callable[[OnlyEvent], None]


class OnlyEventQueuePolicy(StrEnum):
    REJECT = "REJECT"
    FAIL_RUNTIME = "FAIL_RUNTIME"
    DROP_LOW_PRIORITY = "DROP_LOW_PRIORITY"


class OnlyEventBusError(OnlyLifecycleError):
    """Base EventBus lifecycle or delivery error."""


class OnlyEventCapacityError(OnlyEventBusError):
    """Raised when a bounded queue cannot accept a core event."""


class OnlyEventScopeError(OnlyEventBusError):
    """Raised when an event does not belong to this bus scope."""


class OnlyEventRuntimeFailure(OnlyEventBusError):
    """Raised when queue policy requires the owning Runtime to fail."""


@dataclass(frozen=True, order=True, slots=True)
class OnlySubscriptionId:
    value: UUID

    @classmethod
    def new(cls) -> OnlySubscriptionId:
        return cls(uuid4())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class OnlySubscription:
    subscription_id: OnlySubscriptionId
    event_type: OnlyEventType
    priority: OnlyEventPriority
    registration_sequence: int
    handler_name: str


@dataclass(frozen=True, slots=True)
class OnlyEventHandlerResult:
    subscription_id: OnlySubscriptionId
    handler_name: str
    succeeded: bool
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class OnlyEventDispatchResult:
    event: OnlyEvent
    handler_results: tuple[OnlyEventHandlerResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(result.succeeded for result in self.handler_results)


@dataclass(frozen=True, slots=True)
class OnlyEventFailure:
    event: OnlyEvent
    subscription_id: OnlySubscriptionId
    handler_name: str
    error: Exception


@dataclass(frozen=True, slots=True)
class OnlyDroppedEvent:
    """Observable replacement made by DROP_LOW_PRIORITY policy."""

    dropped: OnlyEvent
    accepted: OnlyEvent
    reason: str


@dataclass(slots=True)
class OnlyRegisteredHandler:
    subscription: OnlySubscription
    handler: OnlyEventHandler


class OnlyEventBus:
    """Single-thread dispatch, FIFO queue, explicit backpressure and scope."""

    def __init__(
        self,
        capacity: int = 1024,
        *,
        scope: OnlyEventScope | None = None,
        queue_policy: OnlyEventQueuePolicy = OnlyEventQueuePolicy.REJECT,
    ) -> None:
        if capacity <= 0:
            raise ValueError("event bus capacity must be positive")
        self._capacity = capacity
        self._scope = scope
        self._queue_policy = queue_policy
        self._queue: deque[OnlyEvent] = deque()
        self._handlers: dict[OnlyEventType, list[OnlyRegisteredHandler]] = defaultdict(list)
        self._subscriptions: dict[OnlySubscriptionId, OnlyRegisteredHandler] = {}
        self._failures: list[OnlyEventFailure] = []
        self._dispatch_results: list[OnlyEventDispatchResult] = []
        self._dropped_events: list[OnlyDroppedEvent] = []
        self._registration_sequence = 0
        self._accepting = True
        self._lock = RLock()

    @property
    def failures(self) -> tuple[OnlyEventFailure, ...]:
        with self._lock:
            return tuple(self._failures)

    @property
    def dispatch_results(self) -> tuple[OnlyEventDispatchResult, ...]:
        with self._lock:
            return tuple(self._dispatch_results)

    @property
    def dropped_events(self) -> tuple[OnlyDroppedEvent, ...]:
        with self._lock:
            return tuple(self._dropped_events)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def subscribe(
        self,
        event_type: OnlyEventType | str,
        handler: OnlyEventHandler,
        *,
        priority: OnlyEventPriority = OnlyEventPriority.NORMAL,
    ) -> OnlySubscription:
        normalized_type = event_type if isinstance(event_type, OnlyEventType) else OnlyEventType(event_type)
        with self._lock:
            if not self._accepting:
                raise OnlyEventBusError("event bus is closed")
            self._registration_sequence += 1
            subscription = OnlySubscription(
                OnlySubscriptionId.new(),
                normalized_type,
                priority,
                self._registration_sequence,
                getattr(handler, "__qualname__", repr(handler)),
            )
            registered = OnlyRegisteredHandler(subscription, handler)
            self._handlers[normalized_type].append(registered)
            self._handlers[normalized_type].sort(
                key=lambda item: (-int(item.subscription.priority), item.subscription.registration_sequence)
            )
            self._subscriptions[subscription.subscription_id] = registered
            return subscription

    def unsubscribe(self, subscription_id: OnlySubscriptionId) -> bool:
        with self._lock:
            registered = self._subscriptions.pop(subscription_id, None)
            if registered is None:
                return False
            handlers = self._handlers[registered.subscription.event_type]
            handlers.remove(registered)
            return True

    def publish(self, event: OnlyEvent) -> bool:
        with self._lock:
            if not self._accepting:
                raise OnlyEventBusError("event bus is closed")
            self._require_scope(event)
            if len(self._queue) >= self._capacity:
                return self._handle_capacity(event)
            self._queue.append(event)
            return True

    def publish_many(self, events: Iterable[OnlyEvent]) -> int:
        published = 0
        for event in events:
            published += int(self.publish(event))
        return published

    def dispatch(self) -> OnlyEventDispatchResult | None:
        with self._lock:
            if not self._queue:
                return None
            event = self._queue.popleft()
            event_type = (
                event.event_type if isinstance(event.event_type, OnlyEventType) else OnlyEventType(event.event_type)
            )
            handlers = tuple(self._handlers.get(event_type, ()))
        results: list[OnlyEventHandlerResult] = []
        for registered in handlers:
            subscription = registered.subscription
            try:
                registered.handler(event)
                results.append(OnlyEventHandlerResult(subscription.subscription_id, subscription.handler_name, True))
            except Exception as exc:
                failure = OnlyEventFailure(
                    event,
                    subscription.subscription_id,
                    subscription.handler_name,
                    exc,
                )
                with self._lock:
                    self._failures.append(failure)
                results.append(
                    OnlyEventHandlerResult(subscription.subscription_id, subscription.handler_name, False, exc)
                )
        dispatch_result = OnlyEventDispatchResult(event, tuple(results))
        with self._lock:
            self._dispatch_results.append(dispatch_result)
        return dispatch_result

    def drain(self) -> int:
        handled = 0
        while self.dispatch() is not None:
            handled += 1
        return handled

    def close(self) -> None:
        with self._lock:
            if not self._accepting:
                return
            self._accepting = False
        self.drain()

    def _require_scope(self, event: OnlyEvent) -> None:
        if self._scope is not None and not self._scope.includes(event.scope):
            raise OnlyEventScopeError(f"event scope {event.scope} does not belong to bus scope {self._scope}")

    def _handle_capacity(self, event: OnlyEvent) -> bool:
        if self._queue_policy is OnlyEventQueuePolicy.FAIL_RUNTIME:
            raise OnlyEventRuntimeFailure("event bus capacity exceeded")
        if self._queue_policy is OnlyEventQueuePolicy.DROP_LOW_PRIORITY:
            candidates = [
                (queued.priority, index) for index, queued in enumerate(self._queue) if queued.priority < event.priority
            ]
            if candidates:
                _, index = min(candidates, key=lambda item: (int(item[0]), item[1]))
                dropped = self._queue[index]
                del self._queue[index]
                self._queue.append(event)
                self._dropped_events.append(
                    OnlyDroppedEvent(dropped, event, "replaced lower-priority event at bounded capacity")
                )
                return True
        raise OnlyEventCapacityError("event bus capacity exceeded")
