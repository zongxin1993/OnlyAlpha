from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.runtime import OnlyRuntime


class OnlyResearchRuntime(OnlyRuntime):
    """Research Runtime boundary; factor loop is intentionally absent."""

    _supported_modes = frozenset({OnlyRuntimeMode.RESEARCH})
