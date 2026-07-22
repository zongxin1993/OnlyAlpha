"""Structural input boundary preventing Analytics from importing Runtime modules."""

from collections.abc import Sequence
from typing import Protocol

from onlyalpha.account.performance import OnlyAccountEquityPoint, OnlyRuntimePortfolioPerformanceSummary
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate
from onlyalpha.result.records import OnlyBacktestFacts
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyLedgerId
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint


class OnlyClusterPerformanceView(Protocol):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    ledger_id: OnlyStrategyLedgerId
    currency: OnlyCurrency
    initial_equity: OnlyMoney
    final_equity: OnlyMoney
    net_pnl: OnlyMoney
    return_since_start: OnlyRate | None
    maximum_drawdown: OnlyRate
    quality_flags: tuple[str, ...]


class OnlyClusterResultView(Protocol):
    @property
    def cluster_id(self) -> OnlyClusterId: ...

    @property
    def performance(self) -> OnlyClusterPerformanceView: ...


class OnlyBacktestResultView(Protocol):
    @property
    def facts(self) -> OnlyBacktestFacts: ...

    @property
    def runtime_performance(self) -> OnlyRuntimePortfolioPerformanceSummary: ...

    @property
    def account_equity_timeline(self) -> tuple[OnlyAccountEquityPoint, ...]: ...

    @property
    def cluster_results(self) -> Sequence[object]: ...

    @property
    def cluster_equity_timelines(self) -> tuple[tuple[OnlyStrategyLedgerEquityPoint, ...], ...]: ...

    @property
    def result_fingerprint(self) -> str: ...
