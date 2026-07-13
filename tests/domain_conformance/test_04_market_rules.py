from decimal import Decimal

from onlyalpha.domain.market_rules import OnlyLotSizeRule, OnlyMarketRule, OnlySettlementRule


def test_same_equity_can_use_different_rules(equity, buy_request) -> None:
    cn = OnlyMarketRule(
        "CN", lot_size_rule=OnlyLotSizeRule(Decimal("100"), Decimal("1")), settlement_rule=OnlySettlementRule(1)
    )
    us = OnlyMarketRule(
        "US", lot_size_rule=OnlyLotSizeRule(Decimal("0.001"), Decimal("0.001")), settlement_rule=OnlySettlementRule(1)
    )
    assert not cn.validate_order(equity, buy_request).is_valid
    assert us.validate_order(equity, buy_request).is_valid
