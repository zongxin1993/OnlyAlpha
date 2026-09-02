from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType

STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11


def map_side(side: OnlyOrderSide) -> int:
    return STOCK_BUY if side is OnlyOrderSide.BUY else STOCK_SELL


def require_limit(order_type: OnlyOrderType) -> int:
    if order_type is not OnlyOrderType.LIMIT:
        raise ValueError("MiniQMT phase one supports LIMIT orders only")
    return FIX_PRICE
