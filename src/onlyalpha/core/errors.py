"""Shared OnlyAlpha exceptions."""


class OnlyError(Exception):
    """Base exception for expected OnlyAlpha failures."""


class OnlyLifecycleError(OnlyError):
    """Raised when a component receives an invalid lifecycle transition."""


class OnlyDuplicateIdError(OnlyError):
    """Raised when a registry receives an existing identifier."""


class OnlyNotFoundError(OnlyError):
    """Raised when a requested component does not exist."""


class OnlyValidationError(OnlyError):
    """Raised when a domain value violates an explicit constraint."""
