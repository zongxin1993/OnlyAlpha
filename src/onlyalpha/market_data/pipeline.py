"""Synchronous MarketData workflow and explicit data-ready barrier."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.core.clock import OnlyClock
from onlyalpha.core.time import only_unix_ns_to_datetime_utc
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import (
    OnlyBarReceivedEvent,
    OnlyBarValidatedEvent,
    OnlyDerivedBarCreatedEvent,
    OnlyEvent,
    OnlyKnownEventType,
    OnlyMarketDataPipelineFailedEvent,
    OnlyMarketDataSnapshotReadyEvent,
)
from onlyalpha.indicator.base import OnlyIndicatorId, OnlyIndicatorRequirement
from onlyalpha.indicator.pipeline import (
    OnlyIndicatorFailure,
    OnlyIndicatorPipeline,
    OnlyIndicatorPipelineError,
)
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.snapshot import OnlyBarSnapshot, OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import (
    OnlyBarRevisionPolicy,
    OnlyBarSubscription,
    OnlyLateDataPolicy,
    OnlyMarketDataSequencePolicy,
    only_bar_type_id,
)


class OnlyMarketDataPipelineError(Exception):
    """A critical preparation step failed; Dispatcher must not run."""


@dataclass(frozen=True, slots=True)
class OnlyDataReadyBarrier:
    cache_ready: bool
    aggregation_ready: bool
    indicators_ready: bool
    required_dependencies_ready: bool
    snapshot_ready: bool

    @property
    def is_ready(self) -> bool:
        return all(
            (
                self.cache_ready,
                self.aggregation_ready,
                self.indicators_ready,
                self.required_dependencies_ready,
                self.snapshot_ready,
            )
        )

    def require_ready(self) -> None:
        if not self.is_ready:
            raise OnlyMarketDataPipelineError("market-data barrier is not ready")


@dataclass(frozen=True, slots=True)
class OnlyMarketDataUpdateResult:
    input_bar: OnlyBar
    base_bar: OnlyBar
    derived_bars: tuple[OnlyBar, ...]
    updated_bar_types: frozenset[OnlyBarType]
    updated_indicator_ids: tuple[OnlyIndicatorId, ...]
    optional_indicator_failures: tuple[OnlyIndicatorFailure, ...]
    snapshot: OnlyMarketDataSnapshot
    barrier: OnlyDataReadyBarrier
    sequence: int
    facts: tuple[OnlyEvent, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "input_bar": self.input_bar.to_dict(),
            "base_bar": self.base_bar.to_dict(),
            "derived_bars": [item.to_dict() for item in self.derived_bars],
            "updated_bar_types": [item.to_dict() for item in sorted(self.updated_bar_types, key=only_bar_type_id)],
            "updated_indicator_ids": [str(item) for item in self.updated_indicator_ids],
            "optional_indicator_failures": [str(item.indicator_id) for item in self.optional_indicator_failures],
            "snapshot": self.snapshot.to_dict(),
            "sequence": self.sequence,
            "facts": [item.to_dict() for item in self.facts],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyMarketDataUpdateResult:
        def mapping(value: object) -> Mapping[str, object]:
            if not isinstance(value, Mapping):
                raise ValueError("update result entry must be a mapping")
            return value

        def items(value: object) -> list[object]:
            if not isinstance(value, list):
                raise ValueError("update result entry must be a list")
            return value

        snapshot = OnlyMarketDataSnapshot.from_dict(mapping(payload["snapshot"]))
        return cls(
            input_bar=OnlyBar.from_dict(mapping(payload["input_bar"])),
            base_bar=OnlyBar.from_dict(mapping(payload["base_bar"])),
            derived_bars=tuple(OnlyBar.from_dict(mapping(item)) for item in items(payload["derived_bars"])),
            updated_bar_types=frozenset(
                OnlyBarType.from_dict(mapping(item)) for item in items(payload["updated_bar_types"])
            ),
            updated_indicator_ids=tuple(OnlyIndicatorId(str(item)) for item in items(payload["updated_indicator_ids"])),
            optional_indicator_failures=tuple(
                OnlyIndicatorFailure(
                    OnlyIndicatorId(str(item)),
                    OnlyIndicatorRequirement.OPTIONAL,
                    RuntimeError("restored optional indicator failure"),
                )
                for item in items(payload["optional_indicator_failures"])
            ),
            snapshot=snapshot,
            barrier=OnlyDataReadyBarrier(True, True, True, True, True),
            sequence=int(str(payload["sequence"])),
            facts=tuple(OnlyEvent.from_dict(mapping(item)) for item in items(payload["facts"])),
        )


class OnlyMarketDataPipeline:
    """Owns the strict Bar→aggregation→cache→indicator→Snapshot transaction order."""

    def __init__(
        self,
        engine_id: OnlyEngineId,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClock,
        cache: OnlyMarketDataCache,
        aggregation_manager: OnlyBarAggregationManager,
        indicator_pipeline: OnlyIndicatorPipeline,
        *,
        sequence_policy: OnlyMarketDataSequencePolicy = OnlyMarketDataSequencePolicy.REJECT,
        late_policy: OnlyLateDataPolicy = OnlyLateDataPolicy.REJECT,
        revision_policy: OnlyBarRevisionPolicy = OnlyBarRevisionPolicy.REJECT,
    ) -> None:
        self._engine_id = engine_id
        self._runtime_id = runtime_id
        self._clock = clock
        self._cache = cache
        self._aggregation_manager = aggregation_manager
        self._indicator_pipeline = indicator_pipeline
        self._sequence_policy = sequence_policy
        self._late_policy = late_policy
        self._revision_policy = revision_policy
        self._last_bars: dict[OnlyBarType, OnlyBar] = {}
        self._sequence = 0
        self._event_sequence = 0
        self._failure_facts: list[OnlyEvent] = []

    @property
    def failure_facts(self) -> tuple[OnlyEvent, ...]:
        return tuple(self._failure_facts)

    @property
    def aggregation_manager(self) -> OnlyBarAggregationManager:
        return self._aggregation_manager

    def register_subscription(self, subscription: OnlyBarSubscription) -> None:
        self._aggregation_manager.register_subscription(subscription)

    def unregister_subscription(self, subscription: OnlyBarSubscription) -> None:
        self._aggregation_manager.unregister_subscription(subscription)

    def process_bar(self, bar: OnlyBar) -> OnlyMarketDataUpdateResult:
        self._sequence += 1
        facts: list[OnlyEvent] = [self._fact(OnlyBarReceivedEvent, OnlyKnownEventType.BAR_RECEIVED, bar, bar)]
        try:
            self._validate_input(bar)
            facts.append(self._fact(OnlyBarValidatedEvent, OnlyKnownEventType.BAR_VALIDATED, bar, bar))
            self._cache.update_closed(bar)
            derived = self._aggregation_manager.process(bar)
            updated: dict[OnlyBarType, OnlyBar] = {bar.bar_type: bar}
            for derived_bar in derived:
                self._cache.update_closed(derived_bar)
                updated[derived_bar.bar_type] = derived_bar
                facts.append(
                    self._fact(
                        OnlyDerivedBarCreatedEvent,
                        OnlyKnownEventType.DERIVED_BAR_CREATED,
                        derived_bar,
                        derived_bar,
                    )
                )
            histories = self._cache.histories_all()
            indicator_result = self._indicator_pipeline.update(updated, histories)
            quality_flags = tuple(
                f"OPTIONAL_INDICATOR_MISSING:{failure.indicator_id}" for failure in indicator_result.failures
            )
            now_ns = self._clock.timestamp_ns()
            global_snapshot = OnlyMarketDataSnapshot(
                ts_event=OnlyTimestamp.from_datetime(bar.bar_end),
                ts_init=OnlyTimestamp.from_unix_nanos(now_ns),
                runtime_id=self._runtime_id,
                cluster_id=None,
                instrument_id=bar.instrument_id,
                primary_bar_type=bar.bar_type,
                primary_bar=bar,
                updated_bar_types=frozenset(updated),
                bars=OnlyBarSnapshot(
                    self._cache.latest_all(),
                    histories,
                    {},
                    self._cache.versions_all(),
                ),
                indicator_values=self._indicator_pipeline.values(),
                indicator_versions=self._indicator_pipeline.versions(),
                trading_day=bar.trading_day,
                session_type=bar.session_type,
                quality_flags=quality_flags,
            )
            barrier = OnlyDataReadyBarrier(True, True, True, True, True)
            barrier.require_ready()
            facts.append(
                self._fact(
                    OnlyMarketDataSnapshotReadyEvent,
                    OnlyKnownEventType.MARKET_DATA_SNAPSHOT_READY,
                    bar,
                    {"snapshot_ts_event_ns": global_snapshot.ts_event.unix_nanos},
                )
            )
            self._last_bars[bar.bar_type] = bar
            return OnlyMarketDataUpdateResult(
                bar,
                bar,
                derived,
                frozenset(updated),
                indicator_result.updated_indicator_ids,
                indicator_result.failures,
                global_snapshot,
                barrier,
                self._sequence,
                tuple(facts),
            )
        except Exception as exc:
            failure = self._fact(
                OnlyMarketDataPipelineFailedEvent,
                OnlyKnownEventType.MARKET_DATA_PIPELINE_FAILED,
                bar,
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
            self._failure_facts.append(failure)
            if isinstance(exc, OnlyMarketDataPipelineError):
                raise
            if isinstance(exc, OnlyIndicatorPipelineError):
                raise OnlyMarketDataPipelineError(str(exc)) from exc
            raise OnlyMarketDataPipelineError(f"market-data pipeline failed: {exc}") from exc

    def _validate_input(self, bar: OnlyBar) -> None:
        if not bar.is_closed:
            raise OnlyMarketDataPipelineError("base input must be a closed Bar")
        if bar.bar_type.aggregation_source is not OnlyAggregationSource.EXTERNAL:
            raise OnlyMarketDataPipelineError("base input must be externally aggregated")
        if bar.bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise OnlyMarketDataPipelineError("first-phase base input must be a time Bar")
        if bar.bar_type.specification.step != 1:
            raise OnlyMarketDataPipelineError("first-phase base input must be 1m")
        if bar.ts_event != bar.bar_end:
            raise OnlyMarketDataPipelineError("closed base Bar ts_event must equal bar_end")
        if bar.revision != 0 and self._revision_policy is OnlyBarRevisionPolicy.REJECT:
            raise OnlyMarketDataPipelineError("Bar revisions are not supported")
        previous = self._last_bars.get(bar.bar_type)
        if previous is not None and bar.bar_end == previous.bar_end:
            raise OnlyMarketDataPipelineError("duplicate Bar rejected")
        if previous is not None and bar.bar_end < previous.bar_end and self._late_policy is OnlyLateDataPolicy.REJECT:
            raise OnlyMarketDataPipelineError("late or out-of-order Bar rejected")
        if self._clock.now_utc() < bar.bar_end:
            raise OnlyMarketDataPipelineError("Runtime Clock is earlier than Bar event time")

    def _fact(
        self,
        event_class: type[OnlyEvent],
        event_type: OnlyKnownEventType,
        bar: OnlyBar,
        payload: object,
    ) -> OnlyEvent:
        now_ns = self._clock.timestamp_ns()
        now = only_unix_ns_to_datetime_utc(now_ns, allow_truncation=True)
        self._event_sequence += 1
        return event_class(
            event_type.value,
            bar.bar_end,
            self._engine_id,
            self._runtime_id,
            "market_data_pipeline",
            self._event_sequence,
            payload=payload,
            ts_init=now,
            ts_init_ns=now_ns,
        )
