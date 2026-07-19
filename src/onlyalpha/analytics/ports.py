"""Structural input boundary preventing Analytics from importing Runtime modules."""

from typing import Protocol

from onlyalpha.domain.value import OnlyMoney
from onlyalpha.result.records import OnlyBacktestFacts


class OnlyBacktestPerformanceView(Protocol):
    @property
    def initial_equity(self) -> OnlyMoney: ...

    @property
    def final_equity(self) -> OnlyMoney: ...


class OnlyBacktestResultView(Protocol):
    @property
    def facts(self) -> OnlyBacktestFacts: ...

    @property
    def performance(self) -> OnlyBacktestPerformanceView: ...

    @property
    def result_fingerprint(self) -> str: ...
