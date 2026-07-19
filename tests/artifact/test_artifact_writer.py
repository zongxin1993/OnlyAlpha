from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.artifact import OnlyBacktestArtifactWriter, OnlyRunArtifactTarget
from onlyalpha.artifact.writer import OnlyArtifactWriteError
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.result import only_result_fingerprint
from onlyalpha.result.diagnostics import OnlyBacktestDiagnostics
from onlyalpha.result.records import (
    OnlyAccountResultRecord,
    OnlyBacktestFacts,
    OnlyEquityResultRecord,
    OnlySignalResultRecord,
)


@dataclass(frozen=True)
class OnlyPerformanceFixture:
    initial_equity: OnlyMoney
    final_equity: OnlyMoney


@dataclass(frozen=True)
class OnlyArtifactResultFixture:
    facts: OnlyBacktestFacts
    performance: OnlyPerformanceFixture
    diagnostics: OnlyBacktestDiagnostics
    result_fingerprint: str
    data: object = None


def _result(value: str = "1000000.01") -> OnlyArtifactResultFixture:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    amount = Decimal(value)
    account = OnlyAccountResultRecord(
        sequence=1,
        ts_event=now,
        trading_day=date(2026, 1, 1),
        runtime_id="runtime-1",
        account_id="account-1",
        currency="CNY",
        cash=amount,
        frozen_cash=Decimal("0.01"),
        market_value=Decimal("0"),
        equity=amount,
        realized_pnl=Decimal("0.1"),
        unrealized_pnl=Decimal("0"),
        commission=Decimal("0.01"),
        fees=Decimal("0"),
    )
    equity = OnlyEquityResultRecord(
        sequence=2,
        ts_event=now,
        trading_day=date(2026, 1, 1),
        runtime_id="runtime-1",
        account_id="account-1",
        cluster_id=None,
        currency="CNY",
        cash=amount,
        market_value=Decimal("0"),
        equity=amount,
        realized_pnl=Decimal("0.1"),
        unrealized_pnl=Decimal("0"),
        commission=Decimal("0.01"),
        fees=Decimal("0"),
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
        position_count=0,
        complete=True,
    )
    facts = OnlyBacktestFacts(accounts=(account,), equity=(equity,))
    currency = OnlyCurrency("CNY", 2)
    return OnlyArtifactResultFixture(
        facts,
        OnlyPerformanceFixture(OnlyMoney(amount, currency), OnlyMoney(amount, currency)),
        OnlyBacktestDiagnostics(),
        only_result_fingerprint(facts),
    )


def test_writer_publishes_verified_decimal_parquet_and_manifest_last(tmp_path: Path) -> None:
    result = _result()
    analysis = OnlyBacktestAnalyticsService().analyze(result)

    manifest = OnlyBacktestArtifactWriter().write(result, analysis, OnlyRunArtifactTarget(tmp_path))

    expected = {
        "summary.json",
        "diagnostics.json",
        "data_manifest.json",
        "artifact_manifest.json",
        "orders.parquet",
        "executions.parquet",
        "trades.parquet",
        "positions.parquet",
        "accounts.parquet",
        "equity.parquet",
        "signals.parquet",
    }
    assert expected == {item.name for item in tmp_path.iterdir()}
    assert manifest.result_fingerprint == result.result_fingerprint
    assert manifest.analysis_fingerprint == analysis.analysis_fingerprint
    assert all(len(item.sha256) == 64 for item in manifest.artifacts)
    assert pq.read_table(tmp_path / "orders.parquet").num_rows == 0
    assert pq.read_table(tmp_path / "orders.parquet").num_columns > 0
    account = pq.read_table(tmp_path / "accounts.parquet").to_pylist()[0]
    assert account["cash"] == Decimal("1000000.010000000000000000")
    assert account["frozen_cash"] == Decimal("0.010000000000000000")
    assert not tuple(tmp_path.glob(".artifact-staging-*"))


def test_writer_failure_leaves_no_manifest_or_partial_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _result()
    analysis = OnlyBacktestAnalyticsService().analyze(result)

    def fail_write(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("injected parquet failure")

    monkeypatch.setattr("onlyalpha.artifact.writer.pq.write_table", fail_write)

    with pytest.raises(OnlyArtifactWriteError, match="injected parquet failure"):
        OnlyBacktestArtifactWriter().write(result, analysis, OnlyRunArtifactTarget(tmp_path))

    assert tuple(tmp_path.iterdir()) == ()


def test_writer_preserves_high_precision_factor_scores(tmp_path: Path) -> None:
    result = _result()
    signal = OnlySignalResultRecord(
        sequence=1,
        signal_id="signal-1",
        cluster_id="cluster-1",
        strategy_id="strategy-1",
        instrument_id="600000.XSHG",
        signal_type="GOLDEN_CROSS",
        ts_event=datetime(2026, 1, 1, tzinfo=UTC),
        trading_day=date(2026, 1, 1),
        score=Decimal("0.001234567890123456789012345678"),
        confidence=Decimal("0.9876543210987654321098765432"),
    )
    facts = OnlyBacktestFacts(signals=(signal,), accounts=result.facts.accounts, equity=result.facts.equity)
    precise = OnlyArtifactResultFixture(
        facts,
        result.performance,
        result.diagnostics,
        only_result_fingerprint(facts),
    )
    analysis = OnlyBacktestAnalyticsService().analyze(precise)

    OnlyBacktestArtifactWriter().write(precise, analysis, OnlyRunArtifactTarget(tmp_path))

    stored = pq.read_table(tmp_path / "signals.parquet").to_pylist()[0]
    assert stored["score"] == signal.score
    assert stored["confidence"] == signal.confidence
