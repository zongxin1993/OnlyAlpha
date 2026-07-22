"""Report adapters which format existing Result, Analysis, and Artifact values."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from onlyalpha.analytics import OnlyBacktestAnalysis
from onlyalpha.artifact import OnlyBacktestArtifactManifest
from onlyalpha.runtime.backtest.result import OnlyBacktestResult


class OnlyJsonBacktestReport:
    """Build the concise, automation-friendly backtest projection."""

    def render(
        self,
        result: OnlyBacktestResult,
        analysis: OnlyBacktestAnalysis,
        manifest: OnlyBacktestArtifactManifest,
    ) -> dict[str, object]:
        diagnostics = result.diagnostics
        first_failure = diagnostics.first_failure
        return {
            "status": result.status.value,
            "runtime_id": str(result.runtime_id),
            "cluster_count": len(result.run.cluster_ids),
            "bar_count": result.data.processed_bar_count,
            "signal_count": len(result.facts.signals),
            "order_count": analysis.orders.submitted_count,
            "execution_count": analysis.executions.execution_count,
            "trade_count": analysis.trades.trade_count,
            "runtime_performance": _json_value(result.runtime_performance),
            "cluster_performance": [_json_value(item.performance) for item in result.cluster_results],
            "reconciliation": _json_value(result.reconciliation),
            "failure_count": diagnostics.total_failure_count,
            "first_failure": None if first_failure is None else _json_value(first_failure),
            "result_fingerprint": result.result_fingerprint,
            "analysis_fingerprint": analysis.analysis_fingerprint,
            "artifact_content_fingerprint": manifest.artifact_content_fingerprint,
            "summary_path": _artifact_path(manifest, "SUMMARY"),
            "diagnostics_path": _artifact_path(manifest, "DIAGNOSTICS"),
            "artifact_manifest_path": "artifact_manifest.json",
        }


class OnlyConsoleBacktestReport:
    """Render a compact terminal summary without deriving new metrics."""

    def render(
        self,
        result: OnlyBacktestResult,
        analysis: OnlyBacktestAnalysis,
        manifest: OnlyBacktestArtifactManifest,
    ) -> str:
        runtime_performance = result.runtime_performance
        currency = runtime_performance.currency.code
        artifacts = {item.artifact_type: item.relative_path for item in manifest.artifacts}
        lines = [
            "Run",
            f"  Status: {result.status.value}",
            f"  Runtime ID: {result.runtime_id}",
            f"  Period: {result.run.start_time.to_datetime().isoformat()} – {result.run.end_time.to_datetime().isoformat()}",
            f"  Bars: {result.data.processed_bar_count}",
            "",
            "Trading",
            f"  Signals: {len(result.facts.signals)}",
            f"  Orders: {analysis.orders.submitted_count}",
            f"  Executions: {analysis.executions.execution_count}",
            f"  Trades: {analysis.trades.trade_count}",
            "",
            "Runtime Portfolio Performance (Account authority)",
            f"  Account: {runtime_performance.account_id}",
            f"  Initial Equity: {_number(runtime_performance.initial_equity.amount)} {currency}".rstrip(),
            f"  Ending Equity: {_number(runtime_performance.final_equity.amount)} {currency}".rstrip(),
            f"  Net PnL: {_number(runtime_performance.net_pnl.amount)} {currency}".rstrip(),
            f"  Fees: {_number(runtime_performance.fees.amount)} {currency}".rstrip(),
            f"  Return: {_percent(None if runtime_performance.return_since_start is None else runtime_performance.return_since_start.value)}",
            f"  Max Drawdown: {_percent(runtime_performance.maximum_drawdown.value)}",
            f"  High Water Mark: {_number(runtime_performance.high_water_mark.amount)} {currency}".rstrip(),
            f"  Valuation Count: {runtime_performance.valuation_count}",
            "",
            "Cluster Performance (Strategy Ledger authority)",
            *(
                f"  {item.cluster_id}: ledger={item.performance.ledger_id}, allocated={item.performance.initial_equity.amount}, "
                f"final={item.performance.final_equity.amount}, pnl={item.performance.net_pnl.amount}, "
                f"fees={item.performance.fees.amount}, return={_percent(None if item.performance.return_since_start is None else item.performance.return_since_start.value)}, "
                f"max_drawdown={_percent(item.performance.maximum_drawdown.value)}, trades={item.performance.trade_count}"
                for item in result.cluster_results
            ),
            "",
            "Reconciliation",
            f"  Status: {result.reconciliation.status.value}",
            f"  Account Equity: {runtime_performance.final_equity.amount}",
            f"  Sum Cluster Ledger Equity: {sum((item.performance.final_equity.amount for item in result.cluster_results), Decimal(0))}",
            f"  Difference: {runtime_performance.final_equity.amount - sum((item.performance.final_equity.amount for item in result.cluster_results), Decimal(0))}",
            "",
            "Artifacts",
            f"  Summary: {artifacts.get('SUMMARY', 'unavailable')}",
            f"  Trades: {artifacts.get('TRADES', 'unavailable')}",
            f"  Equity: {artifacts.get('EQUITY', 'unavailable')}",
        ]
        return "\n".join(lines)


class OnlyMarkdownBacktestReport:
    """Render the stable first-generation Markdown report (without charts)."""

    def render(
        self,
        result: OnlyBacktestResult,
        analysis: OnlyBacktestAnalysis,
        manifest: OnlyBacktestArtifactManifest,
    ) -> str:
        currency = result.runtime_performance.currency.code
        positions = result.facts.positions or tuple()
        accounts = result.facts.accounts or tuple()
        diagnostics = result.diagnostics
        sections = [
            "# Backtest Report",
            "",
            "## Run Summary",
            _table(
                (
                    ("Status", result.status.value),
                    ("Runtime", str(result.runtime_id)),
                    ("Clusters", ", ".join(str(item) for item in result.run.cluster_ids)),
                    ("Start", result.run.start_time.to_datetime().isoformat()),
                    ("End", result.run.end_time.to_datetime().isoformat()),
                )
            ),
            "## Data Summary",
            _table(
                (
                    ("Processed bars", result.data.processed_bar_count),
                    ("Duplicates", result.data.duplicate_count),
                    ("Gaps", result.data.gap_count),
                )
            ),
            "## Strategy Summary",
            _table((("Signals", len(result.facts.signals)), ("Strategies", len(result.cluster_results)))),
            "## Order Summary",
            _table(
                (
                    ("Submitted", analysis.orders.submitted_count),
                    ("Filled", analysis.orders.filled_count),
                    ("Rejected", analysis.orders.rejected_count),
                )
            ),
            "## Execution Summary",
            _table(
                (
                    ("Executions", analysis.executions.execution_count),
                    ("Turnover", analysis.executions.gross_turnover),
                    ("Fees", analysis.executions.fees),
                )
            ),
            "## Trade Summary",
            _table(
                (
                    ("Trades", analysis.trades.trade_count),
                    ("Winning", analysis.trades.winning_trade_count),
                    ("Losing", analysis.trades.losing_trade_count),
                    ("Win rate", _percent(analysis.trades.win_rate)),
                )
            ),
            "## Runtime Portfolio Performance (Account authority)",
            _table(
                (
                    ("Account", result.runtime_performance.account_id),
                    ("Initial equity", f"{result.runtime_performance.initial_equity.amount} {currency}".rstrip()),
                    ("Ending equity", f"{result.runtime_performance.final_equity.amount} {currency}".rstrip()),
                    ("Net PnL", f"{result.runtime_performance.net_pnl.amount} {currency}".rstrip()),
                    ("Fees", result.runtime_performance.fees.amount),
                    (
                        "Return",
                        _percent(
                            None
                            if result.runtime_performance.return_since_start is None
                            else result.runtime_performance.return_since_start.value
                        ),
                    ),
                    ("Max drawdown", _percent(result.runtime_performance.maximum_drawdown.value)),
                    ("High water mark", result.runtime_performance.high_water_mark.amount),
                    ("Valuation count", result.runtime_performance.valuation_count),
                )
            ),
            "## Cluster Performance (Strategy Ledger authority)",
            "\n".join(
                f"- `{item.cluster_id}` / `{item.performance.ledger_id}`: allocated={item.performance.initial_equity.amount}, "
                f"final={item.performance.final_equity.amount}, pnl={item.performance.net_pnl.amount}, fees={item.performance.fees.amount}, "
                f"return={_percent(None if item.performance.return_since_start is None else item.performance.return_since_start.value)}, "
                f"max_drawdown={_percent(item.performance.maximum_drawdown.value)}, trades={item.performance.trade_count}"
                for item in result.cluster_results
            ),
            "## Runtime/Cluster Reconciliation",
            _table(
                (
                    ("Status", result.reconciliation.status.value),
                    ("Account equity", result.runtime_performance.final_equity.amount),
                    (
                        "Sum Cluster equity",
                        sum((item.performance.final_equity.amount for item in result.cluster_results), Decimal(0)),
                    ),
                    ("Difference count", len(result.reconciliation.differences)),
                )
            ),
            "## Final Account",
            _table((("Account records", len(accounts)), ("Final account", result.final_account.account_id))),
            "## Final Positions",
            _table((("Position records", len(positions)), ("Open positions", len(result.final_positions)))),
            "## Diagnostics",
            _table(
                (
                    ("Failures", diagnostics.total_failure_count),
                    ("Warnings", len(diagnostics.warnings) + len(analysis.warnings)),
                    ("First failure", diagnostics.first_failure.message if diagnostics.first_failure else "None"),
                )
            ),
            "## Artifacts",
            "\n".join(f"- `{item.artifact_type}`: `{item.relative_path}`" for item in manifest.artifacts),
            "",
            "## Fingerprints",
            _table(
                (
                    ("Result", result.result_fingerprint),
                    ("Analysis", analysis.analysis_fingerprint),
                    ("Artifact content", manifest.artifact_content_fingerprint),
                )
            ),
        ]
        return "\n\n".join(sections).rstrip() + "\n"


def _artifact_path(manifest: OnlyBacktestArtifactManifest, artifact_type: str) -> str | None:
    return next((item.relative_path for item in manifest.artifacts if item.artifact_type == artifact_type), None)


def _money(value: Decimal, currency: str | None) -> dict[str, str | None]:
    return {"value": str(value), "currency": currency}


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _number(value: Decimal) -> str:
    return f"{value:,.2f}"


def _percent(value: Decimal | None) -> str:
    return "N/A" if value is None else f"{value * Decimal(100):.2f}%"


def _table(rows: tuple[tuple[str, object], ...]) -> str:
    body = "\n".join(f"| {key} | {value} |" for key, value in rows)
    return f"| Metric | Value |\n| --- | --- |\n{body}"


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (Decimal, datetime, date, timedelta, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value
