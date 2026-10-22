"""Research Calculation error and immutable result store failure."""

from onlyalpha.algorithm.batch import OnlyResearchCalculationError as OnlyResearchCalculationError


class OnlyResearchCalculationResultStoreError(OnlyResearchCalculationError):
    """Stable public failure contract for immutable Result persistence."""
