"""External historical-fact loading for same-process streaming recovery."""

from dataclasses import dataclass, replace
from datetime import timedelta

from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.runtime.runtime import OnlyRuntimeError

from .recovery import OnlyStreamingRecoveryPlan, only_expected_closed_bar_boundaries


@dataclass(frozen=True, slots=True)
class OnlyStreamingRecoveryBatch:
    plan: OnlyStreamingRecoveryPlan
    updates: tuple[OnlyMarketDataInboundUpdate, ...]


class OnlyStreamingRecoveryLoader:
    """Load and validate immutable recovery facts without applying semantics."""

    def __init__(
        self,
        *,
        source: OnlyHistoricalDataSource,
        calendar: OnlyTradingCalendar,
        data_version: OnlyDataVersion,
        runtime_id: OnlyRuntimeId,
        source_id: OnlyMarketDataSourceId,
    ) -> None:
        self._source = source
        self._calendar = calendar
        self._data_version = data_version
        self._runtime_id = runtime_id
        self._source_id = source_id

    def load(self, plan: OnlyStreamingRecoveryPlan, accepted_sequence: int) -> OnlyStreamingRecoveryBatch:
        expected = only_expected_closed_bar_boundaries(
            calendar=self._calendar,
            bar_type=plan.bar_type,
            confirmed_bar_end=plan.confirmed_bar_end,
            recovery_target=plan.recovery_target,
        )
        if not expected:
            return OnlyStreamingRecoveryBatch(plan, ())
        request = OnlyHistoricalBarRequest(
            f"recovery-{self._runtime_id}-{plan.generation}",
            frozenset({plan.instrument_id}),
            frozenset({plan.bar_type}),
            OnlyHistoricalDataRange(
                plan.confirmed_bar_end.to_datetime(),
                plan.recovery_target.to_datetime() + timedelta(microseconds=1),
            ),
            self._data_version,
        )
        by_end: dict[int, OnlyMarketDataInboundUpdate] = {}
        for candidate in tuple(self._source.load_bars(request)):
            if not isinstance(candidate.payload, OnlyBarUpdate):
                raise OnlyRuntimeError("historical recovery returned a non-Bar update")
            bar = candidate.payload.bar
            if candidate.instrument_id != plan.instrument_id or bar.bar_type != plan.bar_type:
                raise OnlyRuntimeError("historical recovery identity mismatch")
            if candidate.data_version != self._data_version:
                raise OnlyRuntimeError("historical recovery DataVersion mismatch")
            intervals = self._calendar.session_intervals_for_trading_day(OnlyTradingDay(bar.trading_day))
            in_session = any(start <= bar.bar_start < end and start < bar.bar_end <= end for start, end in intervals)
            if not bar.is_closed or bar.ts_event != bar.bar_end or not in_session:
                raise OnlyRuntimeError("historical recovery returned an invalid closed Bar")
            end_ns = OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos
            if plan.confirmed_bar_end.unix_nanos < end_ns <= plan.recovery_target.unix_nanos:
                existing = by_end.get(end_ns)
                if existing is not None and existing.payload != candidate.payload:
                    raise OnlyRuntimeError("historical recovery returned conflicting duplicate Bars")
                by_end[end_ns] = candidate
        expected_ns = tuple(item.unix_nanos for item in expected)
        if tuple(sorted(by_end)) != expected_ns:
            raise OnlyRuntimeError("historical recovery coverage is incomplete")
        updates = tuple(
            replace(
                by_end[boundary.unix_nanos],
                update_id=OnlyMarketDataUpdateId(f"recovery-{self._runtime_id}-{plan.generation}-{offset}"),
                runtime_id=self._runtime_id,
                source_id=self._source_id,
                source_sequence=OnlyDataSequence(accepted_sequence + offset),
                metadata=by_end[boundary.unix_nanos].metadata
                + (
                    ("provider_sequence", str(int(by_end[boundary.unix_nanos].source_sequence))),
                    ("recovery_generation", str(plan.generation)),
                    ("recovery_source", "historical"),
                ),
            )
            for offset, boundary in enumerate(expected, start=1)
        )
        return OnlyStreamingRecoveryBatch(plan, updates)
