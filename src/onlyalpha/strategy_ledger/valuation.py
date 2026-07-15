"""Allocation-authoritative linear Strategy valuation."""

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier
from onlyalpha.position.models import OnlyPositionAllocationSnapshot
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyMarkPrice,
    OnlyStrategyValuation,
    OnlyStrategyValuationLine,
    only_zero_money,
)


class OnlyStrategyValuationService:
    """Values only Cluster Allocations; account Position cost is never accepted."""

    def value(
        self,
        key: OnlyStrategyLedgerKey,
        allocations: tuple[OnlyPositionAllocationSnapshot, ...],
        marks: tuple[OnlyStrategyMarkPrice, ...],
        multipliers: Mapping[OnlyInstrumentId, OnlyMultiplier],
        ts_event: OnlyTimestamp,
        ts_init: OnlyTimestamp,
        valuation_version: int,
    ) -> OnlyStrategyValuation:
        mark_by_instrument = {item.instrument_id: item for item in marks}
        lines: list[OnlyStrategyValuationLine] = []
        quantum = Decimal(1).scaleb(-key.base_currency.precision)
        for allocation in allocations:
            if allocation.key.runtime_id != key.runtime_id or allocation.key.cluster_id != key.cluster_id:
                raise ValueError("Strategy Valuation received an out-of-scope Allocation")
            if allocation.average_open_price is None:
                continue
            mark = mark_by_instrument.get(allocation.key.instrument_id)
            multiplier = multipliers.get(allocation.key.instrument_id)
            if mark is None or multiplier is None:
                raise ValueError(f"missing Mark/Multiplier for {allocation.key.instrument_id}")
            cost_amount = (
                allocation.average_open_price.value * allocation.total_quantity.value * multiplier.value
            ).quantize(quantum, ROUND_HALF_EVEN)
            market_amount = (mark.mark_price.value * allocation.total_quantity.value * multiplier.value).quantize(
                quantum, ROUND_HALF_EVEN
            )
            lines.append(
                OnlyStrategyValuationLine(
                    allocation.key.instrument_id,
                    OnlyMoney(cost_amount, key.base_currency),
                    OnlyMoney(market_amount, key.base_currency),
                    OnlyMoney(market_amount - cost_amount, key.base_currency),
                    mark.mark_price,
                    mark.price_version,
                )
            )
        lines.sort(key=lambda item: str(item.instrument_id))
        zero = only_zero_money(key.base_currency)
        return OnlyStrategyValuation(
            key,
            ts_event,
            ts_init,
            valuation_version,
            sum_money((item.position_cost for item in lines), zero),
            sum_money((item.position_market_value for item in lines), zero),
            sum_money((item.unrealized_pnl for item in lines), zero),
            tuple(lines),
        )


def sum_money(values: Iterable[OnlyMoney], initial: OnlyMoney) -> OnlyMoney:
    result = initial
    for value in values:
        result = result + value
    return result
