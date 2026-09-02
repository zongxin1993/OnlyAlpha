"""Virtual Broker plugin errors."""


class OnlyVirtualBrokerError(RuntimeError):
    pass


__all__ = ["OnlyVirtualBrokerError"]
