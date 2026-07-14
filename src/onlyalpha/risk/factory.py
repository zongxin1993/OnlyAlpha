"""Risk Profile factory and built-in Rule registration."""

from collections.abc import Mapping
from decimal import Decimal

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.risk.enums import OnlyRiskRuleMode
from onlyalpha.risk.profile import OnlyRiskProfile, OnlyRiskProfileConfig
from onlyalpha.risk.registry import OnlyRiskRuleRegistry
from onlyalpha.risk.rules.mandatory import ONLY_MANDATORY_RISK_RULE_IDS
from onlyalpha.risk.rules.runtime import (
    OnlyMaxActiveOrdersRiskRule,
    OnlyMaxClusterActiveOrdersRiskRule,
    OnlyMaxInstrumentActiveOrdersRiskRule,
    OnlyMaxOrderNotionalRiskRule,
    OnlyMaxOrderQuantityRiskRule,
)


def _required(config: Mapping[str, object], key: str) -> object:
    if key not in config:
        raise ValueError(f"Risk Rule config requires {key}")
    return config[key]


def only_default_risk_rule_registry() -> OnlyRiskRuleRegistry:
    registry = OnlyRiskRuleRegistry()
    registry.register(
        "OnlyMaxActiveOrdersRiskRule",
        lambda config, order, mode: OnlyMaxActiveOrdersRiskRule(
            int(str(_required(config, "maximum"))), order=order, mode=mode
        ),
    )
    registry.register(
        "OnlyMaxClusterActiveOrdersRiskRule",
        lambda config, order, mode: OnlyMaxClusterActiveOrdersRiskRule(
            int(str(_required(config, "maximum"))), order=order, mode=mode
        ),
    )
    registry.register(
        "OnlyMaxInstrumentActiveOrdersRiskRule",
        lambda config, order, mode: OnlyMaxInstrumentActiveOrdersRiskRule(
            int(str(_required(config, "maximum"))), order=order, mode=mode
        ),
    )
    registry.register(
        "OnlyMaxOrderQuantityRiskRule",
        lambda config, order, mode: OnlyMaxOrderQuantityRiskRule(
            OnlyQuantity(
                Decimal(str(_required(config, "maximum"))),
                int(str(config.get("precision", 0))),
            ),
            order=order,
            mode=mode,
        ),
    )

    def max_notional(config: Mapping[str, object], order: int, mode: OnlyRiskRuleMode) -> OnlyMaxOrderNotionalRiskRule:
        raw = config.get("maximum", config.get("max_notional"))
        if not isinstance(raw, Mapping):
            raise ValueError("maximum/max_notional must contain amount, currency and optional precision")
        currency = OnlyCurrency(str(_required(raw, "currency")), int(str(raw.get("precision", 2))))
        return OnlyMaxOrderNotionalRiskRule(
            OnlyMoney(Decimal(str(_required(raw, "amount"))), currency),
            include_active_reservations=bool(config.get("include_active_reservations", True)),
            order=order,
            mode=mode,
        )

    registry.register("OnlyMaxOrderNotionalRiskRule", max_notional)
    return registry


class OnlyRiskProfileFactory:
    def __init__(self, registry: OnlyRiskRuleRegistry | None = None) -> None:
        self._registry = registry or only_default_risk_rule_registry()

    @property
    def registry(self) -> OnlyRiskRuleRegistry:
        return self._registry

    def create(self, config: OnlyRiskProfileConfig) -> OnlyRiskProfile:
        forbidden = set(config.disabled_rule_ids) & set(ONLY_MANDATORY_RISK_RULE_IDS)
        if forbidden:
            raise ValueError(f"Mandatory Risk Rules cannot be disabled: {sorted(map(str, forbidden))}")
        rules = tuple(
            self._registry.create(
                item.rule_type,
                item.config,
                item.order,
                OnlyRiskRuleMode(item.mode),
            )
            for item in config.rules
        )
        if any(rule.rule_id in ONLY_MANDATORY_RISK_RULE_IDS or rule.metadata.mandatory for rule in rules):
            raise ValueError("Cluster Risk Profile cannot replace Mandatory System Rules")
        return OnlyRiskProfile(config.profile_id, rules)
