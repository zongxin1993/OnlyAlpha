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
        currency = analysis.performance.currency
        return {
            "status": result.status.value,
            "runtime_id": str(result.runtime_id),
            "cluster_count": len(result.run.cluster_ids),
            "bar_count": result.data.processed_bar_count,
            "signal_count": len(result.facts.signals),
            "order_count": analysis.orders.submitted_count,
            "execution_count": analysis.executions.execution_count,
            "trade_count": analysis.trades.trade_count,
            "initial_equity": _money(analysis.performance.initial_equity, currency),
            "ending_equity": _money(analysis.performance.ending_equity, currency),
            "net_profit": str(analysis.performance.net_profit),
            "total_return": _optional_decimal(analysis.performance.total_return),
            "max_drawdown": _optional_decimal(analysis.drawdown.max_drawdown_ratio),
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
        currency = analysis.performance.currency or ""
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
            "Performance",
            f"  Initial Equity: {_number(analysis.performance.initial_equity)} {currency}".rstrip(),
            f"  Ending Equity: {_number(analysis.performance.ending_equity)} {currency}".rstrip(),
            f"  Net Profit: {_number(analysis.performance.net_profit)} {currency}".rstrip(),
            f"  Total Return: {_percent(analysis.performance.total_return)}",
            f"  Max Drawdown: {_percent(analysis.drawdown.max_drawdown_ratio)}",
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
        currency = analysis.performance.currency or ""
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
            "## Performance Summary",
            _table(
                (
                    ("Initial equity", f"{analysis.performance.initial_equity} {currency}".rstrip()),
                    ("Ending equity", f"{analysis.performance.ending_equity} {currency}".rstrip()),
                    ("Net profit", f"{analysis.performance.net_profit} {currency}".rstrip()),
                    ("Total return", _percent(analysis.performance.total_return)),
                    ("Max drawdown", _percent(analysis.drawdown.max_drawdown_ratio)),
                )
            ),
            "## Final Account",
            _table((("Account records", len(accounts)), ("Final accounts", len(result.final_accounts)))),
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
