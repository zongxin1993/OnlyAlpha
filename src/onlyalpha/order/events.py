"""Past-tense Order facts emitted only after successful mutation."""

from onlyalpha.event.model import OnlyEvent


class OnlyOrderCreatedEvent(OnlyEvent):
    pass


class OnlyOrderSubmittedEvent(OnlyEvent):
    pass


class OnlyOrderAcceptedEvent(OnlyEvent):
    pass


class OnlyOrderPartiallyFilledEvent(OnlyEvent):
    pass


class OnlyOrderFilledEvent(OnlyEvent):
    pass


class OnlyOrderCancelRequestedEvent(OnlyEvent):
    pass


class OnlyOrderCancelledEvent(OnlyEvent):
    pass


class OnlyOrderRejectedEvent(OnlyEvent):
    pass


class OnlyOrderExpiredEvent(OnlyEvent):
    pass


class OnlyOrderFailedEvent(OnlyEvent):
    pass
