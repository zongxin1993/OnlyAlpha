from onlyalpha.domain.identifiers import OnlyInstrumentId

_XT_TO_VENUE = {"SH": "XSHG", "SZ": "XSHE"}
_VENUE_TO_XT = {value: key for key, value in _XT_TO_VENUE.items()}


def from_xt_symbol(value: str) -> OnlyInstrumentId:
    symbol, separator, exchange = value.rpartition(".")
    if not separator or exchange not in _XT_TO_VENUE:
        raise ValueError(f"unsupported MiniQMT symbol: {value}")
    return OnlyInstrumentId.parse(f"{symbol}.{_XT_TO_VENUE[exchange]}")


def to_xt_symbol(value: OnlyInstrumentId) -> str:
    venue = str(value.venue)
    if venue not in _VENUE_TO_XT:
        raise ValueError(f"unsupported MiniQMT venue: {venue}")
    return f"{value.symbol}.{_VENUE_TO_XT[venue]}"
