import re

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyEquity, OnlyETF, OnlyInstrument

from ..errors import OnlyTushareError

_SUFFIXES = {"XSHG": "SH", "XSHE": "SZ", "XBSE": "BJ"}


def only_to_tushare_symbol(instrument_id: OnlyInstrumentId) -> str:
    symbol, venue = str(instrument_id).rsplit(".", 1)
    if not re.fullmatch(r"\d{6}", symbol):
        raise OnlyTushareError(
            "TUSHARE_SYMBOL_INVALID", "instrument symbol must contain six digits"
        )
    try:
        suffix = _SUFFIXES[venue]
    except KeyError as exc:
        raise OnlyTushareError(
            "TUSHARE_VENUE_UNSUPPORTED", "instrument venue is not supported"
        ) from exc
    return f"{symbol}.{suffix}"


def only_to_tushare_asset(instrument: OnlyInstrument) -> str:
    if isinstance(instrument, OnlyETF):
        return "FD"
    if isinstance(instrument, OnlyEquity):
        return "E"
    raise OnlyTushareError(
        "TUSHARE_ASSET_UNSUPPORTED", "instrument asset type is not supported"
    )
