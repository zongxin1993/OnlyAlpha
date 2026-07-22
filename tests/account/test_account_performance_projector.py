from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountConfig, OnlyAccountValuation
from onlyalpha.account.performance import OnlyAccountPerformanceProjector, OnlyAccountValuationSource
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney


def test_runtime_drawdown_uses_account_equity_path_not_either_cluster_path() -> None:
    runtime_id = OnlyRuntimeId("drawdown-runtime")
    account_id = OnlyAccountId("shared-account")
    currency = OnlyCurrency("CNY", 2)
    accounts = OnlyAccountManager(runtime_id)
    created = accounts.create_account(
        OnlyAccountConfig(
            runtime_id,
            account_id,
            "virtual",
            OnlyAccountType.CASH,
            currency,
            OnlyMoney(Decimal("1000.00"), currency),
        ),
        OnlyTimestamp(1),
    )
    projector = OnlyAccountPerformanceProjector(runtime_id)
    projector.record(created, OnlyAccountValuationSource.ACCOUNT_CREATED)

    for version, market_value in enumerate(("200.00", "100.00"), 1):
        snapshot = accounts.apply_valuation(
            OnlyAccountValuation(
                runtime_id,
                account_id,
                OnlyMoney(Decimal(market_value), currency),
                OnlyMoney(Decimal(market_value), currency),
                OnlyTimestamp(version + 1),
                version,
            )
        ).after
        projector.record(snapshot, OnlyAccountValuationSource.MARKET_VALUATION)

    summary = projector.summarize(account_id)

    # Aggregate path: 1000 -> 1200 -> 1100. Cluster paths used by this
    # accounting scenario are 400 -> 700 -> 500 and 600 -> 500 -> 600.
    assert summary.maximum_drawdown.value == Decimal("-0.08333333")
    assert summary.maximum_drawdown.value != Decimal("-0.28571429")
    assert summary.maximum_drawdown.value != Decimal("-0.16666667")
    assert summary.high_water_mark.amount == Decimal("1200.00")
    assert summary.valuation_count == 3


def test_same_timestamp_points_keep_explicit_sequence() -> None:
    runtime_id = OnlyRuntimeId("sequence-runtime")
    account_id = OnlyAccountId("shared-account")
    currency = OnlyCurrency("CNY", 2)
    accounts = OnlyAccountManager(runtime_id)
    snapshot = accounts.create_account(
        OnlyAccountConfig(
            runtime_id,
            account_id,
            "virtual",
            OnlyAccountType.CASH,
            currency,
            OnlyMoney(Decimal("1000.00"), currency),
        ),
        OnlyTimestamp(1),
    )
    projector = OnlyAccountPerformanceProjector(runtime_id)

    first = projector.record(snapshot, OnlyAccountValuationSource.ACCOUNT_CREATED)
    second = projector.record(snapshot, OnlyAccountValuationSource.FINAL_SEAL)

    assert first.ts_event == second.ts_event
    assert (first.sequence, second.sequence) == (1, 2)
    assert len(projector.timeline(account_id)) == 2
