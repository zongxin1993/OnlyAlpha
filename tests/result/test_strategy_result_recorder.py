from datetime import UTC, date, datetime

import pytest

from onlyalpha.result.strategy import OnlyStrategyResultRecorder


def test_strategy_signal_recorder_has_stable_identity_and_seals() -> None:
    first = OnlyStrategyResultRecorder("cluster-1", "strategy-1")
    second = OnlyStrategyResultRecorder("cluster-1", "strategy-1")
    kwargs = {
        "signal_type": "ENTRY",
        "instrument_id": "600000.XSHG",
        "ts_event": datetime(2026, 1, 1, tzinfo=UTC),
        "trading_day": date(2026, 1, 1),
    }

    first_record = first.record_signal(**kwargs)  # type: ignore[arg-type]
    second_record = second.record_signal(**kwargs)  # type: ignore[arg-type]

    assert first_record.signal_id == second_record.signal_id
    assert first.seal() == (first_record,)
    with pytest.raises(RuntimeError, match="sealed"):
        first.record_signal(**kwargs)  # type: ignore[arg-type]
