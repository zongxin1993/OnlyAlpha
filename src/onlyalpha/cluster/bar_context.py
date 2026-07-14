"""Read-only strategy context for a single primary-Bar callback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from onlyalpha.core.clock import OnlyClockView

if TYPE_CHECKING:
    from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot


@dataclass(frozen=True, slots=True)
class OnlyBarContext:
    snapshot: OnlyMarketDataSnapshot
    clock_view: OnlyClockView
