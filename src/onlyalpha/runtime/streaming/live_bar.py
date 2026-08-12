"""Finalize mutable live period snapshots exactly once at the next period boundary."""

from dataclasses import replace

from onlyalpha.data.identifiers import OnlyDataSequence
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp


class OnlyLiveBarFinalizationError(RuntimeError):
    """A live Bar cannot be ordered without revising already accepted state."""


class OnlyLiveBarFinalizer:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, str, OnlyBarType], OnlyMarketDataInboundUpdate] = {}
        self._closed_sequences: dict[tuple[str, str], int] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def seed_closed_sequences(self, updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        for update in updates:
            key = (str(update.source_id), str(update.instrument_id))
            self._closed_sequences[key] = max(
                self._closed_sequences.get(key, 0),
                int(update.source_sequence),
            )

    def reset_pending(self) -> None:
        """Discard mutable, unconfirmed live periods at a recovery boundary."""
        self._pending.clear()

    def accept(self, update: OnlyMarketDataInboundUpdate) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        if not isinstance(update.payload, OnlyBarUpdate):
            return (update,)
        bar = update.payload.bar
        if bar.is_closed:
            return (update,)
        key = (str(update.source_id), str(update.instrument_id), bar.bar_type)
        pending = self._pending.get(key)
        if pending is None:
            self._pending[key] = update
            return ()
        previous = pending.payload
        if not isinstance(previous, OnlyBarUpdate):
            raise AssertionError("live Bar pending state must contain a Bar update")
        previous_bar = previous.bar
        if bar.bar_start < previous_bar.bar_start:
            raise OnlyLiveBarFinalizationError("out-of-order live Bar is older than the pending period")
        if bar.bar_start == previous_bar.bar_start:
            self._pending[key] = update
            return ()
        if bar.bar_start < previous_bar.bar_end:
            raise OnlyLiveBarFinalizationError("overlapping live Bar periods are not supported")
        self._pending[key] = update
        closed = self._close(previous_bar)
        sequence_key = (str(pending.source_id), str(pending.instrument_id))
        next_sequence = self._closed_sequences.get(sequence_key, 0) + 1
        self._closed_sequences[sequence_key] = next_sequence
        return (
            replace(
                pending,
                source_sequence=OnlyDataSequence(next_sequence),
                payload=OnlyBarUpdate(closed),
                ts_event=OnlyTimestamp.from_datetime(closed.ts_event),
                ts_init=update.ts_init,
            ),
        )

    @staticmethod
    def _close(bar: OnlyBar) -> OnlyBar:
        return replace(
            bar,
            ts_event=bar.bar_end,
            ts_init=bar.bar_end,
            is_closed=True,
        )
