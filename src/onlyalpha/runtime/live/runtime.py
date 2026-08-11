from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.runtime import OnlyRuntime


class OnlyLiveRuntime(OnlyRuntime):
    """Live Runtime boundary; real trading adapters are intentionally absent."""

    _supported_modes = frozenset({OnlyRuntimeMode.LIVE})
