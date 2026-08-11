from decimal import Decimal

from onlyalpha_market_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.models import OnlyFeeBasisValues
from onlyalpha.fee.packs import only_generic_t0_cash_fee_pack
from onlyalpha.market.profiles import only_generic_t0_cash_profile


def test_generic_market_policy_constants_conform_to_legacy_economics() -> None:
    legacy = only_generic_t0_cash_profile()
    assert legacy.session_model.model_id == "GENERIC_DAY"
    assert legacy.position_model.mode.value == "LONG_ONLY"
    assert legacy.short_selling_rule.mode.value == "DISABLED"
    assert legacy.margin_model is None
    assert legacy.settlement_model.compile().legal_settlement_lag == 0
    assert legacy.quantity_rule.allow_fractional is True
    assert legacy.price_rule.daily_limit_rate is None


def test_generic_market_fee_pack_is_economically_identical_to_legacy_authority() -> None:
    legacy = only_generic_t0_cash_fee_pack()
    plugin = only_generic_t0_cash_market_fee_pack()
    basis = OnlyFeeBasisValues(
        OnlyMoney(Decimal("12345.67"), OnlyCurrency("CNY")),
        Decimal("100"),
        Decimal(0),
    )
    assert plugin == legacy
    assert plugin.schedules[0].rules[0].formula.evaluate(basis) == legacy.schedules[0].rules[0].formula.evaluate(basis)
    assert plugin.schedules[0].rules[0].formula.payload() == (
        {"kind": "RATE", "basis": "NOTIONAL", "rate": str(Decimal("0.001"))},
    )
    assert all(rule.authority.value != "BROKER" for schedule in plugin.schedules for rule in schedule.rules)
