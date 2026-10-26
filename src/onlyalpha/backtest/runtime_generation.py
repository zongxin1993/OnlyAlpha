"""Backtest-only Generation composition; the generic binding port owns no execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

from onlyalpha.application.runtime_generation import (
    OnlyNoClaimRuntimeGenerationWorkAuthority,
    OnlyRuntimeGenerationWorkAuthority,
)

if TYPE_CHECKING:
    from onlyalpha.backtest.admission import OnlyBacktestDatasetBindingReader
    from onlyalpha.backtest.model import OnlyBacktestRun
    from onlyalpha.backtest.worker import (
        OnlyBacktestEnginePlanBuilder,
        OnlyBacktestRuntimeComposition,
        OnlyBacktestRuntimeControl,
        OnlyBacktestRuntimeExecutor,
    )
    from onlyalpha.research.dataset.ports import OnlyBoundedResearchDatasetSnapshotStore
    from onlyalpha.strategy.revision import OnlyStrategyRevision
    from onlyalpha.strategy.store import OnlyStrategyRevisionReader


class OnlyBacktestRuntimeGenerationWorkAuthority(OnlyRuntimeGenerationWorkAuthority, Protocol):
    def validate_backtest_result_binding(
        self,
        work_id: str,
        generation: str,
        native_artifact: str,
        *,
        run: OnlyBacktestRun,
        plans: OnlyBacktestEnginePlanBuilder,
        strategies: OnlyStrategyRevisionReader,
        datasets: OnlyBoundedResearchDatasetSnapshotStore,
        dataset_bindings: OnlyBacktestDatasetBindingReader,
        plan_fingerprint: str,
        result: Mapping[str, object],
        trace: Mapping[str, object],
    ) -> None: ...
    def validate_backtest_work(self, run: OnlyBacktestRun, strategy: OnlyStrategyRevision) -> None: ...
    def backtest_executor(self, composition: OnlyBacktestRuntimeComposition) -> OnlyBacktestRuntimeExecutor: ...


class OnlyNoClaimBacktestRuntimeGenerationWorkAuthority(OnlyNoClaimRuntimeGenerationWorkAuthority):
    """Keep lifecycle-only worker composition available without an executable fallback."""

    def validate_backtest_result_binding(
        self,
        work_id: str,
        generation: str,
        native_artifact: str,
        *,
        run: OnlyBacktestRun,
        plans: OnlyBacktestEnginePlanBuilder,
        strategies: OnlyStrategyRevisionReader,
        datasets: OnlyBoundedResearchDatasetSnapshotStore,
        dataset_bindings: OnlyBacktestDatasetBindingReader,
        plan_fingerprint: str,
        result: Mapping[str, object],
        trace: Mapping[str, object],
    ) -> None:
        self._unavailable()

    def validate_backtest_work(self, run: OnlyBacktestRun, strategy: OnlyStrategyRevision) -> None:
        self._unavailable()

    def backtest_executor(self, composition: OnlyBacktestRuntimeComposition) -> OnlyBacktestRuntimeExecutor:
        del composition
        return self

    def execute(
        self, run: OnlyBacktestRun, control: OnlyBacktestRuntimeControl, *, initialize: bool = False
    ) -> NoReturn:
        del run, control, initialize
        self._unavailable()


def only_require_backtest_runtime_generation_work_authority(
    authority: OnlyRuntimeGenerationWorkAuthority,
) -> OnlyBacktestRuntimeGenerationWorkAuthority:
    required = ("validate_backtest_result_binding", "validate_backtest_work", "backtest_executor")
    if any(not callable(getattr(authority, name, None)) for name in required):
        raise RuntimeError("BACKTEST_RUNTIME_GENERATION_WORK_AUTHORITY_INVALID")
    return cast(OnlyBacktestRuntimeGenerationWorkAuthority, authority)
