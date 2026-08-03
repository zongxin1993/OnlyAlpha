"""Normalize XtQuant live callbacks before entering the Runtime queue."""

from datetime import datetime, timedelta
from typing import Any

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyQuoteTickUpdate,
)
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyQuoteTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ..mapping.market_data import quantized_decimal, utc_from_xt, valid_ohlc


class OnlyMiniQmtLiveNormalizer:
    def __init__(self, request: OnlyDataSourceCreateRequest) -> None:
        self._request = request
        self._sequence = 0

    def set_sequence_floor(self, sequence: int) -> None:
        if sequence < self._sequence:
            raise ValueError("live sequence floor cannot move backwards")
        self._sequence = sequence

    @staticmethod
    def period(bar_type: OnlyBarType) -> str:
        from .historical import PERIODS

        period = PERIODS.get(bar_type.specification.step)
        if period is None:
            raise ValueError(f"unsupported MiniQMT period: {bar_type.specification.step}m")
        return period

    def publish(self, raw: Any, instrument_id: OnlyInstrumentId, period: str) -> None:
        sink = self._request.market_data_sink
        if sink is None:
            raise RuntimeError("Runtime market_data_sink is required")
        for row in self._rows(raw):
            update = self._quote(row, instrument_id) if period == "tick" else self._bar(row, instrument_id, period)
            sink(update)

    def _quote(self, row: dict[str, Any], instrument_id: OnlyInstrumentId) -> OnlyMarketDataInboundUpdate:
        event = utc_from_xt(row["time"])
        bids, asks = row.get("bidPrice", ()), row.get("askPrice", ())
        bid_volumes, ask_volumes = row.get("bidVol", ()), row.get("askVol", ())
        quote = OnlyQuoteTick(
            instrument_id=instrument_id,
            ts_event=event,
            ts_init=event,
            sequence=self._sequence + 1,
            source="miniqmt",
            bid_price=OnlyPrice(quantized_decimal(bids[0], 4), 4),
            bid_quantity=OnlyQuantity(quantized_decimal(bid_volumes[0], 0), 0),
            ask_price=OnlyPrice(quantized_decimal(asks[0], 4), 4),
            ask_quantity=OnlyQuantity(quantized_decimal(ask_volumes[0], 0), 0),
        )
        return self._envelope(instrument_id, event, OnlyMarketDataType.QUOTE, OnlyQuoteTickUpdate(quote))

    def _bar(self, row: dict[str, Any], instrument_id: OnlyInstrumentId, period: str) -> OnlyMarketDataInboundUpdate:
        if not valid_ohlc(row):
            raise ValueError("invalid live MiniQMT OHLC")
        event = utc_from_xt(row["time"])
        bar_type = self._request.bar_types[instrument_id]
        precision = self._request.instruments[instrument_id].price_precision
        minutes = bar_type.specification.step
        bar = OnlyBar(
            bar_type=bar_type,
            open=OnlyPrice(quantized_decimal(row["open"], precision), precision),
            high=OnlyPrice(quantized_decimal(row["high"], precision), precision),
            low=OnlyPrice(quantized_decimal(row["low"], precision), precision),
            close=OnlyPrice(quantized_decimal(row["close"], precision), precision),
            volume=OnlyQuantity(quantized_decimal(row.get("volume", 0), 0), 0),
            quote_volume=None,
            turnover=None,
            trade_count=None,
            open_interest=None,
            bar_start=event,
            bar_end=event + timedelta(minutes=minutes),
            ts_event=event,
            ts_init=event,
            # XtQuant may publish the same period repeatedly. The Runtime-owned
            # live finalizer is the sole authority that closes it on T+1.
            is_closed=False,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=event.date(),
            session_type=OnlySessionType.REGULAR,
        )
        return self._envelope(instrument_id, event, OnlyMarketDataType.BAR, OnlyBarUpdate(bar))

    def _envelope(
        self,
        instrument_id: OnlyInstrumentId,
        event: datetime,
        data_type: OnlyMarketDataType,
        payload: OnlyBarUpdate | OnlyQuoteTickUpdate,
    ) -> OnlyMarketDataInboundUpdate:
        self._sequence += 1
        stamp = OnlyTimestamp.from_datetime(event)
        return OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId(f"miniqmt-live-{self._sequence}"),
            runtime_id=self._request.runtime_id,
            source_id=self._request.source_id,
            source_sequence=OnlyDataSequence(self._sequence),
            data_version=self._request.data_version,
            instrument_id=instrument_id,
            data_type=data_type,
            payload=payload,
            ts_event=stamp,
            ts_init=stamp,
        )

    @staticmethod
    def _rows(raw: Any) -> tuple[dict[str, Any], ...]:
        if not isinstance(raw, dict):
            return ()
        rows: list[dict[str, Any]] = []
        for value in raw.values():
            if isinstance(value, dict):
                rows.append(value)
            elif isinstance(value, (list, tuple)):
                rows.extend(item for item in value if isinstance(item, dict))
        return tuple(rows)
