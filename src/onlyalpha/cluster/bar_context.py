"""Read-only strategy context for a single primary-Bar callback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from onlyalpha.core.clock import OnlyClockView
from onlyalpha.runtime.context import OnlyRuntimeContextError, OnlyRuntimeContextView

if TYPE_CHECKING:
    from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot


class OnlyBarContext:
    """Immutable callback view; standalone component tests may provide only ClockView."""

    __slots__ = ("_clock_view", "_runtime", "snapshot")
    snapshot: OnlyMarketDataSnapshot
    _runtime: OnlyRuntimeContextView | None
    _clock_view: OnlyClockView

    def __init__(
        self,
        snapshot: OnlyMarketDataSnapshot,
        runtime: OnlyRuntimeContextView | OnlyClockView,
    ) -> None:
        object.__setattr__(self, "snapshot", snapshot)
        if isinstance(runtime, OnlyClockView):
            object.__setattr__(self, "_runtime", None)
            object.__setattr__(self, "_clock_view", runtime)
        else:
            object.__setattr__(self, "_runtime", runtime)
            object.__setattr__(self, "_clock_view", runtime.clock)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    @property
    def runtime(self) -> OnlyRuntimeContextView:
        if self._runtime is None:
            raise OnlyRuntimeContextError("standalone BarContext has no RuntimeContext")
        return self._runtime

    @property
    def clock_view(self) -> OnlyClockView:
        return self._clock_view
