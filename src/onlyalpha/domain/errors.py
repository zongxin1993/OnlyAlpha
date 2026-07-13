"""Domain-local errors with no dependency on application infrastructure."""


class OnlyDomainError(Exception):
    """Base class for pure financial domain failures."""


class OnlyValidationError(OnlyDomainError):
    """Raised when a domain invariant is violated."""


class OnlyCurrencyMismatchError(OnlyValidationError):
    """Raised when arithmetic mixes currencies without conversion."""


class OnlyStateTransitionError(OnlyDomainError):
    """Raised when an entity receives an illegal lifecycle transition."""


class OnlySerializationError(OnlyDomainError):
    """Raised when a domain object cannot be serialized or restored."""
