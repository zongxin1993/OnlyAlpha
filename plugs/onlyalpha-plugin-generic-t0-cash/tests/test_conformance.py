from decimal import Decimal

from onlyalpha_plugin_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.models import OnlyFeeBasisValues


def test_generic_market_fee_pack_matches_frozen_economic_vector() -> None:
    plugin = only_generic_t0_cash_market_fee_pack()
    basis = OnlyFeeBasisValues(
        OnlyMoney(Decimal("12345.67"), OnlyCurrency("CNY")),
        Decimal("100"),
        Decimal(0),
    )
    assert plugin.schedules[0].rules[0].formula.evaluate(basis) == Decimal("12.34567")
    assert plugin.schedules[0].rules[0].formula.payload() == (
        {"kind": "RATE", "basis": "NOTIONAL", "rate": str(Decimal("0.001"))},
    )
    assert all(rule.authority.value != "BROKER" for schedule in plugin.schedules for rule in schedule.rules)
