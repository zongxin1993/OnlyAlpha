from datetime import datetime

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market.session_clock import OnlyMarketSessionResolver
from onlyalpha.runtime.streaming.health import only_streaming_data_state
from onlyalpha.runtime.streaming.phase import OnlyStreamingDataState, OnlyStreamingPhase


def _at(calendar, local: datetime) -> OnlyTimestamp:
    return OnlyTimestamp.from_datetime(calendar.to_utc(local))


def test_closed_session_states_are_idle(runtime_calendar) -> None:
    resolver = OnlyMarketSessionResolver(runtime_calendar)
    for local in (
        datetime(2026, 7, 20, 12),
        datetime(2026, 7, 20, 16),
        datetime(2026, 7, 19, 10),
    ):
        observed = _at(runtime_calendar, local)
        assert (
            only_streaming_data_state(
                session=resolver.resolve(observed),
                phase=OnlyStreamingPhase.LIVE,
                source_connected=True,
                observed_at=observed,
                next_expected_bar_end=OnlyTimestamp.from_unix_nanos(observed.unix_nanos - 60_000_000_000),
                grace_seconds=10,
            )
            is OnlyStreamingDataState.IDLE
        )


def test_only_open_overdue_data_is_stale(runtime_calendar) -> None:
    observed = _at(runtime_calendar, datetime(2026, 7, 20, 10))
    state = only_streaming_data_state(
        session=OnlyMarketSessionResolver(runtime_calendar).resolve(observed),
        phase=OnlyStreamingPhase.LIVE,
        source_connected=True,
        observed_at=observed,
        next_expected_bar_end=OnlyTimestamp.from_unix_nanos(observed.unix_nanos - 60_000_000_000),
        grace_seconds=10,
    )
    assert state is OnlyStreamingDataState.STALE


def test_disconnected_and_bootstrap_states_take_precedence(runtime_calendar) -> None:
    observed = _at(runtime_calendar, datetime(2026, 7, 20, 10))
    session = OnlyMarketSessionResolver(runtime_calendar).resolve(observed)
    assert (
        only_streaming_data_state(
            session=session,
            phase=OnlyStreamingPhase.LIVE,
            source_connected=False,
            observed_at=observed,
            next_expected_bar_end=None,
            grace_seconds=10,
        )
        is OnlyStreamingDataState.DISCONNECTED
    )
    assert (
        only_streaming_data_state(
            session=session,
            phase=OnlyStreamingPhase.BOOTSTRAP,
            source_connected=True,
            observed_at=observed,
            next_expected_bar_end=None,
            grace_seconds=10,
        )
        is OnlyStreamingDataState.BOOTSTRAPPING
    )
