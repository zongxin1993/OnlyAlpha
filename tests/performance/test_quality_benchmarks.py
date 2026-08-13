from __future__ import annotations

from decimal import Decimal

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney

pytestmark = pytest.mark.performance


def test_benchmark_canonical_fingerprint(benchmark: BenchmarkFixture) -> None:
    payload = {
        "orders": [{"id": f"order-{index:04d}", "price": Decimal("10.25"), "quantity": index} for index in range(100)],
        "runtime": "BACKTEST",
    }

    result = benchmark(only_canonical_fingerprint, payload)

    assert len(result) == 64


def test_benchmark_domain_serialization(benchmark: BenchmarkFixture) -> None:
    money = OnlyMoney(Decimal("123456.78"), OnlyCurrency("CNY", 2))

    result = benchmark(money.to_json)

    assert OnlyMoney.from_json(result) == money
