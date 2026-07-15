"""Position component failures."""


class OnlyPositionError(Exception):
    pass


class OnlyPositionInvariantError(OnlyPositionError):
    pass


class OnlyPositionOverSellError(OnlyPositionError):
    pass


class OnlyPositionReconciliationRequiredError(OnlyPositionError):
    pass
