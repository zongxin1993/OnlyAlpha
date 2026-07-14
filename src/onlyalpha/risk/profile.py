"""Immutable configuration and resolved Cluster Risk Profiles."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule


@dataclass(frozen=True, slots=True)
class OnlyRiskRuleConfig:
    rule_type: str
    order: int = 100
    config: Mapping[str, object] = field(default_factory=dict)
    mode: str = "ENFORCING"

    def __post_init__(self) -> None:
        if not self.rule_type.startswith("Only"):
            raise ValueError("Risk Rule type must start with Only")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass(frozen=True, slots=True)
class OnlyRiskProfileConfig:
    profile_id: OnlyRiskProfileId
    rules: tuple[OnlyRiskRuleConfig, ...] = ()
    disabled_rule_ids: tuple[OnlyRiskRuleId, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyRiskProfile:
    profile_id: OnlyRiskProfileId
    rules: tuple[OnlyRiskRule, ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(rule.rule_id for rule in self.rules)
        if len(ids) != len(set(ids)):
            raise ValueError("Risk Profile contains duplicate RuleId")
