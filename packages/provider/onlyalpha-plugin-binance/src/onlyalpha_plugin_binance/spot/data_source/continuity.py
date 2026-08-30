"""Serialized Binance Spot continuity, bounded buffering and recovery proof."""

from __future__ import annotations

import threading
from collections.abc import Callable

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataConnectionState
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.data.processor import OnlyMarketDataDeduplicator, OnlyMarketDataSequenceTracker
from onlyalpha_plugin_binance.errors import OnlyBinanceError

type OnlyRecoveryLoader = Callable[[OnlyMarketDataInboundUpdate, int, int], tuple[OnlyMarketDataInboundUpdate, ...]]


class OnlyBinanceSpotContinuityCoordinator:
    """Owns every continuity mutation behind one atomic semantic-transition lock."""

    def __init__(self, max_buffer_events: int) -> None:
        if max_buffer_events <= 0:
            raise ValueError("BINANCE_RECOVERY_BUFFER_BOUND_INVALID")
        self._max_buffer_events = max_buffer_events
        self._lock = threading.RLock()
        self._state = OnlyMarketDataConnectionState.DISCONNECTED
        self._dedup = OnlyMarketDataDeduplicator()
        self._sequence = OnlyMarketDataSequenceTracker()
        self._buffer: list[OnlyMarketDataInboundUpdate] = []
        self._transport_connected = False
        self._subscription_established = False
        self._baseline_established = False
        self._recovery_pending = False
        self._continuity_proven = False

    @property
    def state(self) -> OnlyMarketDataConnectionState:
        with self._lock:
            return self._state

    @property
    def buffered_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def connected(self) -> None:
        with self._lock:
            self._transport_connected = True
            self._subscription_established = False
            self._baseline_established = False
            self._recovery_pending = False
            self._continuity_proven = False
            self._state = OnlyMarketDataConnectionState.CONNECTED

    def subscription_established(self) -> None:
        with self._lock:
            if not self._transport_connected or self._state is not OnlyMarketDataConnectionState.CONNECTED:
                raise OnlyBinanceError("BINANCE_SUBSCRIPTION_STATE_INVALID")
            self._subscription_established = True

    def begin_recovery(self) -> None:
        with self._lock:
            if not self._transport_connected or not self._subscription_established:
                raise OnlyBinanceError("BINANCE_RECOVERY_EVIDENCE_MISSING")
            self._enter_recovery_locked()

    def establish_empty_baseline(self) -> None:
        with self._lock:
            self._require_recovering_locked()
            self._baseline_established = True

    def complete_recovery(self, recover: OnlyRecoveryLoader | None = None) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        """Derive READY only after baseline and the buffered suffix are reconciled."""
        with self._lock:
            self._require_recovering_locked()
            ordered = tuple(sorted(self._buffer, key=self._order_key))
            self._buffer.clear()
            accepted: list[OnlyMarketDataInboundUpdate] = []
            for item in ordered:
                accepted.extend(self._accept_locked(item, recover))
            if self._state is OnlyMarketDataConnectionState.FAILED:
                raise OnlyBinanceError("BINANCE_CONTINUITY_FAILED")
            if self._buffer:
                raise OnlyBinanceError("BINANCE_CONTINUITY_UNPROVEN")
            self._recovery_pending = False
            self._continuity_proven = True
            self._prove_ready_locked()
            self._state = OnlyMarketDataConnectionState.READY
            return tuple(accepted)

    def disconnected(self) -> None:
        with self._lock:
            self._transport_connected = False
            self._subscription_established = False
            self._baseline_established = False
            self._recovery_pending = False
            self._continuity_proven = False
            if self._state is not OnlyMarketDataConnectionState.FAILED:
                self._state = OnlyMarketDataConnectionState.DISCONNECTED

    def fail(self) -> None:
        with self._lock:
            self._continuity_proven = False
            self._state = OnlyMarketDataConnectionState.FAILED

    def buffer(self, update: OnlyMarketDataInboundUpdate) -> None:
        with self._lock:
            self._buffer_locked(update)

    def _buffer_locked(self, update: OnlyMarketDataInboundUpdate) -> None:
        self._require_recovering_locked()
        if len(self._buffer) >= self._max_buffer_events:
            self.fail()
            raise OnlyBinanceError("RECOVERY_BUFFER_OVERFLOW")
        self._buffer.append(update)

    def accept(
        self,
        update: OnlyMarketDataInboundUpdate,
        recover: OnlyRecoveryLoader | None = None,
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        """Atomically order a realtime fact against recovery and READY cutover."""
        with self._lock:
            if self._state is OnlyMarketDataConnectionState.RECOVERING:
                self._buffer_locked(update)
                return ()
            if self._state is not OnlyMarketDataConnectionState.READY:
                raise OnlyBinanceError("BINANCE_CONTINUITY_NOT_READY")
            return self._accept_locked(update, recover)

    def _accept_locked(
        self,
        update: OnlyMarketDataInboundUpdate,
        recover: OnlyRecoveryLoader | None,
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        was_ready = self._state is OnlyMarketDataConnectionState.READY
        if self._dedup.contains(update):
            return ()
        assessment = self._sequence.assess(update)
        if assessment.stale:
            return ()
        recovered: tuple[OnlyMarketDataInboundUpdate, ...] = ()
        if assessment.gap:
            self._enter_recovery_locked()
            if recover is None or update.sequence_semantics is not OnlyDataSequenceSemantics.CONTIGUOUS:
                self._buffer_locked(update)
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
            recovered = tuple(
                sorted(recover(update, previous + 1, int(update.source_sequence) - 1), key=self._order_key)
            )
            expected_sequences = tuple(range(previous + 1, int(update.source_sequence)))
            if tuple(int(item.source_sequence) for item in recovered) != expected_sequences or any(
                item.sequence_scope != scope for item in recovered
            ):
                self._buffer_locked(update)
                return ()
            for item in recovered:
                self._commit(item)
        self._commit(update)
        if was_ready:
            self._recovery_pending = False
            self._continuity_proven = True
            self._prove_ready_locked()
            self._state = OnlyMarketDataConnectionState.READY
        return (*recovered, update)

    def accept_baseline(
        self,
        update: OnlyMarketDataInboundUpdate,
        recover: OnlyRecoveryLoader | None = None,
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        with self._lock:
            self._require_recovering_locked()
            checkpoint = self._sequence.capture_checkpoint()
            has_scope = (
                isinstance(checkpoint, list)
                and update.sequence_scope is not None
                and any(
                    isinstance(item, dict) and item.get("scope") == update.sequence_scope.to_dict()
                    for item in checkpoint
                )
            )
            if has_scope:
                accepted = self._accept_locked(update, recover)
            elif self._dedup.contains(update):
                accepted = ()
            else:
                self._commit(update)
                accepted = (update,)
            self._baseline_established = True
            return accepted

    def _enter_recovery_locked(self) -> None:
        self._state = OnlyMarketDataConnectionState.RECOVERING
        self._recovery_pending = True
        self._continuity_proven = False

    def _require_recovering_locked(self) -> None:
        if self._state is not OnlyMarketDataConnectionState.RECOVERING:
            raise OnlyBinanceError("BINANCE_RECOVERY_STATE_INVALID")

    def _prove_ready_locked(self) -> None:
        if not (
            self._transport_connected
            and self._subscription_established
            and self._baseline_established
            and not self._recovery_pending
            and self._continuity_proven
            and not self._buffer
        ):
            raise OnlyBinanceError("BINANCE_READY_INVARIANT_UNPROVEN")

    def _commit(self, update: OnlyMarketDataInboundUpdate) -> None:
        self._dedup.remember(update)
        self._sequence.commit(update)

    @staticmethod
    def _order_key(update: OnlyMarketDataInboundUpdate) -> tuple[str, int, str]:
        return (str(update.sequence_scope), int(update.source_sequence), str(update.update_id))
