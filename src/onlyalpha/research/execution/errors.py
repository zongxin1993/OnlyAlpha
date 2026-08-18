"""Stable Research execution-control failure boundary."""


class OnlyResearchExecutionError(RuntimeError):
    code = "RESEARCH_EXECUTION_ERROR"


class OnlyResearchExecutionOwnershipLostError(OnlyResearchExecutionError):
    code = "RESEARCH_EXECUTION_OWNERSHIP_LOST"


class OnlyResearchExecutionStoreUnavailableError(OnlyResearchExecutionError):
    code = "RESEARCH_EXECUTION_STORE_UNAVAILABLE"


class OnlyResearchExecutionCancelledError(OnlyResearchExecutionError):
    code = "RESEARCH_EXECUTION_CANCELLED"


__all__ = [name for name in globals() if name.startswith("Only")]
