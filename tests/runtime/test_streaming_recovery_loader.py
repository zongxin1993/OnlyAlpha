import pytest

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.runtime import OnlyRuntimeError
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
        "recovery-runtime-3-1",
        "recovery-runtime-3-2",
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
