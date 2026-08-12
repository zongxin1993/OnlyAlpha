from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


class OnlySimRuntime(OnlyStreamingRuntime):
    """Realtime Runtime using simulated Broker execution."""

    _supported_modes = frozenset({OnlyRuntimeMode.SIM})
