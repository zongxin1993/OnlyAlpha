from __future__ import annotations

from decimal import Decimal

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney


class CanonicalFingerprint:
    def setup(self) -> None:
        self.payload = {
            "orders": [
                {"id": f"order-{index:04d}", "price": Decimal("10.25"), "quantity": index} for index in range(100)
            ],
            "runtime": "BACKTEST",
        }

    def time_fingerprint(self) -> None:
        only_canonical_fingerprint(self.payload)


class DomainSerialization:
    def setup(self) -> None:
        self.money = OnlyMoney(Decimal("123456.78"), OnlyCurrency("CNY", 2))

    def time_to_json(self) -> None:
        self.money.to_json()
