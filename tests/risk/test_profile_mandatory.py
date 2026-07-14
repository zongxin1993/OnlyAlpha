from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.enums import OnlyRiskRuleMode
from onlyalpha.risk.factory import OnlyRiskProfileFactory, only_default_risk_rule_registry
from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.profile import OnlyRiskProfileConfig, OnlyRiskRuleConfig
from onlyalpha.risk.rules.mandatory import ONLY_MANDATORY_RISK_RULE_IDS
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule


def test_profile_cannot_disable_or_replace_mandatory_rule() -> None:
    factory = OnlyRiskProfileFactory()
    mandatory = next(iter(ONLY_MANDATORY_RISK_RULE_IDS))
    with pytest.raises(ValueError):
        factory.create(OnlyRiskProfileConfig(OnlyRiskProfileId("bad"), disabled_rule_ids=(mandatory,)))


def test_profile_factory_builds_configured_rule_stably() -> None:
    config = OnlyRiskProfileConfig(
        OnlyRiskProfileId("conservative"),
        (
            OnlyRiskRuleConfig(
                "OnlyMaxOrderNotionalRiskRule",
                200,
                {"maximum": {"amount": "50000.00", "currency": "CNY", "precision": 2}},
            ),
        ),
    )
    profile = OnlyRiskProfileFactory().create(config)
    assert isinstance(profile.rules[0], OnlyMaxOrderNotionalRiskRule)
    assert profile.rules[0].maximum == OnlyMoney(Decimal("50000.00"), OnlyCurrency("CNY", 2))


def test_custom_rule_registry_validates_name_and_duplicate() -> None:
    registry = only_default_risk_rule_registry()
    with pytest.raises(ValueError):
        registry.register("BadRule", lambda config, order, mode: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError):
        registry.register("OnlyMaxOrderNotionalRiskRule", lambda config, order, mode: None)  # type: ignore[arg-type,return-value]


def test_mandatory_metadata_cannot_be_observing() -> None:
    from onlyalpha.risk.enums import OnlyRiskRuleScope
    from onlyalpha.risk.rules.base import OnlyRiskRuleMetadata

    with pytest.raises(ValueError):
        OnlyRiskRuleMetadata(
            OnlyRiskRuleId("system.bad"),
            OnlyRiskRuleScope.SYSTEM,
            OnlyRiskRuleMode.OBSERVING,
            mandatory=True,
        )
