"""Canonical identities for provider-neutral market facts."""

from datetime import datetime

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyMarketReferenceKind, OnlyQuoteTick
from onlyalpha.identity import only_identity_fingerprint


def _identity(kind: str, payload: dict[str, object]) -> OnlyMarketDataUpdateId:
    fingerprint = only_identity_fingerprint({"kind": kind, **payload})
    return OnlyMarketDataUpdateId(f"market-fact:{kind.lower()}:{fingerprint}")


def only_bar_update_id(
    source_id: OnlyMarketDataSourceId,
    instrument_id: OnlyInstrumentId,
    bar_type: OnlyBarType,
    bar_start: datetime,
    data_version: OnlyDataVersion,
) -> OnlyMarketDataUpdateId:
    return _identity(
        "BAR",
        {
            "source": str(source_id),
            "instrument": instrument_id.to_json(),
            "bar_type": bar_type.to_json(),
            "bar_start": bar_start,
            "data_version": str(data_version),
        },
    )


def only_provisional_bar_update_id(
    source_id: OnlyMarketDataSourceId,
    bar: OnlyBar,
    data_version: OnlyDataVersion,
) -> OnlyMarketDataUpdateId:
    if bar.is_closed:
        raise ValueError("provisional Bar identity requires an open Bar")
    return _identity(
        "PROVISIONAL_BAR",
        {
            "source": str(source_id),
            "bar": bar.to_json(),
            "data_version": str(data_version),
        },
    )


def only_quote_update_id(
    source_id: OnlyMarketDataSourceId,
    quote: OnlyQuoteTick,
    data_version: OnlyDataVersion,
) -> OnlyMarketDataUpdateId:
    return _identity(
        "QUOTE",
        {
            "source": str(source_id),
            "quote": quote.to_json(),
            "data_version": str(data_version),
        },
    )


def only_trade_update_id(
    source_id: OnlyMarketDataSourceId,
    instrument_id: OnlyInstrumentId,
    trade_id: OnlyTradeId,
    data_version: OnlyDataVersion,
) -> OnlyMarketDataUpdateId:
    return _identity(
        "TRADE",
        {
            "source": str(source_id),
            "instrument": instrument_id.to_json(),
            "venue_trade_id": str(trade_id),
            "data_version": str(data_version),
        },
    )


def only_market_reference_update_id(
    source_id: OnlyMarketDataSourceId,
    instrument_id: OnlyInstrumentId,
    reference_kind: OnlyMarketReferenceKind,
    ts_event: datetime,
    data_version: OnlyDataVersion,
) -> OnlyMarketDataUpdateId:
    return _identity(
        "MARKET_REFERENCE",
        {
            "source": str(source_id),
            "instrument": instrument_id.to_json(),
            "reference_kind": reference_kind.value,
            "ts_event": ts_event,
            "data_version": str(data_version),
        },
    )
