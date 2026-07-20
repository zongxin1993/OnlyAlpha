"""Normalize XtQuant live callbacks before entering the Runtime queue."""

from datetime import timedelta

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyQuoteTickUpdate,
)
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.market import OnlyBar, OnlyQuoteTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity

from ..mapping.market_data import quantized_decimal, utc_from_xt, valid_ohlc


class OnlyMiniQmtLiveNormalizer:
    def __init__(self, request: object) -> None:
        self._request = request
        self._sequence = 0

    @staticmethod
    def period(bar_type: object) -> str:
        from .historical import PERIODS

        period = PERIODS.get(bar_type.specification.step)
        if period is None:
            raise ValueError(
                f"unsupported MiniQMT period: {bar_type.specification.step}m"
            )
        return period

    def publish(self, raw: object, instrument_id: object, period: str) -> None:
        for row in self._rows(raw):
            update = (
                self._quote(row, instrument_id)
                if period == "tick"
                else self._bar(row, instrument_id, period)
            )
            self._request.market_data_sink(update)

    def _quote(
        self, row: dict[str, object], instrument_id: object
    ) -> OnlyMarketDataInboundUpdate:
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
        return self._envelope(
            instrument_id, event, OnlyMarketDataType.QUOTE, OnlyQuoteTickUpdate(quote)
        )

    def _bar(
        self, row: dict[str, object], instrument_id: object, period: str
    ) -> OnlyMarketDataInboundUpdate:
        if not valid_ohlc(row):
            raise ValueError("invalid live MiniQMT OHLC")
        event = utc_from_xt(row["time"])
        bar_type = self._request.bar_types[instrument_id]
        minutes = bar_type.specification.step
        bar = OnlyBar(
            bar_type=bar_type,
            open=OnlyPrice(quantized_decimal(row["open"], 4), 4),
            high=OnlyPrice(quantized_decimal(row["high"], 4), 4),
            low=OnlyPrice(quantized_decimal(row["low"], 4), 4),
            close=OnlyPrice(quantized_decimal(row["close"], 4), 4),
            volume=OnlyQuantity(quantized_decimal(row.get("volume", 0), 0), 0),
            quote_volume=None,
            turnover=None,
            trade_count=None,
            open_interest=None,
            bar_start=event,
            bar_end=event + timedelta(minutes=minutes),
            ts_event=event,
            ts_init=event,
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=event.date(),
            session_type=OnlySessionType.REGULAR,
        )
        return self._envelope(
            instrument_id, event, OnlyMarketDataType.BAR, OnlyBarUpdate(bar)
        )

    def _envelope(self, instrument_id, event, data_type, payload):
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
    def _rows(raw: object) -> tuple[dict[str, object], ...]:
        if not isinstance(raw, dict):
            return ()
        rows: list[dict[str, object]] = []
        for value in raw.values():
            if isinstance(value, dict):
                rows.append(value)
            elif isinstance(value, (list, tuple)):
                rows.extend(item for item in value if isinstance(item, dict))
        return tuple(rows)
