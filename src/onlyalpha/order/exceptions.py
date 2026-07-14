"""Order component errors."""


class OnlyOrderError(Exception):
    """Base expected Order component error."""


class OnlyInvalidOrderTransitionError(OnlyOrderError):
    """A requested status transition violates the central state machine."""


class OnlyOrderNotFoundError(OnlyOrderError):
    """An Order query could not resolve the requested ID."""


class OnlyOrderScopeError(OnlyOrderError):
    """A Cluster attempted to access another Cluster's Order."""
