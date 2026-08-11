"""Finite historical external-world driver."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from onlyalpha.runtime.backtest.run_plan import OnlyBacktestRunPlan

if TYPE_CHECKING:
    from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime


class OnlyBacktestDriver:
    """Drive historical replay, clock advancement and deterministic run termination."""

    def __init__(self, plan: OnlyBacktestRunPlan) -> None:
        self._plan = plan

    def execute(self, runtime: object) -> object:
        return self._plan.execute(cast("OnlyBacktestRuntime", runtime))
