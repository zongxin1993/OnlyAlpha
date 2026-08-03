from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


class OnlyPaperRuntime(OnlyStreamingRuntime):
    """Real-time market observation with Risk/Order and broker-free Shadow execution."""

    _supported_modes = frozenset({OnlyRuntimeMode.PAPER})
