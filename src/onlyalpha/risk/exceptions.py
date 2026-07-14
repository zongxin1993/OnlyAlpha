"""Risk component boundary errors."""


class OnlyRiskError(Exception):
    """Base exception for invalid Risk configuration or service use."""


class OnlyRiskConfigurationError(OnlyRiskError):
    """Raised when a Risk Profile or Rule configuration is invalid."""
