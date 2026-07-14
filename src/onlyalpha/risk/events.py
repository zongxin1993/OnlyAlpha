"""Past-tense Risk facts; no strategy callbacks are defined in this phase."""

from onlyalpha.event.model import OnlyEvent


class OnlyRiskAcceptedEvent(OnlyEvent):
    pass


class OnlyRiskRejectedEvent(OnlyEvent):
    pass


class OnlyRiskRuleFailedEvent(OnlyEvent):
    pass


class OnlyRiskLimitTriggeredEvent(OnlyEvent):
    pass


class OnlyRiskReservationCreatedEvent(OnlyEvent):
    pass


class OnlyRiskReservationReleasedEvent(OnlyEvent):
    pass


class OnlyRiskStateUpdatedEvent(OnlyEvent):
    pass
