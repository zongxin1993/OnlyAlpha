"""Validated registry for built-in and custom Risk Rule factories."""

from collections.abc import Callable, Mapping

from onlyalpha.risk.enums import OnlyRiskRuleMode
from onlyalpha.risk.rules.base import OnlyRiskRule

OnlyRiskRuleFactory = Callable[[Mapping[str, object], int, OnlyRiskRuleMode], OnlyRiskRule]


class OnlyRiskRuleRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, OnlyRiskRuleFactory] = {}

    def register(self, rule_type: str, factory: OnlyRiskRuleFactory) -> None:
        if not rule_type.startswith("Only"):
            raise ValueError("custom Risk Rule type must start with Only")
        if rule_type in self._factories:
            raise ValueError(f"duplicate Risk Rule type: {rule_type}")
        self._factories[rule_type] = factory

    def create(
        self,
        rule_type: str,
        config: Mapping[str, object],
        order: int,
        mode: OnlyRiskRuleMode,
    ) -> OnlyRiskRule:
        try:
            rule = self._factories[rule_type](config, order, mode)
        except KeyError as exc:
            raise ValueError(f"unknown Risk Rule type: {rule_type}") from exc
        if not isinstance(rule, OnlyRiskRule):
            raise TypeError("Risk Rule factory must return OnlyRiskRule")
        if not type(rule).__name__.startswith("Only"):
            raise ValueError("Risk Rule class name must start with Only")
        return rule

    @property
    def rule_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
