"""Staged, verified, deterministic Backtest artifact publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.analytics.models import OnlyBacktestAnalysis
from onlyalpha.artifact.models import (
    OnlyArtifactDescriptor,
    OnlyBacktestArtifactManifest,
    OnlyRunArtifactTarget,
)
from onlyalpha.result.fingerprint import only_result_fingerprint
from onlyalpha.result.records import OnlyBacktestFacts


class OnlyArtifactWriteError(RuntimeError):
    pass


class OnlyBacktestArtifactWriter:
    def write(
        self,
        result: object,
        analysis: OnlyBacktestAnalysis,
        target: OnlyRunArtifactTarget,
    ) -> OnlyBacktestArtifactManifest:
        facts = getattr(result, "facts", None)
        result_fingerprint = getattr(result, "result_fingerprint", None)
        diagnostics = getattr(result, "diagnostics", None)
        data = getattr(result, "data", None)
        if not isinstance(facts, OnlyBacktestFacts) or not isinstance(result_fingerprint, str):
            raise TypeError("Artifact Writer requires an immutable Backtest Result")
        target.run_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".artifact-staging-", dir=target.run_root))
        descriptors: list[OnlyArtifactDescriptor] = []
        try:
            summary = {
                "schema_version": 1,
                "result_fingerprint": result_fingerprint,
                "analysis_fingerprint": analysis.analysis_fingerprint,
                "fact_counts": {
                    name: len(getattr(facts, name))
                    for name in (
                        "signals",
                        "order_requests",
                        "orders",
                        "executions",
                        "positions",
                        "accounts",
                        "equity",
                        "settlements",
                        "margin",
                        "fees",
                        "market_rule_decisions",
                        "profile_timeline",
                        "compiled_market_rules",
                    )
                },
                "performance": _json_value(analysis.performance),
                "trades": _json_value(analysis.trades),
                "orders": _json_value(analysis.orders),
                "executions": _json_value(analysis.executions),
                "drawdown": _json_value(analysis.drawdown),
                "exposure": _json_value(analysis.exposure),
                "warnings": list(analysis.warnings),
            }
            self._write_json(staging, "summary.json", "SUMMARY", summary, descriptors)
            self._write_json(
                staging,
                "diagnostics.json",
                "DIAGNOSTICS",
                {
                    "schema_version": 1,
                    "failure_count": 0 if diagnostics is None else diagnostics.total_failure_count,
                    "warning_count": len(analysis.warnings),
                    "truncated": False if diagnostics is None else diagnostics.truncated,
                    "first_failure": None if diagnostics is None else _json_value(diagnostics.first_failure),
                    "failures": [] if diagnostics is None else _json_value(diagnostics.failures),
                    "warnings": list(analysis.warnings),
                },
                descriptors,
            )
            self._write_json(
                staging,
                "data_manifest.json",
                "DATA_MANIFEST",
                {"schema_version": 1, "data": _json_value(data)},
                descriptors,
            )
            tables = {
                "orders.parquet": ("ORDERS", self._orders_table(facts)),
                "executions.parquet": ("EXECUTIONS", self._executions_table(facts)),
                "trades.parquet": ("TRADES", self._trades_table(analysis)),
                "positions.parquet": ("POSITIONS", self._positions_table(facts)),
                "accounts.parquet": ("ACCOUNTS", self._accounts_table(facts)),
                "equity.parquet": ("EQUITY", self._equity_table(facts, analysis)),
                "signals.parquet": ("SIGNALS", self._signals_table(facts)),
                "settlements.parquet": (
                    "SETTLEMENTS",
                    _table(_SETTLEMENT_SCHEMA, [_record(item) for item in facts.settlements]),
                ),
                "margin.parquet": ("MARGIN", _table(_MARGIN_SCHEMA, [_record(item) for item in facts.margin])),
                "fees.parquet": ("FEES", _table(_FEE_SCHEMA, [_record(item) for item in facts.fees])),
                "market_rule_decisions.parquet": (
                    "MARKET_RULE_DECISIONS",
                    _table(_MARKET_RULE_DECISION_SCHEMA, [_record(item) for item in facts.market_rule_decisions]),
                ),
                "profile_timeline.parquet": (
                    "PROFILE_TIMELINE",
                    _table(_PROFILE_TIMELINE_SCHEMA, [_record(item) for item in facts.profile_timeline]),
                ),
                "compiled_market_rules.parquet": (
                    "COMPILED_MARKET_RULES",
                    _table(_COMPILED_MARKET_RULE_SCHEMA, [_record(item) for item in facts.compiled_market_rules]),
                ),
            }
            for relative_path, (artifact_type, table) in tables.items():
                path = staging / relative_path
                pq.write_table(table, path, compression="zstd", version="2.6")
                verified = pq.read_table(path)
                if verified.schema != table.schema or verified.num_rows != table.num_rows:
                    raise OnlyArtifactWriteError(f"Parquet verification failed: {relative_path}")
                descriptors.append(self._descriptor(path, artifact_type, relative_path, "PARQUET", table.num_rows))
            descriptors.sort(key=lambda item: item.relative_path)
            artifact_content_fingerprint = only_result_fingerprint(
                tuple(
                    (item.artifact_type, item.relative_path, item.row_count, item.content_fingerprint)
                    for item in descriptors
                )
            )
            manifest = OnlyBacktestArtifactManifest(
                1,
                result_fingerprint,
                analysis.analysis_fingerprint,
                artifact_content_fingerprint,
                tuple(descriptors),
            )
            manifest_path = staging / "artifact_manifest.json"
            manifest_path.write_text(_json_dump(_json_value(manifest)), encoding="utf-8")
            json.loads(manifest_path.read_text(encoding="utf-8"))
            for descriptor in descriptors:
                os.replace(staging / descriptor.relative_path, target.run_root / descriptor.relative_path)
            os.replace(manifest_path, target.run_root / "artifact_manifest.json")
            return manifest
        except Exception as exc:
            raise OnlyArtifactWriteError(str(exc)) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _write_json(
        staging: Path,
        relative_path: str,
        artifact_type: str,
        payload: object,
        descriptors: list[OnlyArtifactDescriptor],
    ) -> None:
        path = staging / relative_path
        path.write_text(_json_dump(payload), encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8"))
        descriptors.append(OnlyBacktestArtifactWriter._descriptor(path, artifact_type, relative_path, "JSON", None))

    @staticmethod
    def _descriptor(
        path: Path, artifact_type: str, relative_path: str, format_name: str, row_count: int | None
    ) -> OnlyArtifactDescriptor:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return OnlyArtifactDescriptor(artifact_type, relative_path, format_name, 1, row_count, digest, digest)

    @staticmethod
    def _orders_table(facts: OnlyBacktestFacts) -> pa.Table:
        schema = pa.schema(
            [
                ("sequence", pa.int64()),
                ("request_id", pa.string()),
                ("order_id", pa.string()),
                ("runtime_id", pa.string()),
                ("cluster_id", pa.string()),
                ("strategy_id", pa.string()),
                ("account_id", pa.string()),
                ("instrument_id", pa.string()),
                ("side", pa.string()),
                ("offset", pa.string()),
                ("order_type", pa.string()),
                ("requested_quantity", _DECIMAL),
                ("filled_quantity", _DECIMAL),
                ("remaining_quantity", _DECIMAL),
                ("status", pa.string()),
                ("submitted_at", _TIMESTAMP),
                ("accepted_at", _TIMESTAMP),
                ("completed_at", _TIMESTAMP),
                ("rejection_code", pa.string()),
                ("rejection_message", pa.string()),
                ("tags_json", pa.string()),
            ]
        )
        return _table(
            schema,
            [
                {
                    **_record(item),
                    "tags_json": json.dumps(item.tags, separators=(",", ":")),
                }
                for item in facts.orders
            ],
        )

    @staticmethod
    def _executions_table(facts: OnlyBacktestFacts) -> pa.Table:
        return _table(_EXECUTION_SCHEMA, [_record(item) for item in facts.executions])

    @staticmethod
    def _trades_table(analysis: OnlyBacktestAnalysis) -> pa.Table:
        rows = []
        for item in analysis.trades.trades:
            row = _record(item)
            row["holding_duration_ns"] = int(item.holding_duration.total_seconds() * 1_000_000_000)
            row.pop("holding_duration")
            rows.append(row)
        return _table(_TRADE_SCHEMA, rows)

    @staticmethod
    def _positions_table(facts: OnlyBacktestFacts) -> pa.Table:
        return _table(_POSITION_SCHEMA, [_record(item) for item in facts.positions])

    @staticmethod
    def _accounts_table(facts: OnlyBacktestFacts) -> pa.Table:
        return _table(_ACCOUNT_SCHEMA, [_record(item) for item in facts.accounts])

    @staticmethod
    def _equity_table(facts: OnlyBacktestFacts, analysis: OnlyBacktestAnalysis) -> pa.Table:
        drawdowns = {item.ts_event: item for item in analysis.drawdown.points}
        return _table(
            _EQUITY_SCHEMA,
            [
                {
                    **_record(item),
                    "running_peak": None if item.ts_event not in drawdowns else drawdowns[item.ts_event].running_peak,
                    "drawdown_amount": None
                    if item.ts_event not in drawdowns
                    else drawdowns[item.ts_event].drawdown_amount,
                    "drawdown_ratio": None
                    if item.ts_event not in drawdowns
                    else drawdowns[item.ts_event].drawdown_ratio,
                }
                for item in facts.equity
            ],
        )

    @staticmethod
    def _signals_table(facts: OnlyBacktestFacts) -> pa.Table:
        rows = []
        for item in facts.signals:
            row = _record(item)
            row["payload_json"] = _json_dump(item.payload).strip()
            row.pop("payload", None)
            rows.append(row)
        return _table(_SIGNAL_SCHEMA, rows)


_DECIMAL = pa.decimal128(38, 18)
_RATIO_DECIMAL = pa.decimal128(38, 30)
_TIMESTAMP = pa.timestamp("us", tz="UTC")

_EXECUTION_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("execution_id", pa.string()),
        ("order_id", pa.string()),
        ("request_id", pa.string()),
        ("runtime_id", pa.string()),
        ("cluster_id", pa.string()),
        ("strategy_id", pa.string()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("side", pa.string()),
        ("offset", pa.string()),
        ("quantity", _DECIMAL),
        ("price", _DECIMAL),
        ("turnover", _DECIMAL),
        ("commission", _DECIMAL),
        ("fees", _DECIMAL),
        ("slippage", _DECIMAL),
        ("ts_event", _TIMESTAMP),
        ("trading_day", pa.date32()),
        ("venue", pa.string()),
    ]
)
_TRADE_SCHEMA = pa.schema(
    [
        ("trade_id", pa.string()),
        ("cluster_id", pa.string()),
        ("strategy_id", pa.string()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("direction", pa.string()),
        ("quantity", _DECIMAL),
        ("entry_time", _TIMESTAMP),
        ("exit_time", _TIMESTAMP),
        ("entry_price", _DECIMAL),
        ("exit_price", _DECIMAL),
        ("gross_pnl", _DECIMAL),
        ("commission", _DECIMAL),
        ("fees", _DECIMAL),
        ("net_pnl", _DECIMAL),
        ("holding_duration_ns", pa.int64()),
        ("entry_execution_id", pa.string()),
        ("exit_execution_id", pa.string()),
        ("entry_order_id", pa.string()),
        ("exit_order_id", pa.string()),
    ]
)
_POSITION_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("ts_event", _TIMESTAMP),
        ("trading_day", pa.date32()),
        ("runtime_id", pa.string()),
        ("cluster_id", pa.string()),
        ("strategy_id", pa.string()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("total_quantity", _DECIMAL),
        ("available_quantity", _DECIMAL),
        ("frozen_quantity", _DECIMAL),
        ("average_price", _DECIMAL),
        ("mark_price", _DECIMAL),
        ("market_value", _DECIMAL),
        ("realized_pnl", _DECIMAL),
        ("unrealized_pnl", _DECIMAL),
    ]
)
_ACCOUNT_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("ts_event", _TIMESTAMP),
        ("trading_day", pa.date32()),
        ("runtime_id", pa.string()),
        ("account_id", pa.string()),
        ("currency", pa.string()),
        ("cash", _DECIMAL),
        ("frozen_cash", _DECIMAL),
        ("market_value", _DECIMAL),
        ("equity", _DECIMAL),
        ("realized_pnl", _DECIMAL),
        ("unrealized_pnl", _DECIMAL),
        ("commission", _DECIMAL),
        ("fees", _DECIMAL),
    ]
)
_EQUITY_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("ts_event", _TIMESTAMP),
        ("trading_day", pa.date32()),
        ("runtime_id", pa.string()),
        ("account_id", pa.string()),
        ("cluster_id", pa.string()),
        ("currency", pa.string()),
        ("cash", _DECIMAL),
        ("market_value", _DECIMAL),
        ("equity", _DECIMAL),
        ("realized_pnl", _DECIMAL),
        ("unrealized_pnl", _DECIMAL),
        ("commission", _DECIMAL),
        ("fees", _DECIMAL),
        ("gross_exposure", _DECIMAL),
        ("net_exposure", _DECIMAL),
        ("position_count", pa.int64()),
        ("complete", pa.bool_()),
        ("snapshot_phase", pa.string()),
        ("running_peak", _DECIMAL),
        ("drawdown_amount", _DECIMAL),
        ("drawdown_ratio", _DECIMAL),
    ]
)
_SIGNAL_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("signal_id", pa.string()),
        ("cluster_id", pa.string()),
        ("strategy_id", pa.string()),
        ("instrument_id", pa.string()),
        ("signal_type", pa.string()),
        ("ts_event", _TIMESTAMP),
        ("trading_day", pa.date32()),
        ("factor_id", pa.string()),
        ("score", _RATIO_DECIMAL),
        ("confidence", _RATIO_DECIMAL),
        ("related_order_request_id", pa.string()),
        ("payload_json", pa.string()),
    ]
)
_SETTLEMENT_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("execution_id", pa.string()),
        ("asset_quantity", _DECIMAL),
        ("cash_amount", _DECIMAL),
        ("trade_time", _TIMESTAMP),
        ("asset_available_time", _TIMESTAMP),
        ("cash_available_time", _TIMESTAMP),
        ("settlement_time", _TIMESTAMP),
        ("status", pa.string()),
        ("settlement_model_id", pa.string()),
    ]
)
_MARGIN_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("position_side", pa.string()),
        ("initial_margin", _DECIMAL),
        ("maintenance_margin", _DECIMAL),
        ("used_margin", _DECIMAL),
        ("available_margin", _DECIMAL),
        ("margin_ratio", _RATIO_DECIMAL),
    ]
)
_FEE_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("fee_record_id", pa.string()),
        ("instruction_id", pa.string()),
        ("idempotency_key", pa.string()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("order_id", pa.string()),
        ("trade_id", pa.string()),
        ("fee_type", pa.string()),
        ("authority", pa.string()),
        ("status", pa.string()),
        ("accrued", _DECIMAL),
        ("charged", _DECIMAL),
        ("currency", pa.string()),
        ("schedule_id", pa.string()),
        ("schedule_version", pa.string()),
    ]
)
_MARKET_RULE_DECISION_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("account_id", pa.string()),
        ("instrument_id", pa.string()),
        ("market_profile_id", pa.string()),
        ("rule_set_id", pa.string()),
        ("rule_type", pa.string()),
        ("decision", pa.string()),
        ("reason", pa.string()),
        ("ts_event", _TIMESTAMP),
    ]
)
_PROFILE_TIMELINE_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("runtime_id", pa.string()),
        ("profile_id", pa.string()),
        ("profile_version", pa.string()),
        ("trading_day", pa.date32()),
        ("effective_from", _TIMESTAMP),
        ("effective_to", _TIMESTAMP),
        ("resolved_rules_fingerprint", pa.string()),
        ("reference_fingerprint", pa.string()),
        ("override_fingerprint", pa.string()),
        ("runtime_mode", pa.string()),
    ]
)
_COMPILED_MARKET_RULE_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("instrument_id", pa.string()),
        ("venue_id", pa.string()),
        ("trading_day", pa.date32()),
        ("profile_id", pa.string()),
        ("profile_version", pa.string()),
        ("compiled_rules_fingerprint", pa.string()),
        ("reference_fingerprint", pa.string()),
        ("runtime_mode", pa.string()),
        ("schema_version", pa.string()),
    ]
)


def _record(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"cannot create artifact record from {type(value).__name__}")
    return {item.name: getattr(value, item.name) for item in fields(value)}


def _table(schema: pa.Schema, rows: list[dict[str, object]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return ((value.days * 86400 + value.seconds) * 1_000_000_000) + value.microseconds * 1000
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)


def _json_dump(value: object) -> str:
    return (
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    )
