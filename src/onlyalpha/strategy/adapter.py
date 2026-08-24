"""Internal kernel lifecycle adapter for one resolved Strategy Revision."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.domain.market import OnlyBar
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.execution import OnlyStrategyDecision, OnlyStrategyExecutionPlan
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyRevisionStrategyAdapter(OnlyStrategy):
    """Contains lifecycle plumbing only; Strategy rules live in the Revision graph."""

    def __init__(self, plan: OnlyStrategyExecutionPlan) -> None:
        self._plan = plan
        self._executor = plan.new_executor()
        self._decisions: list[OnlyStrategyDecision] = []
        super().__init__(OnlyStrategyConfig(OnlyStrategyId(str(plan.strategy_fingerprint))))

    @property
    def strategy_fingerprint(self) -> str:
        return str(self._plan.strategy_fingerprint)

    @property
    def decisions(self) -> tuple[OnlyStrategyDecision, ...]:
        return tuple(self._decisions)

    def on_initialize(self) -> None:
        return None

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        if not isinstance(context.primary_bar, OnlyBar):
            raise TypeError("Revision Strategy requires an OnlyBar observation")
        decision = self._executor.execute(context.primary_bar)
        if not self._decisions or self._decisions[-1] != decision:
            self._decisions.append(decision)

    @property
    def checkpoint_schema_version(self) -> int:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return self._executor.capture_checkpoint()

    def restore_checkpoint(self, payload: object) -> None:
        self._executor.restore_checkpoint(payload)
        self._decisions = list(self._executor.last_decisions)

    def build_result_extension(self) -> Mapping[str, object]:
        last = None
        if self._decisions:
            decision = self._decisions[-1]
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
