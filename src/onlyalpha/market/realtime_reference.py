"""Provider-neutral in-process realtime market-reference authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges, only_missing_ranges
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyMarketReferenceTick, OnlyTradeTick
from onlyalpha.domain.time import only_require_utc
from onlyalpha.market.models import OnlyCompiledDynamicPriceRequirement


@dataclass(frozen=True, slots=True)
class OnlyRealtimeMarketReferenceResolution:
    price: Decimal | None
    evidence_kind: str
    coverage: OnlyTimeRange | None
    as_of: datetime
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.price is not None


class OnlyRealtimeMarketReferenceAuthority:
    """Owns ephemeral reference/trade evidence; P9.3 owns durable revisions."""

    def __init__(self) -> None:
        self._references: dict[OnlyInstrumentId, list[OnlyMarketReferenceTick]] = {}
        self._trades: dict[OnlyInstrumentId, dict[str, OnlyTradeTick]] = {}
        self._trade_coverage: dict[OnlyInstrumentId, tuple[OnlyTimeRange, ...]] = {}

    def ingest_reference(self, reference: OnlyMarketReferenceTick) -> None:
        values = self._references.setdefault(reference.instrument_id, [])
        if reference not in values:
            values.append(reference)
            values.sort(key=lambda item: (item.ts_event, item.sequence))

    def ingest_trade(self, trade: OnlyTradeTick) -> None:
        values = self._trades.setdefault(trade.instrument_id, {})
        identity = str(trade.trade_id)
        existing = values.get(identity)
        if existing is not None and existing != trade:
            raise ValueError("MARKET_REFERENCE_TRADE_IDENTITY_CONFLICT")
        values[identity] = trade

    def prove_trade_coverage(self, instrument_id: OnlyInstrumentId, coverage: OnlyTimeRange) -> None:
        self._trade_coverage[instrument_id] = only_merge_ranges(
            (*self._trade_coverage.get(instrument_id, ()), coverage)
        )

    def resolve(
        self,
        requirement: OnlyCompiledDynamicPriceRequirement,
        instrument_id: OnlyInstrumentId,
        as_of: datetime,
    ) -> OnlyRealtimeMarketReferenceResolution:
        only_require_utc(as_of, "market reference as_of")
        reference = next(
            (item for item in reversed(self._references.get(instrument_id, [])) if item.ts_event <= as_of),
            None,
        )
        if reference is not None and reference.price is not None:
            return OnlyRealtimeMarketReferenceResolution(
                reference.price.value,
                "VENUE_REFERENCE_PRICE",
                None,
                as_of,
            )
        if requirement.reference_kind == "VENUE_REFERENCE_PRICE":
            reason = (
                "venue reference explicitly reports no price"
                if reference is not None
                else "venue reference fact is unavailable"
            )
            return self._unavailable(as_of, reason)
        if requirement.reference_kind != "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE":
            return self._unavailable(as_of, "unsupported market reference requirement")
        window_minutes = requirement.reference_window_minutes
        if window_minutes is None:
            return self._unavailable(as_of, "trade reference window is unspecified")
        trades = tuple(
            sorted(
                (item for item in self._trades.get(instrument_id, {}).values() if item.ts_event <= as_of),
                key=lambda item: (item.ts_event, str(item.trade_id)),
            )
        )
        if window_minutes == 0:
            if not trades:
                return self._unavailable(as_of, "previous Trade is unavailable")
            return OnlyRealtimeMarketReferenceResolution(
                trades[-1].price.value,
                "PREVIOUS_TRADE",
                None,
                as_of,
            )
        window = OnlyTimeRange(as_of - timedelta(minutes=window_minutes), as_of)
        if only_missing_ranges(window, self._trade_coverage.get(instrument_id, ())):
            return self._unavailable(as_of, "Trade window coverage is incomplete", window)
        included = tuple(item for item in trades if window.contains(item.ts_event))
        total_quantity = sum((item.quantity.value for item in included), Decimal(0))
        if not included or total_quantity <= 0:
            return self._unavailable(as_of, "Trade window has no valid facts", window)
        vwap = sum((item.price.value * item.quantity.value for item in included), Decimal(0)) / total_quantity
        return OnlyRealtimeMarketReferenceResolution(vwap, "TRADE_VWAP", window, as_of)

    @staticmethod
    def _unavailable(
        as_of: datetime,
        reason: str,
        coverage: OnlyTimeRange | None = None,
    ) -> OnlyRealtimeMarketReferenceResolution:
        return OnlyRealtimeMarketReferenceResolution(
            None,
            "MARKET_REFERENCE_UNAVAILABLE",
            coverage,
            as_of,
            reason,
        )
