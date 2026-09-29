from datetime import timedelta
from decimal import Decimal

import pytest

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.market import OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.runtime.runtime import OnlyRuntimeError
from onlyalpha.runtime.streaming.continuity import OnlyStreamingContinuityTracker
from onlyalpha.runtime.streaming.recovery import OnlyStreamingRecoveryPlan, OnlyStreamingRecoveryReason
from onlyalpha.runtime.streaming.recovery_loader import OnlyStreamingRecoveryLoader

pytestmark = pytest.mark.unit


class _Source:
    source_id = OnlyMarketDataSourceId("historical")
    capabilities = frozenset()

    def __init__(self, updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        self.updates = updates

    def load_bars(self, request: object) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        del request
        return self.updates

    def load_trades(self, request: object) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        del request
        return self.updates


def _update(bar, sequence: int) -> OnlyMarketDataInboundUpdate:
    stamp = OnlyTimestamp.from_datetime(bar.bar_end)
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(f"provider-{sequence}"),
        OnlyRuntimeId("provider"),
        OnlyMarketDataSourceId("provider"),
        OnlyDataSequence(sequence),
        OnlyDataVersion("v1"),
        bar.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        stamp,
        stamp,
    )


def test_loader_validates_and_normalizes_immutable_external_facts(runtime_calendar, make_runtime_bar) -> None:
    confirmed = make_runtime_bar(0)
    first = make_runtime_bar(1)
    second = make_runtime_bar(2)
    source = _Source((_update(second, 90), _update(first, 80)))
    plan = OnlyStreamingRecoveryPlan(
        3,
        OnlyStreamingRecoveryReason.GAP,
        confirmed.instrument_id,
        confirmed.bar_type,
        OnlyTimestamp.from_datetime(confirmed.bar_end),
        OnlyTimestamp.from_datetime(second.bar_end),
    )
    loader = OnlyStreamingRecoveryLoader(
        source=source,  # type: ignore[arg-type]
        calendar=runtime_calendar,
        data_version=OnlyDataVersion("v1"),
        runtime_id=OnlyRuntimeId("runtime"),
        source_id=OnlyMarketDataSourceId("live"),
    )

    batch = loader.load(plan, 10)

    assert batch.plan is plan
    assert tuple(int(item.source_sequence) for item in batch.updates) == (11, 12)
    assert tuple(str(item.update_id) for item in batch.updates) == (
        "provider-80",
        "provider-90",
    )
    assert tuple(item.payload.bar for item in batch.updates) == (first, second)
    assert dict(batch.updates[0].metadata) == {
        "provider_sequence": "80",
        "recovery_generation": "3",
        "recovery_source": "historical",
    }


def test_loader_rejects_incomplete_coverage(runtime_calendar, make_runtime_bar) -> None:
    confirmed = make_runtime_bar(0)
    target = make_runtime_bar(2)
    plan = OnlyStreamingRecoveryPlan(
        1,
        OnlyStreamingRecoveryReason.GAP,
        confirmed.instrument_id,
        confirmed.bar_type,
        OnlyTimestamp.from_datetime(confirmed.bar_end),
        OnlyTimestamp.from_datetime(target.bar_end),
    )
    loader = OnlyStreamingRecoveryLoader(
        source=_Source((_update(target, 1),)),  # type: ignore[arg-type]
        calendar=runtime_calendar,
        data_version=OnlyDataVersion("v1"),
        runtime_id=OnlyRuntimeId("runtime"),
        source_id=OnlyMarketDataSourceId("live"),
    )

    with pytest.raises(OnlyRuntimeError, match="coverage is incomplete"):
        loader.load(plan, 0)


def test_loader_recovers_trade_suffix_by_provider_sequence(runtime_calendar, make_runtime_bar) -> None:
    template = make_runtime_bar(0)
    source_id = OnlyMarketDataSourceId("live")
    version = OnlyDataVersion("v1")
    confirmed = OnlyTimestamp.from_datetime(template.bar_end)

    def update(sequence: int, seconds: int) -> OnlyMarketDataInboundUpdate:
        timestamp = OnlyTimestamp.from_datetime(template.bar_end + timedelta(seconds=seconds))
        trade = OnlyTradeTick(
            template.instrument_id,
            timestamp.to_datetime(),
            timestamp.to_datetime(),
            sequence,
            str(source_id),
            OnlyPrice(Decimal("10"), 2),
            OnlyQuantity(Decimal("1"), 0),
            OnlyOrderSide.BUY,
            OnlyTradeId(f"trade-{sequence}"),
        )
        return OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"trade-{sequence}"),
            OnlyRuntimeId("provider"),
            source_id,
            OnlyDataSequence(sequence),
            version,
            template.instrument_id,
            OnlyMarketDataType.TRADE,
            OnlyTradeTickUpdate(trade),
            timestamp,
            timestamp,
            sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    loader = OnlyStreamingRecoveryLoader(
        source=_Source((update(12, 2), update(11, 1))),  # type: ignore[arg-type]
        calendar=runtime_calendar,
        data_version=version,
        runtime_id=OnlyRuntimeId("runtime"),
        source_id=source_id,
    )
    plan = OnlyStreamingRecoveryPlan(
        2,
        OnlyStreamingRecoveryReason.DISCONNECTED,
        template.instrument_id,
        None,
        confirmed,
        OnlyTimestamp.from_datetime(template.bar_end + timedelta(seconds=3)),
        data_type=OnlyMarketDataType.TRADE,
    )

    batch = loader.load(plan, 10)

    assert tuple(int(item.source_sequence) for item in batch.updates) == (11, 12)
    assert all(item.runtime_id == OnlyRuntimeId("runtime") for item in batch.updates)


@pytest.mark.parametrize(
    ("high_instrument", "low_instrument"),
    (
        (OnlyInstrumentId.parse("BTCUSDT.BINANCE"), OnlyInstrumentId.parse("ETHUSDT.BINANCE")),
        (OnlyInstrumentId.parse("ETHUSDT.BINANCE"), OnlyInstrumentId.parse("BTCUSDT.BINANCE")),
    ),
)
def test_trade_recovery_cursor_is_scoped_per_instrument_after_checkpoint(
    runtime_calendar,
    make_runtime_bar,
    high_instrument: OnlyInstrumentId,
    low_instrument: OnlyInstrumentId,
) -> None:
    template = make_runtime_bar(0)
    source_id = OnlyMarketDataSourceId("live")
    version = OnlyDataVersion("v1")
    confirmed = OnlyTimestamp.from_datetime(template.bar_end)

    def update(instrument_id: OnlyInstrumentId, sequence: int) -> OnlyMarketDataInboundUpdate:
        timestamp = OnlyTimestamp.from_unix_nanos(confirmed.unix_nanos + sequence)
        trade = OnlyTradeTick(
            instrument_id,
            timestamp.to_datetime(),
            timestamp.to_datetime(),
            sequence,
            str(source_id),
            OnlyPrice(Decimal("10"), 2),
            OnlyQuantity(Decimal("1"), 0),
            OnlyOrderSide.BUY,
            OnlyTradeId(f"{instrument_id}-{sequence}"),
        )
        return OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"{instrument_id}-{sequence}"),
            OnlyRuntimeId("provider"),
            source_id,
            OnlyDataSequence(sequence),
            version,
            instrument_id,
            OnlyMarketDataType.TRADE,
            OnlyTradeTickUpdate(trade),
            timestamp,
            timestamp,
            sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    tracker = OnlyStreamingContinuityTracker()
    for item in (update(high_instrument, 1000), update(low_instrument, 10)):
        tracker.advance(item)
    restored = OnlyStreamingContinuityTracker()
    restored.restore_checkpoint(tracker.capture_checkpoint())

    suffix = tuple(update(low_instrument, sequence) for sequence in (11, 12, 13))
    loader = OnlyStreamingRecoveryLoader(
        source=_Source(tuple(reversed(suffix))),  # type: ignore[arg-type]
        calendar=runtime_calendar,
        data_version=version,
        runtime_id=OnlyRuntimeId("runtime"),
        source_id=source_id,
    )
    plan = OnlyStreamingRecoveryPlan(
        1,
        OnlyStreamingRecoveryReason.RESTART,
        low_instrument,
        None,
        confirmed,
        suffix[-1].ts_event,
        data_type=OnlyMarketDataType.TRADE,
    )

    batch = loader.load(plan, restored.accepted_sequence(restored.key(update(low_instrument, 10))))

    assert tuple(int(item.source_sequence) for item in batch.updates) == (11, 12, 13)
