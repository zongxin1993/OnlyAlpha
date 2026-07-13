from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.value import OnlyMoney, OnlyPrice


def test_money_quantization_hash_and_json_are_deterministic(equity, cny) -> None:
    values = [
        (
            OnlyMoney(Decimal("1.00"), cny) + OnlyMoney(Decimal("2.00"), cny),
            equity.quantize_price(OnlyPrice(Decimal("10.03"), 2), rounding=ROUND_HALF_EVEN),
        )
        for _ in range(10)
    ]
    assert len({(money.to_json(), price.to_json(), hash(money), hash(price)) for money, price in values}) == 1
