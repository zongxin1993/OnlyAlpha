from onlyalpha.domain.enums import OnlyOrderStatus

XT_ORDER_STATUS = {
    48: OnlyOrderStatus.SUBMITTED,
    49: OnlyOrderStatus.SUBMITTED,
    50: OnlyOrderStatus.ACCEPTED,
    51: OnlyOrderStatus.CANCELLED,
    52: OnlyOrderStatus.PARTIALLY_FILLED,
    53: OnlyOrderStatus.FILLED,
    54: OnlyOrderStatus.CANCELLED,
    55: OnlyOrderStatus.REJECTED,
    56: OnlyOrderStatus.CANCELLED,
}


def map_order_status(value: int) -> OnlyOrderStatus:
    return XT_ORDER_STATUS.get(value, OnlyOrderStatus.SUBMITTED)
