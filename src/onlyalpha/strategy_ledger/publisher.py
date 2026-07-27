"""Strategy Ledger publisher implementations."""

from collections.abc import Callable

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.event.model import OnlyEvent
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEvent


class OnlyNoOpStrategyLedgerEventPublisher:
    def publish(self, event: OnlyStrategyLedgerEvent) -> None:
        del event


class OnlyInMemoryStrategyLedgerEventPublisher:
    def __init__(self) -> None:
        self.events: list[OnlyStrategyLedgerEvent] = []

    def publish(self, event: OnlyStrategyLedgerEvent) -> None:
        self.events.append(event)


class OnlyRuntimeStrategyLedgerEventPublisherAdapter:
    """Converts component facts to the shared immutable Runtime envelope."""

    def __init__(self, engine_id: OnlyEngineId, publish_event: Callable[[OnlyEvent], None]) -> None:
        self.__engine_id = engine_id
        self.__publish_event = publish_event

    def publish(self, event: OnlyStrategyLedgerEvent) -> None:
        self.__publish_event(
            OnlyEvent(
                event.event_type,
                event.timestamp.to_datetime(),
                self.__engine_id,
                event.key.runtime_id,
                "strategy_ledger",
                event.sequence,
                event,
                cluster_id=event.key.cluster_id,
                timestamp_ns=event.timestamp.unix_nanos,
                ts_init_ns=event.timestamp.unix_nanos,
            )
        )
