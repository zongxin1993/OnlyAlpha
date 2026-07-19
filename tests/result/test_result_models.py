from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.result import (
    OnlyBacktestDiagnostics,
    OnlyBacktestFailure,
    OnlyEquityResultRecord,
    OnlyResultDiagnosticSeverity,
    OnlyResultFailureStage,
    OnlySignalResultRecord,
    only_result_fingerprint,
)


def test_signal_record_is_immutable_and_preserves_decimal() -> None:
    record = OnlySignalResultRecord(
        sequence=1,
        signal_id="signal-1",
        cluster_id="cluster-1",
        strategy_id="strategy-1",
        instrument_id="600000.XSHG",
        signal_type="ENTRY",
        ts_event=datetime(2026, 1, 1, tzinfo=UTC),
        trading_day=date(2026, 1, 1),
        score=Decimal("0.100000000000000001"),
        payload={"source": "fixture"},
    )

    assert record.score == Decimal("0.100000000000000001")
    with pytest.raises(TypeError):
        record.payload["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        record.sequence = 2  # type: ignore[misc]


def test_result_times_must_be_utc_aware() -> None:
    with pytest.raises(OnlyValidationError, match="naive datetime"):
        OnlyEquityResultRecord(
            sequence=1,
            ts_event=datetime(2026, 1, 1),
            trading_day=date(2026, 1, 1),
            runtime_id="runtime-1",
            account_id="account-1",
            cluster_id=None,
            currency="CNY",
            cash=Decimal("1"),
            market_value=Decimal("0"),
            equity=Decimal("1"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            commission=Decimal("0"),
            fees=Decimal("0"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
            position_count=0,
            complete=True,
        )


def test_diagnostics_preserve_first_root_failure() -> None:
    root = OnlyBacktestFailure(
        failure_id="failure-1",
        sequence=3,
        severity=OnlyResultDiagnosticSeverity.ERROR,
        stage=OnlyResultFailureStage.STRATEGY,
        exception_type="OnlyStrategyError",
        message="root cause",
    )
    aggregate = OnlyBacktestFailure(
        failure_id="failure-2",
        sequence=4,
        severity=OnlyResultDiagnosticSeverity.ERROR,
        stage=OnlyResultFailureStage.REPLAY,
        exception_type="RuntimeError",
        message="historical replay failed=1 rejected=0",
    )

    diagnostics = OnlyBacktestDiagnostics((root, aggregate), (), False, 2)

    assert diagnostics.first_failure is root


def test_fingerprint_excludes_run_metadata_and_traceback() -> None:
    first = {
        "run_id": "run-a",
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "traceback": "/private/path/a.py",
        "equity": Decimal("1000000.01"),
    }
    second = {
        "run_id": "run-b",
        "started_at": datetime(2026, 2, 1, tzinfo=UTC),
        "traceback": "/other/path/b.py",
        "equity": Decimal("1000000.01"),
    }

    assert only_result_fingerprint(first) == only_result_fingerprint(second)
