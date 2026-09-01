"""Runtime-owned projection of admitted realtime market facts."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.enums import OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import (
    OnlyDataSequenceScope,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataQuality, OnlyTradeTickUpdate
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyRealtimeTradeReference:
    """Exact admitted Trade fact retained by the realtime projection."""

    runtime_id: OnlyRuntimeId
    source_id: OnlyMarketDataSourceId
    instrument_id: OnlyInstrumentId
    data_version: OnlyDataVersion
    update_id: OnlyMarketDataUpdateId
    source_sequence: int
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    quality: OnlyMarketDataQuality
    trade: OnlyTradeTick
    processing_sequence: int

    @classmethod
    def from_update(
        cls,
        update: OnlyMarketDataInboundUpdate,
        quality: OnlyMarketDataQuality,
        processing_sequence: int,
    ) -> OnlyRealtimeTradeReference:
        if not isinstance(update.payload, OnlyTradeTickUpdate):
            raise TypeError("realtime Trade reference requires a Trade update")
        return cls(
            update.runtime_id,
            update.source_id,
            update.instrument_id,
            update.data_version,
            update.update_id,
            int(update.source_sequence),
            update.ts_event,
            update.ts_init,
            quality,
            update.payload.trade,
            processing_sequence,
        )

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "runtime_id": str(self.runtime_id),
            "source_id": str(self.source_id),
            "instrument_id": str(self.instrument_id),
            "data_version": str(self.data_version),
            "update_id": str(self.update_id),
            "source_sequence": self.source_sequence,
            "ts_event": self.ts_event.unix_nanos,
            "ts_init": self.ts_init.unix_nanos,
            "quality": sorted(item.value for item in self.quality.flags),
            "trade": self.trade.to_dict(),
            "processing_sequence": self.processing_sequence,
        }


@dataclass(frozen=True, slots=True)
class OnlyRealtimeMarketSnapshot:
    """Immutable, internally consistent capture for one planning cycle."""

    runtime_id: OnlyRuntimeId
    captured_at: OnlyTimestamp
    trades: tuple[OnlyRealtimeTradeReference, ...]
    unresolved_scopes: tuple[OnlyDataSequenceScope, ...]
    fingerprint: str

    def latest_trade(self, instrument_id: OnlyInstrumentId) -> OnlyRealtimeTradeReference | None:
        return next((item for item in self.trades if item.instrument_id == instrument_id), None)

    def has_unresolved_gap(self, reference: OnlyRealtimeTradeReference) -> bool:
        return (
            OnlyDataSequenceScope(
                reference.source_id,
                reference.instrument_id,
                OnlyMarketDataType.TRADE,
                None,
            )
            in self.unresolved_scopes
        )


class OnlyRealtimeMarketStateStore:
    """Sole Runtime projection authority; never a durable Market Fact store."""

    _invalid_quality = frozenset(
        {
            OnlyMarketDataQualityFlag.STALE,
            OnlyMarketDataQualityFlag.DUPLICATE,
            OnlyMarketDataQualityFlag.OUT_OF_ORDER,
            OnlyMarketDataQualityFlag.UNEXPECTED_GAP,
            OnlyMarketDataQualityFlag.SOURCE_CONFLICT,
            OnlyMarketDataQualityFlag.NON_DETERMINISTIC_SOURCE,
            OnlyMarketDataQualityFlag.PARTIAL,
        }
    )

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self._runtime_id = runtime_id
        self._lock = threading.RLock()
        self._trades: dict[tuple[OnlyMarketDataSourceId, OnlyInstrumentId], OnlyRealtimeTradeReference] = {}
        self._unresolved_scopes: dict[OnlyDataSequenceScope, int] = {}

    def apply_trade(
        self,
        update: OnlyMarketDataInboundUpdate,
        quality: OnlyMarketDataQuality,
        processing_sequence: int,
    ) -> OnlyRealtimeTradeReference:
        reference = OnlyRealtimeTradeReference.from_update(update, quality, processing_sequence)
        if reference.runtime_id != self._runtime_id:
            raise ValueError("REALTIME_MARKET_STATE_RUNTIME_SCOPE_MISMATCH")
        if self._invalid_quality.intersection(quality.flags):
            raise ValueError("REALTIME_MARKET_STATE_QUALITY_NOT_ADMITTED")
        scope = update.sequence_scope
        if scope is None:
            raise ValueError("REALTIME_MARKET_STATE_SEQUENCE_SCOPE_MISSING")
        key = (reference.source_id, reference.instrument_id)
        with self._lock:
            current = self._trades.get(key)
            if current is not None and reference.source_sequence <= current.source_sequence:
                raise ValueError("REALTIME_MARKET_STATE_NON_MONOTONIC_APPLY")
            self._trades[key] = reference
            recovery_target = self._unresolved_scopes.get(scope)
            if recovery_target is not None and reference.source_sequence >= recovery_target:
                self._unresolved_scopes.pop(scope)
        return reference

    def mark_gap(self, scope: OnlyDataSequenceScope, rejected_sequence: int) -> None:
        with self._lock:
            self._unresolved_scopes[scope] = max(rejected_sequence, self._unresolved_scopes.get(scope, 0))

    def capture(self, captured_at: OnlyTimestamp) -> OnlyRealtimeMarketSnapshot:
        with self._lock:
            trades = tuple(
                sorted(
                    self._trades.values(),
                    key=lambda item: (str(item.instrument_id), str(item.source_id)),
                )
            )
            unresolved = tuple(sorted(self._unresolved_scopes, key=lambda item: str(item.to_dict())))
        payload = {
            "runtime_id": str(self._runtime_id),
            "captured_at": captured_at.unix_nanos,
            "trades": [item.fingerprint_payload() for item in trades],
            "unresolved_scopes": [item.to_dict() for item in unresolved],
        }
        return OnlyRealtimeMarketSnapshot(
            self._runtime_id,
            captured_at,
            trades,
            unresolved,
            only_canonical_fingerprint(payload),
        )


__all__ = [name for name in globals() if name.startswith("Only")]
