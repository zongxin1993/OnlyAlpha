"""Runtime-mode capability planning without changing Action semantics."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.scenario.errors import OnlyScenarioErrorCode, OnlyScenarioValidationIssue
from onlyalpha.scenario.fingerprint import only_scenario_fingerprint
from onlyalpha.scenario.models import OnlyMarketScenario, OnlyScenarioAction


@dataclass(frozen=True, slots=True)
class OnlyScenarioRuntimeCommand:
    action_id: str
    command: object


@dataclass(frozen=True, slots=True)
class OnlyMarketScenarioPlan:
    scenario: OnlyMarketScenario
    commands: tuple[OnlyScenarioRuntimeCommand, ...]
    executable: bool
    issues: tuple[OnlyScenarioValidationIssue, ...]
    input_fingerprint: str


class OnlyMarketScenarioPlanner:
    """Checks mode capability and emits runtime-neutral commands; it never executes a Runtime."""

    def plan(self, scenario: OnlyMarketScenario) -> OnlyMarketScenarioPlan:
        commands = tuple(self._command(action) for action in scenario.actions)
        issues: tuple[OnlyScenarioValidationIssue, ...] = ()
        if scenario.runtime.mode is not OnlyRuntimeMode.BACKTEST:
            issues = (
                OnlyScenarioValidationIssue(
                    OnlyScenarioErrorCode.SCENARIO_RUNTIME_MODE_UNSUPPORTED,
                    "$.runtime.mode",
                    f"{scenario.runtime.mode.value} is parseable but not executable by Scenario Runner",
                ),
            )
        return OnlyMarketScenarioPlan(
            scenario,
            commands,
            not issues,
            issues,
            only_scenario_fingerprint({"scenario": scenario, "commands": commands}),
        )

    @staticmethod
    def _command(action: OnlyScenarioAction) -> OnlyScenarioRuntimeCommand:
        return OnlyScenarioRuntimeCommand(action.action_id, action.command)
