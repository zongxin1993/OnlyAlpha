"""Account-authoritative Runtime portfolio performance projection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate


class OnlyAccountValuationSource(StrEnum):
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    MARKET_VALUATION = "MARKET_VALUATION"
    COMMITTED_EXECUTION = "COMMITTED_EXECUTION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    FEE_ADJUSTMENT = "FEE_ADJUSTMENT"
    EXTERNAL_CASH_FLOW = "EXTERNAL_CASH_FLOW"
    STATE_CHANGE = "STATE_CHANGE"
    FINAL_SEAL = "FINAL_SEAL"


@dataclass(frozen=True, slots=True)
class OnlyAccountEquityPoint:
    sequence: int
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    trading_day: OnlyTradingDay | None
    currency: OnlyCurrency
    cash: OnlyMoney
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    equity: OnlyMoney
    external_cash_flow: OnlyMoney
    source: OnlyAccountValuationSource
    account_version: int
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyRuntimePortfolioPerformanceSummary:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    authority: str
    currency: OnlyCurrency
    initial_equity: OnlyMoney
    final_equity: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    net_pnl: OnlyMoney
    fees: OnlyMoney
    external_cash_flow: OnlyMoney
    return_since_start: OnlyRate | None
    current_drawdown: OnlyRate
    maximum_drawdown: OnlyRate
    high_water_mark: OnlyMoney
    valuation_count: int
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.authority != "ACCOUNT":
            raise ValueError("Runtime portfolio performance authority must be ACCOUNT")


class OnlyAccountPerformanceProjector:
    """Consumes immutable Account snapshots and never mutates accounting state."""

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self.runtime_id = runtime_id
        self._points: dict[OnlyAccountId, list[OnlyAccountEquityPoint]] = {}
        self._external_cash_flow: dict[OnlyAccountId, Decimal] = {}
        self._sequence = 0

    def record(
        self,
        snapshot: OnlyAccountSnapshot,
        source: OnlyAccountValuationSource,
        *,
        previous: OnlyAccountSnapshot | None = None,
        trading_day: OnlyTradingDay | None = None,
    ) -> OnlyAccountEquityPoint:
        if snapshot.runtime_id != self.runtime_id:
            raise ValueError("Account performance snapshot belongs to another Runtime")
        external = self._external_cash_flow.get(snapshot.account_id, Decimal(0))
        if source is OnlyAccountValuationSource.EXTERNAL_CASH_FLOW:
            if previous is None:
                raise ValueError("External cash flow projection requires the previous Account snapshot")
            external += snapshot.cash.cash_balance.amount - previous.cash.cash_balance.amount
            self._external_cash_flow[snapshot.account_id] = external
        self._sequence += 1
        point = OnlyAccountEquityPoint(
            self._sequence,
            snapshot.runtime_id,
            snapshot.account_id,
            snapshot.updated_at,
            trading_day,
            snapshot.base_currency,
            snapshot.cash.cash_balance,
            snapshot.position_market_value,
            snapshot.realized_pnl,
            snapshot.unrealized_pnl,
            snapshot.fees,
            snapshot.equity,
            OnlyMoney(external, snapshot.base_currency),
            source,
            snapshot.version,
            snapshot.quality_flags,
        )
        self._points.setdefault(snapshot.account_id, []).append(point)
        return point

    def timeline(self, account_id: OnlyAccountId) -> tuple[OnlyAccountEquityPoint, ...]:
        return tuple(self._points.get(account_id, ()))

    def summarize(self, account_id: OnlyAccountId) -> OnlyRuntimePortfolioPerformanceSummary:
        points = self.timeline(account_id)
        if not points:
            raise KeyError(f"Account equity timeline not found: {account_id}")
        initial = points[0]
        final = points[-1]
        peak = initial.equity.amount
        maximum_drawdown = Decimal(0)
        current_drawdown = Decimal(0)
        for point in points:
            peak = max(peak, point.equity.amount)
            current_drawdown = Decimal(0) if peak == 0 else point.equity.amount / peak - Decimal(1)
            maximum_drawdown = min(maximum_drawdown, current_drawdown)
        external = final.external_cash_flow
        quality_flags = set(flag for point in points for flag in point.quality_flags)
        if external.amount != 0:
            return_since_start = None
            quality_flags.add("EXTERNAL_CASH_FLOW_REQUIRES_TWR")
        elif initial.equity.amount == 0:
            return_since_start = None
            quality_flags.add("ZERO_INITIAL_EQUITY")
        else:
            return_since_start = OnlyRate(
                ((final.equity.amount - initial.equity.amount) / initial.equity.amount).quantize(Decimal("0.00000001")),
                8,
            )
        return OnlyRuntimePortfolioPerformanceSummary(
            self.runtime_id,
            account_id,
            "ACCOUNT",
            final.currency,
            initial.equity,
            final.equity,
            final.realized_pnl,
            final.unrealized_pnl,
            OnlyMoney(final.equity.amount - initial.equity.amount - external.amount, final.currency),
            final.fees,
            external,
            return_since_start,
            OnlyRate(current_drawdown.quantize(Decimal("0.00000001")), 8),
            OnlyRate(maximum_drawdown.quantize(Decimal("0.00000001")), 8),
            OnlyMoney(peak, final.currency),
            len(points),
            tuple(sorted(quality_flags)),
        )
