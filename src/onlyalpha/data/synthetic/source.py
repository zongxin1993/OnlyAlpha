"""Calendar-aware deterministic synthetic HistoricalDataSource."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from onlyalpha.data.enums import OnlyMarketDataCapability, OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalQuoteRequest,
    OnlyHistoricalTradeRequest,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataQuality,
)
from onlyalpha.data.ports import OnlyMarketDataCapabilities
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyBarAggregation, OnlySessionType
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
)
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION

ONLY_SYNTHETIC_PLUGIN_DESCRIPTOR = OnlyPluginDescriptor(
    "synthetic",
    OnlyPluginType.DATA_SOURCE,
    "1.0.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha Synthetic Historical Data",
    "OnlyAlpha",
    OnlyDataSourceCapabilities(historical_bars=True),
)


class OnlySyntheticPriceSegmentType(StrEnum):
    FLAT = "FLAT"
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    OSCILLATION = "OSCILLATION"
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    VOLATILITY_CONTRACTION = "VOLATILITY_CONTRACTION"


@dataclass(frozen=True, slots=True)
class OnlySyntheticPriceSegment:
    segment_type: OnlySyntheticPriceSegmentType
    duration_bars: int
    end_price: Decimal | None = None
    amplitude: Decimal = Decimal("0")
    cycle_length: int = 10
    volatility: Decimal = Decimal("0.02")
    volume_multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.duration_bars <= 0 or self.cycle_length <= 1:
            raise ValueError("synthetic segment duration and cycle length must be positive")
        if self.volatility < 0 or self.volume_multiplier < 0:
            raise ValueError("synthetic volatility and volume multiplier cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySyntheticVolumeModel:
    base_volume: OnlyQuantity
    variation_steps: int = 0

    def __post_init__(self) -> None:
        if self.base_volume.value < 0 or self.variation_steps < 0:
            raise ValueError("synthetic volume values cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySyntheticNoiseModel:
    enabled: bool = False
    maximum_price_steps: int = 0

    def __post_init__(self) -> None:
        if self.maximum_price_steps < 0:
            raise ValueError("maximum_price_steps cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySyntheticInstrumentDataConfig:
    instrument: OnlyInstrument
    trading_calendar: OnlyTradingCalendar
    bar_type: OnlyBarType
    initial_price: OnlyPrice
    price_segments: tuple[OnlySyntheticPriceSegment, ...]
    volume_model: OnlySyntheticVolumeModel
    noise_model: OnlySyntheticNoiseModel = OnlySyntheticNoiseModel()

    def __post_init__(self) -> None:
        if self.bar_type.instrument_id != self.instrument.instrument_id:
            raise ValueError("synthetic BarType must belong to its Instrument")
        if self.bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise ValueError("synthetic source supports TIME Bars only")
        if self.bar_type.specification.step <= 0:
            raise ValueError("synthetic TIME Bar step must be positive")
        if not self.price_segments or not self.instrument.validates_price(self.initial_price):
            raise ValueError("synthetic source requires segments and a valid initial price")
        if not self.instrument.validates_quantity(self.volume_model.base_volume):
            raise ValueError("synthetic base volume must satisfy Instrument quantity rules")


@dataclass(frozen=True, slots=True)
class OnlySyntheticHistoricalDataSourceConfig:
    source_id: OnlyMarketDataSourceId
    runtime_id: OnlyRuntimeId
    data_version: OnlyDataVersion
    instruments: tuple[OnlySyntheticInstrumentDataConfig, ...]
    random_seed: int

    def __post_init__(self) -> None:
        if not self.instruments:
            raise ValueError("synthetic source requires at least one Instrument config")
        ids = [item.instrument.instrument_id for item in self.instruments]
        if len(ids) != len(set(ids)):
            raise ValueError("synthetic source Instrument configs must be unique")


class _OnlyDeterministicNoise:
    """Small integer PRNG with a fully specified cross-process sequence."""

    def __init__(self, seed: int) -> None:
        self._state = seed & ((1 << 64) - 1)

    def signed_step(self, maximum: int) -> int:
        if maximum == 0:
            return 0
        self._state = (6364136223846793005 * self._state + 1442695040888963407) & ((1 << 64) - 1)
        return int(self._state % (2 * maximum + 1)) - maximum


class OnlySyntheticHistoricalDataSource:
    """Generates versioned OHLCV facts through the formal historical Port."""

    _CAPABILITIES: OnlyMarketDataCapabilities = frozenset({OnlyMarketDataCapability.QUERY_HISTORICAL_BAR})

    def __init__(self, config: OnlySyntheticHistoricalDataSourceConfig) -> None:
        self.config = config
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_SYNTHETIC_PLUGIN_DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    def initialize(self) -> None:
        if self._state is OnlyPluginLifecycleState.CREATED:
            self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> None:
        if self._state is OnlyPluginLifecycleState.CREATED:
            self.initialize()
        if self._state is OnlyPluginLifecycleState.INITIALIZED:
            self._state = OnlyPluginLifecycleState.CONNECTING
            self._state = OnlyPluginLifecycleState.CONNECTED

    def start(self) -> None:
        if self._state is OnlyPluginLifecycleState.INITIALIZED:
            self.connect()
        if self._state is OnlyPluginLifecycleState.CONNECTED:
            self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        if self._state is OnlyPluginLifecycleState.STOPPED:
            return
        self._state = OnlyPluginLifecycleState.STOPPING
        self._state = OnlyPluginLifecycleState.STOPPED

    def close(self) -> None:
        self.stop()

    def health(self) -> OnlyPluginHealth:
        if self._state is OnlyPluginLifecycleState.RUNNING:
            return OnlyPluginHealth(OnlyPluginHealthStatus.HEALTHY)
        if self._state is OnlyPluginLifecycleState.STOPPED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.STOPPED)
        return OnlyPluginHealth(OnlyPluginHealthStatus.UNKNOWN)

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self.config.source_id

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return self._CAPABILITIES

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        if request.data_version != self.config.data_version:
            return OnlyHistoricalDataStream((), request.batch_size)
        updates: list[OnlyMarketDataInboundUpdate] = []
        sequence = 0
        for config in sorted(self.config.instruments, key=lambda item: str(item.instrument.instrument_id)):
            if (
                config.instrument.instrument_id not in request.instrument_ids
                or config.bar_type not in request.bar_types
            ):
                continue
            generated = self._generate(config, request)
            for update in generated:
                sequence += 1
                updates.append(self._with_sequence(update, sequence))
        return OnlyHistoricalDataStream(tuple(updates), request.batch_size)

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def _generate(
        self,
        config: OnlySyntheticInstrumentDataConfig,
        request: OnlyHistoricalBarRequest,
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        start = request.data_range.start_time
        end = request.data_range.end_time
        local_start = config.trading_calendar.to_local(start).date() - timedelta(days=2)
        local_end = config.trading_calendar.to_local(end).date() + timedelta(days=2)
        bar_delta = timedelta(minutes=config.bar_type.specification.step)
        slots: list[tuple[datetime, datetime, OnlyTradingDay, OnlySessionType]] = []
        day = local_start
        while day <= local_end:
            trading_day = OnlyTradingDay(day)
            sessions = config.trading_calendar.sessions_for_trading_day(trading_day)
            for session, (session_start, session_end) in zip(
                sessions,
                config.trading_calendar.session_intervals_for_trading_day(trading_day),
                strict=True,
            ):
                current = session_start
                while current + bar_delta <= session_end:
                    bar_end = current + bar_delta
                    if bar_end >= start and bar_end < end:
                        slots.append((current, bar_end, trading_day, session.session_type))
                    current = bar_end
            day += timedelta(days=1)
        noise = _OnlyDeterministicNoise(self.config.random_seed ^ self._stable_seed(config))
        updates: list[OnlyMarketDataInboundUpdate] = []
        previous = config.initial_price.value
        segment_index = 0
        segment_offset = 0
        for bar_index, (bar_start, bar_end, trading_day, session_type) in enumerate(slots):
            if segment_index >= len(config.price_segments):
                break
            segment = config.price_segments[segment_index]
            close = self._segment_close(previous, segment, segment_offset)
            if config.noise_model.enabled:
                close += config.instrument.tick_size.value * noise.signed_step(config.noise_model.maximum_price_steps)
            close = self._quantize(close, config.instrument.tick_size.value)
            open_value = previous
            spread = self._spread(segment, segment_offset)
            high = self._quantize(max(open_value, close) + spread, config.instrument.tick_size.value)
            low = self._quantize(
                max(config.instrument.tick_size.value, min(open_value, close) - spread),
                config.instrument.tick_size.value,
            )
            volume = self._volume(config, segment, noise)
            bar = OnlyBar(
                bar_type=config.bar_type,
                open=OnlyPrice(open_value, config.instrument.price_precision),
                high=OnlyPrice(high, config.instrument.price_precision),
                low=OnlyPrice(low, config.instrument.price_precision),
                close=OnlyPrice(close, config.instrument.price_precision),
                volume=volume,
                quote_volume=None,
                turnover=None,
                trade_count=max(1, int(volume.value / config.instrument.step_size.value)),
                open_interest=None,
                bar_start=bar_start,
                bar_end=bar_end,
                ts_event=bar_end,
                ts_init=bar_end,
                is_closed=True,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=trading_day.value,
                session_type=session_type,
            )
            timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
            updates.append(
                OnlyMarketDataInboundUpdate(
                    OnlyMarketDataUpdateId(f"SYN-{self.source_id}-{bar_index + 1:012d}-{timestamp.unix_nanos}"),
                    self.config.runtime_id,
                    self.source_id,
                    OnlyDataSequence(bar_index + 1),
                    self.config.data_version,
                    config.instrument.instrument_id,
                    data_type=self._bar_data_type(),
                    payload=OnlyBarUpdate(bar),
                    ts_event=timestamp,
                    ts_init=timestamp,
                    quality=OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
                    metadata=(
                        ("generator", "OnlySyntheticHistoricalDataSource"),
                        ("random_seed", str(self.config.random_seed)),
                    ),
                )
            )
            previous = close
            segment_offset += 1
            if segment_offset >= segment.duration_bars:
                segment_index += 1
                segment_offset = 0
        return tuple(updates)

    @staticmethod
    def _bar_data_type() -> OnlyMarketDataType:
        return OnlyMarketDataType.BAR

    def _with_sequence(self, update: OnlyMarketDataInboundUpdate, sequence: int) -> OnlyMarketDataInboundUpdate:
        timestamp = update.ts_event.unix_nanos
        return OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"SYN-{self.source_id}-{sequence:012d}-{timestamp}"),
            update.runtime_id,
            update.source_id,
            OnlyDataSequence(sequence),
            update.data_version,
            update.instrument_id,
            update.data_type,
            update.payload,
            update.ts_event,
            update.ts_init,
            update.quality,
            update.correlation_id,
            update.metadata,
        )

    @staticmethod
    def _stable_seed(config: OnlySyntheticInstrumentDataConfig) -> int:
        value = f"{config.instrument.instrument_id}|{config.bar_type.to_json()}"
        result = 0
        for char in value:
            result = (result * 131 + ord(char)) & ((1 << 64) - 1)
        return result

    @classmethod
    def _segment_close(
        cls,
        previous: Decimal,
        segment: OnlySyntheticPriceSegment,
        offset: int,
    ) -> Decimal:
        progress = Decimal(offset + 1) / Decimal(segment.duration_bars)
        target = previous if segment.end_price is None else segment.end_price
        if segment.segment_type is OnlySyntheticPriceSegmentType.FLAT:
            return previous
        if segment.segment_type in {OnlySyntheticPriceSegmentType.UPTREND, OnlySyntheticPriceSegmentType.DOWNTREND}:
            start = previous if offset == 0 else previous
            remaining = max(segment.duration_bars - offset, 1)
            return start + (target - start) / Decimal(remaining)
        if segment.segment_type is OnlySyntheticPriceSegmentType.OSCILLATION:
            phase = offset % segment.cycle_length
            half = Decimal(segment.cycle_length) / Decimal(2)
            triangle = Decimal(phase) / half if Decimal(phase) <= half else Decimal(2) - Decimal(phase) / half
            return previous + segment.amplitude * (triangle * Decimal(2) - Decimal(1))
        if segment.segment_type is OnlySyntheticPriceSegmentType.GAP_UP:
            return previous + (segment.amplitude if offset == 0 else Decimal(0))
        if segment.segment_type is OnlySyntheticPriceSegmentType.GAP_DOWN:
            return previous - (segment.amplitude if offset == 0 else Decimal(0))
        direction = Decimal(1) if offset % 2 == 0 else Decimal(-1)
        scale = (
            progress
            if segment.segment_type is OnlySyntheticPriceSegmentType.VOLATILITY_EXPANSION
            else Decimal(1) - progress
        )
        return previous + direction * segment.amplitude * scale

    @staticmethod
    def _spread(segment: OnlySyntheticPriceSegment, offset: int) -> Decimal:
        if segment.segment_type is OnlySyntheticPriceSegmentType.VOLATILITY_EXPANSION:
            return segment.volatility * Decimal(offset + 1)
        if segment.segment_type is OnlySyntheticPriceSegmentType.VOLATILITY_CONTRACTION:
            return segment.volatility * Decimal(segment.duration_bars - offset)
        return segment.volatility

    @staticmethod
    def _quantize(value: Decimal, increment: Decimal) -> Decimal:
        units = (value / increment).to_integral_value(rounding=ROUND_HALF_EVEN)
        return units * increment

    @staticmethod
    def _volume(
        config: OnlySyntheticInstrumentDataConfig,
        segment: OnlySyntheticPriceSegment,
        noise: _OnlyDeterministicNoise,
    ) -> OnlyQuantity:
        step = config.instrument.step_size.value
        raw = config.volume_model.base_volume.value * segment.volume_multiplier
        raw += step * Decimal(noise.signed_step(config.volume_model.variation_steps))
        units = max(Decimal(0), (raw / step).to_integral_value(rounding=ROUND_DOWN))
        return OnlyQuantity(units * step, config.instrument.quantity_precision)
