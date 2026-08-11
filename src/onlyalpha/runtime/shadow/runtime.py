from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.runtime import OnlyRuntime


class OnlyShadowRuntime(OnlyRuntime):
    """Shadow Runtime boundary; shadow execution is intentionally absent."""

    _supported_modes = frozenset({OnlyRuntimeMode.SHADOW})
