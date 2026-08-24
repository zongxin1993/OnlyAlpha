"""Internal kernel lifecycle adapter for one resolved Strategy Revision."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.domain.market import OnlyBar
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha.strategy.execution import OnlyStrategyDecision, OnlyStrategyExecutionPlan


class OnlyRevisionStrategyAdapter:
    """Sealed lifecycle plumbing; all Strategy semantics live in the Revision graph."""

    def __init__(self, plan: OnlyStrategyExecutionPlan) -> None:
        if not isinstance(plan, OnlyStrategyExecutionPlan):
            raise TypeError("Revision Strategy adapter requires a resolved execution plan")
        self._plan = plan
        self._executor = plan.new_executor()

    @property
    def strategy_fingerprint(self) -> str:
        return str(self._plan.strategy_fingerprint)

    def on_initialize(self) -> None:
        return None

    def on_start(self) -> None:
        return None

    def on_bar(self, bar: OnlyBar) -> OnlyStrategyDecision:
        if not isinstance(bar, OnlyBar):
            raise TypeError("Revision Strategy requires an OnlyBar observation")
        return self._executor.execute(bar)

    def on_pause(self) -> None:
        return None

    def on_resume(self) -> None:
        return None

    def on_stop(self) -> None:
        return None

    @property
    def checkpoint_schema_version(self) -> int:
        return 2

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return self._executor.capture_checkpoint()

    def restore_checkpoint(self, payload: object) -> None:
        self._executor.restore_checkpoint(payload)

    def build_result_extension(self) -> Mapping[str, object]:
        decisions = self._executor.last_decisions
        last = None
        if decisions:
            decision = max(decisions, key=lambda item: (item.decision_time.unix_nanos, item.instrument_id))
            last = {
                "strategy_fingerprint": decision.strategy_fingerprint,
                "instrument_id": decision.instrument_id,
                "observation_key": decision.observation_key.fingerprint,
                "observation_fingerprint": decision.observation_fingerprint,
                "decision_time_ns": decision.decision_time.unix_nanos,
                "eligibility": decision.eligibility,
                "entry": decision.entry,
                "exit": decision.exit,
            }
        return {"strategy_fingerprint": self.strategy_fingerprint, "last_strategy_decision": last}


__all__ = ["OnlyRevisionStrategyAdapter"]
