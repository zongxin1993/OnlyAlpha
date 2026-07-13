from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.catalog import OnlyInstrumentCatalog
from onlyalpha.domain.market_rules import OnlyFeeSchedule, OnlyFeeScheduleCatalog
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate


def test_catalog_resolves_effective_historical_version(equity_versions) -> None:
    catalog = OnlyInstrumentCatalog(equity_versions)
    assert catalog.resolve(equity_versions[0].instrument_id, datetime(2024, 1, 1, tzinfo=UTC)).instrument_version == 1
    assert catalog.resolve(equity_versions[0].instrument_id, datetime(2026, 1, 1, tzinfo=UTC)).instrument_version == 2


def test_fee_schedule_resolves_by_historical_effective_time() -> None:
    cny = OnlyCurrency("CNY", 2)
    first = OnlyFeeSchedule(
        "equity",
        OnlyRate(Decimal("0.001"), 3),
        OnlyRate(Decimal("0.001"), 3),
        OnlyMoney(Decimal("0.00"), cny),
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
    )
    second = OnlyFeeSchedule(
        "equity",
        OnlyRate(Decimal("0.0005"), 4),
        OnlyRate(Decimal("0.0005"), 4),
        OnlyMoney(Decimal("0.00"), cny),
        datetime(2025, 1, 1, tzinfo=UTC),
    )
    catalog = OnlyFeeScheduleCatalog((first, second))
    assert catalog.resolve("equity", datetime(2024, 1, 1, tzinfo=UTC)) == first
    assert catalog.resolve("equity", datetime(2026, 1, 1, tzinfo=UTC)) == second
