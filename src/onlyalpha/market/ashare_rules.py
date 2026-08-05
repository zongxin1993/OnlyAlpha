"""Pure compilation of versioned China A-share pre-trade policies."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyPriceBandRoundingMode,
)
from onlyalpha.reference import OnlyAshareBoard

_PRICE_LIMIT_REGIMES: dict[str, dict[tuple[OnlyAshareBoard, bool], Decimal]] = {
    "2025.1": {
        (OnlyAshareBoard.SSE_MAIN, False): Decimal("0.10"),
        (OnlyAshareBoard.SSE_MAIN, True): Decimal("0.05"),
        (OnlyAshareBoard.SZSE_MAIN, False): Decimal("0.10"),
        (OnlyAshareBoard.SZSE_MAIN, True): Decimal("0.05"),
        (OnlyAshareBoard.CHINEXT, False): Decimal("0.20"),
        (OnlyAshareBoard.CHINEXT, True): Decimal("0.20"),
        (OnlyAshareBoard.STAR, False): Decimal("0.20"),
        (OnlyAshareBoard.STAR, True): Decimal("0.20"),
    },
    "2026.07": {
        (OnlyAshareBoard.SSE_MAIN, False): Decimal("0.10"),
        (OnlyAshareBoard.SSE_MAIN, True): Decimal("0.10"),
        (OnlyAshareBoard.SZSE_MAIN, False): Decimal("0.10"),
        (OnlyAshareBoard.SZSE_MAIN, True): Decimal("0.10"),
        (OnlyAshareBoard.CHINEXT, False): Decimal("0.20"),
        (OnlyAshareBoard.CHINEXT, True): Decimal("0.20"),
        (OnlyAshareBoard.STAR, False): Decimal("0.20"),
        (OnlyAshareBoard.STAR, True): Decimal("0.20"),
    },
}


def only_compile_ashare_price_policy(
    *,
    profile_version: str,
    board: str | None,
    st_status: bool,
    previous_close: Decimal | None,
    tick_size: Decimal,
) -> OnlyCompiledPriceBandPolicy:
    if previous_close is None or previous_close <= 0:
        raise ValueError("REFERENCE_PREVIOUS_CLOSE_INVALID")
    if tick_size <= 0:
        raise ValueError("REFERENCE_PRICE_TICK_INVALID")
    try:
        canonical_board = OnlyAshareBoard(board or "")
        rate = _PRICE_LIMIT_REGIMES[profile_version][canonical_board, st_status]
    except (KeyError, ValueError) as exc:
        raise ValueError("ASHARE_REGIME_NOT_FOUND") from exc
    upper = _round_to_tick(previous_close * (Decimal(1) + rate), tick_size)
    lower = _round_to_tick(previous_close * (Decimal(1) - rate), tick_size)
    if upper - previous_close < tick_size:
        upper = previous_close + tick_size
    if previous_close - lower < tick_size:
        lower = previous_close - tick_size
    state = "RISK_WARNING" if st_status else "NORMAL"
    return OnlyCompiledPriceBandPolicy(
        f"CN_A_SHARE_CASH@{profile_version}:{canonical_board.value}:{state}",
        tick_size,
        previous_close,
        rate,
        lower,
        upper,
        OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
    )


def only_compile_ashare_quantity_policy(
    *,
    profile_version: str,
    board: str | None,
    lot_size: Decimal | None,
) -> OnlyCompiledQuantityPolicy:
    try:
        canonical_board = OnlyAshareBoard(board or "")
        _PRICE_LIMIT_REGIMES[profile_version]
    except (KeyError, ValueError) as exc:
        raise ValueError("ASHARE_REGIME_NOT_FOUND") from exc
    if lot_size is None or lot_size <= 0:
        raise ValueError("REFERENCE_LOT_SIZE_INVALID")
    if canonical_board is OnlyAshareBoard.STAR:
        minimum_buy = Decimal(200)
        buy_increment = Decimal(1)
    else:
        minimum_buy = Decimal(100)
        buy_increment = Decimal(100)
    return OnlyCompiledQuantityPolicy(
        minimum_buy,
        buy_increment,
        Decimal(1),
        lot_size,
        True,
        None,
        False,
    )


def _round_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return (value / tick_size).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick_size
