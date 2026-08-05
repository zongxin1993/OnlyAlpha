import re
from collections.abc import Mapping

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyEquity, OnlyETF, OnlyInstrument
from onlyalpha.plugin.api import OnlyAshareInstrumentReference

from ..errors import OnlyTushareError

_SUFFIXES = {"XSHG": "SH", "XSHE": "SZ", "XBSE": "BJ"}


def only_to_tushare_symbol(instrument_id: OnlyInstrumentId) -> str:
    symbol, venue = str(instrument_id).rsplit(".", 1)
    if not re.fullmatch(r"\d{6}", symbol):
        raise OnlyTushareError("TUSHARE_SYMBOL_INVALID", "instrument symbol must contain six digits")
    try:
        suffix = _SUFFIXES[venue]
    except KeyError as exc:
        raise OnlyTushareError("TUSHARE_VENUE_UNSUPPORTED", "instrument venue is not supported") from exc
    return f"{symbol}.{suffix}"


def only_to_tushare_asset(instrument: OnlyInstrument) -> str:
    if isinstance(instrument, OnlyETF):
        return "FD"
    if isinstance(instrument, OnlyEquity):
        return "E"
    raise OnlyTushareError("TUSHARE_ASSET_UNSUPPORTED", "instrument asset type is not supported")


def only_ashare_reference(raw: Mapping[str, object]) -> OnlyAshareInstrumentReference:
    """Normalize one explicitly joined historical Tushare reference row.

    The adapter intentionally requires joined historical ST/suspension fields and
    never derives them from the current security name or a price Bar.
    """

    ts_code = raw.get("ts_code")
    exchange = raw.get("exchange")
    trading_day = raw.get("trade_date")
    board = raw.get("market")
    if (
        not isinstance(ts_code, str)
        or not ts_code
        or not isinstance(exchange, str)
        or not exchange
        or not isinstance(trading_day, str)
        or not trading_day
        or not isinstance(board, str)
        or not board
    ):
        raise OnlyTushareError("TUSHARE_REFERENCE_INCOMPLETE", "joined historical reference fields are required")
    symbol, separator, suffix = ts_code.partition(".")
    if not separator or suffix not in {"SH", "SZ"}:
        raise OnlyTushareError("TUSHARE_REFERENCE_INCOMPLETE", "ts_code must identify SH or SZ explicitly")
    board_value = {"主板": "SSE_MAIN" if exchange == "SSE" else "SZSE_MAIN", "创业板": "CHINEXT", "科创板": "STAR"}.get(
        board
    )
    if board_value is None:
        raise OnlyTushareError("TUSHARE_REFERENCE_BOARD_UNSUPPORTED", f"unsupported market: {board}")
    try:
        return OnlyAshareInstrumentReference.from_mapping(
            {
                "instrument_id": f"{symbol}.{'XSHG' if suffix == 'SH' else 'XSHE'}",
                "exchange": exchange,
                "security_type": raw.get("security_type"),
                "board": board_value,
                "lot_size": raw.get("lot_size"),
                "price_tick": raw.get("price_tick"),
                "st_status": raw.get("st_status"),
                "suspended": raw.get("suspended"),
                "previous_close": raw.get("pre_close"),
                "effective_from": trading_day,
                "effective_to": raw.get("effective_to"),
                "source": "TUSHARE",
                "source_version": raw.get("source_version"),
                "data_version": raw.get("data_version"),
            }
        )
    except ValueError as exc:
        raise OnlyTushareError("TUSHARE_REFERENCE_INVALID", str(exc)) from exc
