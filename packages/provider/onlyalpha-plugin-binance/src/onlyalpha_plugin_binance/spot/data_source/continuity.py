"""In-process Binance continuity, bounded buffering and recovery barrier."""

from __future__ import annotations

from collections.abc import Callable

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataConnectionState
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.data.processor import OnlyMarketDataDeduplicator, OnlyMarketDataSequenceTracker
from onlyalpha_plugin_binance.errors import OnlyBinanceError

type OnlyRecoveryLoader = Callable[[OnlyMarketDataInboundUpdate, int, int], tuple[OnlyMarketDataInboundUpdate, ...]]


class OnlyBinanceSpotContinuityCoordinator:
    def __init__(self, max_buffer_events: int) -> None:
        if max_buffer_events <= 0:
            raise ValueError("BINANCE_RECOVERY_BUFFER_BOUND_INVALID")
        self._max_buffer_events = max_buffer_events
        self._state = OnlyMarketDataConnectionState.DISCONNECTED
        self._dedup = OnlyMarketDataDeduplicator()
        self._sequence = OnlyMarketDataSequenceTracker()
        self._buffer: list[OnlyMarketDataInboundUpdate] = []

    @property
    def state(self) -> OnlyMarketDataConnectionState:
        return self._state

    def connected(self) -> None:
        self._state = OnlyMarketDataConnectionState.CONNECTED

    def begin_recovery(self) -> None:
        self._state = OnlyMarketDataConnectionState.RECOVERING

    def ready(self, recover: OnlyRecoveryLoader | None = None) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        if self._state is not OnlyMarketDataConnectionState.RECOVERING:
            raise OnlyBinanceError("BINANCE_READY_BARRIER_INVALID")
        ordered = tuple(sorted(self._buffer, key=self._order_key))
        self._buffer.clear()
        accepted: list[OnlyMarketDataInboundUpdate] = []
        for item in ordered:
            accepted.extend(self.accept(item, recover))
        if self._buffer:
            raise OnlyBinanceError("BINANCE_CONTINUITY_UNPROVEN")
        self._state = OnlyMarketDataConnectionState.READY
        return tuple(accepted)

    def disconnected(self) -> None:
        self._state = OnlyMarketDataConnectionState.DISCONNECTED

    def fail(self) -> None:
        self._state = OnlyMarketDataConnectionState.FAILED

    def buffer(self, update: OnlyMarketDataInboundUpdate) -> None:
        if len(self._buffer) >= self._max_buffer_events:
            self.fail()
            raise OnlyBinanceError("RECOVERY_BUFFER_OVERFLOW")
        self._buffer.append(update)

    def accept(
        self,
        update: OnlyMarketDataInboundUpdate,
        recover: OnlyRecoveryLoader | None = None,
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        was_ready = self._state is OnlyMarketDataConnectionState.READY
        if self._dedup.contains(update):
            return ()
        assessment = self._sequence.assess(update)
        if assessment.stale:
            return ()
        recovered: tuple[OnlyMarketDataInboundUpdate, ...] = ()
        if assessment.gap:
            if recover is None or update.sequence_semantics is not OnlyDataSequenceSemantics.CONTIGUOUS:
                self.begin_recovery()
                self.buffer(update)
                return ()
            scope = update.sequence_scope
            if scope is None:
                raise OnlyBinanceError("BINANCE_SEQUENCE_SCOPE_MISSING")
            checkpoint = self._sequence.capture_checkpoint()
            if not isinstance(checkpoint, list):
                raise OnlyBinanceError("BINANCE_RECOVERY_CHECKPOINT_INVALID")
            previous = next(
                (
                    int(item["sequence"])
                    for item in checkpoint
                    if isinstance(item, dict) and item.get("scope") == scope.to_dict()
                ),
                None,
            )
            if previous is None:
                raise OnlyBinanceError("BINANCE_RECOVERY_BASELINE_MISSING")
            self.begin_recovery()
            recovered = recover(update, previous + 1, int(update.source_sequence) - 1)
            ordered_recovered = tuple(sorted(recovered, key=self._order_key))
            expected_sequences = tuple(range(previous + 1, int(update.source_sequence)))
            if tuple(int(item.source_sequence) for item in ordered_recovered) != expected_sequences or any(
                item.sequence_scope != scope for item in ordered_recovered
            ):
                self.buffer(update)
                return ()
            for item in ordered_recovered:
                self._commit(item)
            recovered = ordered_recovered
        self._commit(update)
        if was_ready and self._state is OnlyMarketDataConnectionState.RECOVERING:
            self._state = OnlyMarketDataConnectionState.READY
        return (*recovered, update)

    def accept_baseline(self, update: OnlyMarketDataInboundUpdate) -> None:
        if self._state is not OnlyMarketDataConnectionState.RECOVERING:
            raise OnlyBinanceError("BINANCE_BASELINE_STATE_INVALID")
        if not self._dedup.contains(update):
            self._commit(update)

    def _commit(self, update: OnlyMarketDataInboundUpdate) -> None:
        self._dedup.remember(update)
        self._sequence.commit(update)

    @staticmethod
    def _order_key(update: OnlyMarketDataInboundUpdate) -> tuple[str, int, str]:
        return (str(update.sequence_scope), int(update.source_sequence), str(update.update_id))
