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
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.account.performance import OnlyAccountEquityPoint, OnlyRuntimePortfolioPerformanceSummary
from onlyalpha.analytics.models import OnlyBacktestAnalysis
from onlyalpha.artifact.models import (
    OnlyArtifactDescriptor,
    OnlyBacktestArtifactManifest,
    OnlyRunArtifactTarget,
)
from onlyalpha.result.diagnostics import OnlyBacktestDiagnostics
from onlyalpha.result.fingerprint import only_result_fingerprint
from onlyalpha.result.records import OnlyBacktestFacts
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint


class OnlyArtifactWriteError(RuntimeError):
    pass


class OnlyBacktestArtifactResultView(Protocol):
    @property
    def facts(self) -> OnlyBacktestFacts: ...

    @property
    def result_fingerprint(self) -> str: ...

    @property
    def diagnostics(self) -> OnlyBacktestDiagnostics: ...

    @property
    def data(self) -> object: ...

    @property
    def runtime_performance(self) -> OnlyRuntimePortfolioPerformanceSummary: ...

    @property
    def cluster_results(self) -> tuple[object, ...]: ...

    @property
    def reconciliation(self) -> object: ...

    @property
    def account_equity_timeline(self) -> tuple[OnlyAccountEquityPoint, ...]: ...

    @property
    def cluster_equity_timelines(self) -> tuple[tuple[OnlyStrategyLedgerEquityPoint, ...], ...]: ...


class OnlyBacktestArtifactWriter:
    def write(
        self,
        result: OnlyBacktestArtifactResultView,
        analysis: OnlyBacktestAnalysis,
        target: OnlyRunArtifactTarget,
    ) -> OnlyBacktestArtifactManifest:
        facts = result.facts
        result_fingerprint = result.result_fingerprint
        diagnostics = result.diagnostics
        data = result.data
        target.run_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".artifact-staging-", dir=target.run_root))
        descriptors: list[OnlyArtifactDescriptor] = []
        try:
            summary = {
                "schema_version": 6,
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
                        "settlement_instructions",
                        "settlement_maturities",
                        "runtime_transactions",
                        "margin",
                        "fees",
                        "market_rule_decisions",
                        "profile_timeline",
                        "compiled_market_rules",
                    )
                },
                "runtime_performance": _json_value(result.runtime_performance),
                "cluster_performance": _json_value(result.cluster_results),
                "reconciliation": _json_value(result.reconciliation),
                "trades": _json_value(analysis.trades),
                "orders": _json_value(analysis.orders),
                "executions": _json_value(analysis.executions),
                "drawdown": _json_value(analysis.drawdown),
                "exposure": _json_value(analysis.exposure),
                "cluster_analytics": _json_value(analysis.cluster_analyses),
                "warnings": list(analysis.warnings),
            }
            self._write_json(staging, "summary.json", "SUMMARY", summary, descriptors)
            self._write_json(
                staging,
                "market_rule_decisions.json",
                "MARKET_RULE_DECISIONS_JSON",
                {"schema_version": 6, "decisions": _json_value(facts.market_rule_decisions)},
                descriptors,
            )
            self._write_json(
                staging,
                "diagnostics.json",
                "DIAGNOSTICS",
                {
                    "schema_version": 6,
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
                {"schema_version": 6, "data": _json_value(data)},
                descriptors,
            )
            tables = {
                "orders.parquet": ("ORDERS", self._orders_table(facts)),
                "executions.parquet": ("EXECUTIONS", self._executions_table(facts)),
                "trades.parquet": ("TRADES", self._trades_table(analysis)),
                "positions.parquet": ("POSITIONS", self._positions_table(facts)),
                "accounts.parquet": ("ACCOUNTS", self._accounts_table(facts)),
                "equity.parquet": (
                    "EQUITY",
                    self._equity_table(
                        result.account_equity_timeline,
                        cluster_id=None,
                    ),
                ),
                "cluster_equity.parquet": (
                    "CLUSTER_EQUITY",
                    self._cluster_equity_table(result.cluster_equity_timelines),
                ),
                "signals.parquet": ("SIGNALS", self._signals_table(facts)),
                "settlements.parquet": (
                    "SETTLEMENTS",
                    _table(_SETTLEMENT_SCHEMA, [_record(item) for item in facts.settlements]),
                ),
                "settlement_instructions.parquet": (
                    "SETTLEMENT_INSTRUCTIONS",
                    _table(
                        _SETTLEMENT_INSTRUCTION_SCHEMA,
                        [_record(item) for item in facts.settlement_instructions],
                    ),
                ),
                "settlement_maturities.parquet": (
                    "SETTLEMENT_MATURITIES",
                    _table(
                        _SETTLEMENT_MATURITY_SCHEMA,
                        [_record(item) for item in facts.settlement_maturities],
                    ),
                ),
                "runtime_transactions.parquet": (
                    "RUNTIME_TRANSACTIONS",
                    _table(
                        _RUNTIME_TRANSACTION_SCHEMA,
                        [_record(item) for item in facts.runtime_transactions],
                    ),
                ),
                "margin.parquet": ("MARGIN", _table(_MARGIN_SCHEMA, [_record(item) for item in facts.margin])),
                "fees.parquet": ("FEES", _table(_FEE_SCHEMA, [_record(item) for item in facts.fees])),
                "fee_schedules.parquet": (
                    "FEE_SCHEDULES",
                    _table(_FEE_SCHEDULE_SCHEMA, _fee_schedule_rows(facts)),
                ),
                "market_fee_packs.parquet": (
                    "MARKET_FEE_PACKS",
                    _table(_MARKET_FEE_PACK_SCHEMA, _market_fee_pack_rows(facts)),
                ),
                "broker_fee_contracts.parquet": (
                    "BROKER_FEE_CONTRACTS",
                    _table(_BROKER_FEE_CONTRACT_SCHEMA, _broker_fee_contract_rows(facts)),
                ),
                "order_fee_bindings.parquet": (
                    "ORDER_FEE_BINDINGS",
                    _table(_ORDER_FEE_BINDING_SCHEMA, _order_fee_binding_rows(facts)),
                ),
                "order_fee_estimates.parquet": ("ORDER_FEE_ESTIMATES", _table(_ORDER_FEE_ESTIMATE_SCHEMA, [])),
                "order_funding_plans.parquet": ("ORDER_FUNDING_PLANS", _table(_ORDER_FUNDING_PLAN_SCHEMA, [])),
                "order_fee_accruals.parquet": ("ORDER_FEE_ACCRUALS", _table(_ORDER_FEE_ACCRUAL_SCHEMA, [])),
                "fee_applications.parquet": (
                    "FEE_APPLICATIONS",
                    _table(_FEE_SCHEMA, [_record(item) for item in facts.fees]),
                ),
                "external_fee_evidence.parquet": (
                    "EXTERNAL_FEE_EVIDENCE",
                    _table(
                        _EXTERNAL_FEE_EVIDENCE_SCHEMA,
                        [_record(item) for item in facts.external_fee_evidence],
                    ),
                ),
                "fee_reconciliations.parquet": (
                    "FEE_RECONCILIATIONS",
                    _table(
                        _FEE_RECONCILIATION_SCHEMA,
                        [_record(item) for item in facts.fee_reconciliations],
                    ),
                ),
                "fee_adjustments.parquet": (
                    "FEE_ADJUSTMENTS",
                    _table(_FEE_ADJUSTMENT_SCHEMA, [_record(item) for item in facts.fee_adjustments]),
                ),
                "unallocated_external_fees.parquet": (
                    "UNALLOCATED_EXTERNAL_FEES",
                    _table(
                        _UNALLOCATED_EXTERNAL_FEE_SCHEMA,
                        [_record(item) for item in facts.unallocated_external_fees],
                    ),
                ),
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
                5,
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
    def _equity_table(points: tuple[OnlyAccountEquityPoint, ...], cluster_id: str | None) -> pa.Table:
        rows = []
        peak: Decimal | None = None
        for item in points:
            peak = item.equity.amount if peak is None else max(peak, item.equity.amount)
            drawdown = item.equity.amount - peak
            rows.append(
                {
                    "sequence": item.sequence,
                    "ts_event": item.ts_event.to_datetime(),
                    "trading_day": None if item.trading_day is None else item.trading_day.value,
                    "runtime_id": str(item.runtime_id),
                    "account_id": str(item.account_id),
                    "cluster_id": cluster_id,
                    "currency": item.currency.code,
                    "cash": item.cash.amount,
                    "market_value": item.position_market_value.amount,
                    "equity": item.equity.amount,
                    "realized_pnl": item.realized_pnl.amount,
                    "unrealized_pnl": item.unrealized_pnl.amount,
                    "commission": Decimal(0),
                    "fees": item.fees.amount,
                    "gross_exposure": item.position_market_value.amount,
                    "net_exposure": item.position_market_value.amount,
                    "position_count": None,
                    "complete": True,
                    "snapshot_phase": item.source.value,
                    "running_peak": peak,
                    "drawdown_amount": drawdown,
                    "drawdown_ratio": (
                        None if peak == 0 else (item.equity.amount / peak - Decimal(1)).quantize(Decimal("1e-18"))
                    ),
                }
            )
        return _table(_EQUITY_SCHEMA, rows)

    @staticmethod
    def _cluster_equity_table(
        timelines: tuple[tuple[OnlyStrategyLedgerEquityPoint, ...], ...],
    ) -> pa.Table:
        rows = []
        for timeline in timelines:
            peak: Decimal | None = None
            for item in timeline:
                peak = item.equity.amount if peak is None else max(peak, item.equity.amount)
                rows.append(
                    {
                        "sequence": item.sequence,
                        "ts_event": item.ts_event.to_datetime(),
                        "trading_day": None,
                        "runtime_id": str(item.key.runtime_id),
                        "account_id": str(item.key.account_id),
                        "cluster_id": str(item.key.cluster_id),
                        "currency": item.currency.code,
                        "cash": item.ledger_cash.amount,
                        "market_value": item.position_market_value.amount,
                        "equity": item.equity.amount,
                        "realized_pnl": item.realized_pnl.amount,
                        "unrealized_pnl": item.unrealized_pnl.amount,
                        "commission": Decimal(0),
                        "fees": item.fees.amount,
                        "gross_exposure": item.position_market_value.amount,
                        "net_exposure": item.position_market_value.amount,
                        "position_count": None,
                        "complete": True,
                        "snapshot_phase": "STRATEGY_LEDGER",
                        "running_peak": peak,
                        "drawdown_amount": item.equity.amount - peak,
                        "drawdown_ratio": item.current_drawdown.value,
                    }
                )
        return _table(_EQUITY_SCHEMA, rows)

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
        ("position_side", pa.string()),
        ("position_effect", pa.string()),
        ("position_mode", pa.string()),
        ("realized_pnl_delta", _DECIMAL),
        ("reference_price", _DECIMAL),
        ("contract_multiplier", _DECIMAL),
        ("market_profile_id", pa.string()),
        ("market_profile_version", pa.string()),
        ("compiled_rule_fingerprint", pa.string()),
        ("reference_fingerprint", pa.string()),
        ("trade_instruction_id", pa.string()),
        ("fee_application_id", pa.string()),
        ("market_fee_pack_id", pa.string()),
        ("market_fee_pack_version", pa.string()),
        ("market_fee_pack_fingerprint", pa.string()),
        ("broker_fee_contract_id", pa.string()),
        ("broker_fee_contract_version", pa.string()),
        ("broker_fee_contract_broker_id", pa.string()),
        ("broker_fee_contract_account_scope", pa.string()),
        ("broker_fee_contract_fingerprint", pa.string()),
        ("fee_binding_fingerprint", pa.string()),
        ("fee_scope_fingerprint", pa.string()),
        ("fee_resolution_fingerprint", pa.string()),
        ("fee_total_charges", _DECIMAL),
        ("fee_total_rebates", _DECIMAL),
        ("fee_signed_cash_effect", _DECIMAL),
        ("market_fee_schedule_ids", pa.list_(pa.string())),
        ("market_fee_schedule_versions", pa.list_(pa.string())),
        ("market_fee_schedule_fingerprints", pa.list_(pa.string())),
        ("broker_fee_schedule_ids", pa.list_(pa.string())),
        ("broker_fee_schedule_versions", pa.list_(pa.string())),
        ("broker_fee_schedule_fingerprints", pa.list_(pa.string())),
        ("settlement_instruction_id", pa.string()),
        ("settlement_status", pa.string()),
        ("margin_instruction_id", pa.string()),
        ("margin_action", pa.string()),
        ("margin_amount", _DECIMAL),
        ("liquidity_side", pa.string()),
        ("fee_breakdown", pa.map_(pa.string(), _DECIMAL)),
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
        ("order_reserved_cash", _DECIMAL),
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
_SETTLEMENT_INSTRUCTION_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("instruction_id", pa.string()),
        ("runtime_id", pa.string()),
        ("account_id", pa.string()),
        ("cluster_id", pa.string()),
        ("instrument_id", pa.string()),
        ("order_id", pa.string()),
        ("trade_id", pa.string()),
        ("position_id", pa.string()),
        ("position_cycle", pa.int64()),
        ("allocation_id", pa.string()),
        ("allocation_cycle", pa.int64()),
        ("side", pa.string()),
        ("quantity", _DECIMAL),
        ("gross_notional", _DECIMAL),
        ("net_cash_flow", _DECIMAL),
        ("trading_day", pa.date32()),
        ("asset_trade_available_on", pa.date32()),
        ("cash_trade_available_on", pa.date32()),
        ("cash_withdrawable_on", pa.date32()),
        ("legal_settlement_on", pa.date32()),
        ("policy_id", pa.string()),
        ("compiled_rule_fingerprint", pa.string()),
        ("reference_fingerprint", pa.string()),
        ("status", pa.string()),
        ("version", pa.int64()),
    ]
)
_SETTLEMENT_MATURITY_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("maturity_identity", pa.string()),
        ("instruction_id", pa.string()),
        ("runtime_id", pa.string()),
        ("account_id", pa.string()),
        ("effective_on", pa.date32()),
        ("transitions_json", pa.string()),
        ("asset_quantity_delta", _DECIMAL),
        ("cash_withdrawable_delta", _DECIMAL),
        ("runtime_sequence", pa.int64()),
        ("transaction_id", pa.string()),
        ("projection_ready", pa.bool_()),
    ]
)
_RUNTIME_TRANSACTION_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("runtime_sequence", pa.int64()),
        ("transaction_id", pa.string()),
        ("operation_kind", pa.string()),
        ("operation_identity", pa.string()),
        ("runtime_id", pa.string()),
        ("account_id", pa.string()),
        ("effective_time", _TIMESTAMP),
        ("projection_ready", pa.bool_()),
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
_FEE_SCHEDULE_SCHEMA = pa.schema(
    [("schedule_id", pa.string()), ("version", pa.string()), ("authority", pa.string()), ("fingerprint", pa.string())]
)
_MARKET_FEE_PACK_SCHEMA = pa.schema(
    [
        ("pack_id", pa.string()),
        ("pack_version", pa.string()),
        ("market_profile_id", pa.string()),
        ("fingerprint", pa.string()),
    ]
)
_BROKER_FEE_CONTRACT_SCHEMA = pa.schema(
    [
        ("contract_id", pa.string()),
        ("contract_version", pa.string()),
        ("broker_id", pa.string()),
        ("account_scope", pa.string()),
        ("fingerprint", pa.string()),
    ]
)
_ORDER_FEE_BINDING_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("binding_fingerprint", pa.string()),
        ("market_fee_pack_id", pa.string()),
        ("market_fee_pack_version", pa.string()),
        ("broker_fee_contract_id", pa.string()),
        ("broker_fee_contract_version", pa.string()),
        ("market_fee_pack_fingerprint", pa.string()),
        ("broker_fee_contract_fingerprint", pa.string()),
        ("scope_fingerprint", pa.string()),
        ("fingerprint", pa.string()),
    ]
)
_ORDER_FEE_ESTIMATE_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("estimated_charges", _DECIMAL),
        ("estimated_rebates", _DECIMAL),
        ("currency", pa.string()),
        ("fingerprint", pa.string()),
    ]
)
_ORDER_FUNDING_PLAN_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("notional_reservation", _DECIMAL),
        ("fee_reservation", _DECIMAL),
        ("total_reservation", _DECIMAL),
        ("currency", pa.string()),
    ]
)
_ORDER_FEE_ACCRUAL_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("component_id", pa.string()),
        ("cumulative_target", _DECIMAL),
        ("cumulative_applied", _DECIMAL),
        ("currency", pa.string()),
        ("version", pa.int64()),
    ]
)
_EXTERNAL_FEE_EVIDENCE_SCHEMA = pa.schema(
    [
        ("evidence_id", pa.string()),
        ("broker_id", pa.string()),
        ("account_id", pa.string()),
        ("scope", pa.string()),
        ("mode", pa.string()),
        ("external_reference", pa.string()),
        ("report_version", pa.string()),
        ("content_fingerprint", pa.string()),
        ("reported_total", _DECIMAL),
        ("currency", pa.string()),
        ("effective_at", _TIMESTAMP),
        ("received_at", _TIMESTAMP),
    ]
)
_FEE_RECONCILIATION_SCHEMA = pa.schema(
    [
        ("reconciliation_id", pa.string()),
        ("evidence_id", pa.string()),
        ("scope", pa.string()),
        ("local_model_amount", _DECIMAL),
        ("prior_adjustments", _DECIMAL),
        ("current_effective_amount", _DECIMAL),
        ("reported_authoritative_amount", _DECIMAL),
        ("difference", _DECIMAL),
        ("currency", pa.string()),
        ("reason", pa.string()),
        ("status", pa.string()),
        ("adjustment_id", pa.string()),
    ]
)
_FEE_ADJUSTMENT_SCHEMA = pa.schema(
    [
        ("adjustment_id", pa.string()),
        ("reconciliation_id", pa.string()),
        ("evidence_id", pa.string()),
        ("account_id", pa.string()),
        ("cluster_id", pa.string()),
        ("direction", pa.string()),
        ("amount", _DECIMAL),
        ("currency", pa.string()),
        ("reason", pa.string()),
    ]
)
_UNALLOCATED_EXTERNAL_FEE_SCHEMA = pa.schema(
    [
        ("account_id", pa.string()),
        ("cumulative_charges", _DECIMAL),
        ("cumulative_refunds", _DECIMAL),
        ("currency", pa.string()),
        ("version", pa.int64()),
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
        ("trading_day", pa.date32()),
        ("profile_version", pa.string()),
        ("side", pa.string()),
        ("quantity", _DECIMAL),
        ("price", _DECIMAL),
        ("trading_phase", pa.string()),
        ("previous_close", _DECIMAL),
        ("tick_size", _DECIMAL),
        ("limit_rate", _DECIMAL),
        ("lower_limit", _DECIMAL),
        ("upper_limit", _DECIMAL),
        ("quantity_policy", pa.string()),
        ("reference_fingerprint", pa.string()),
        ("evaluations", pa.string()),
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


def _market_fee_pack_rows(facts: OnlyBacktestFacts) -> list[dict[str, object]]:
    values: dict[tuple[str, str, str], dict[str, object]] = {}
    for execution in facts.executions:
        if (
            execution.market_fee_pack_id is None
            or execution.market_fee_pack_version is None
            or execution.market_fee_pack_fingerprint is None
        ):
            continue
        key = (
            execution.market_fee_pack_id,
            execution.market_fee_pack_version,
            execution.market_fee_pack_fingerprint,
        )
        values[key] = {
            "pack_id": key[0],
            "pack_version": key[1],
            "market_profile_id": execution.market_profile_id,
            "fingerprint": key[2],
        }
    return [values[key] for key in sorted(values)]


def _broker_fee_contract_rows(facts: OnlyBacktestFacts) -> list[dict[str, object]]:
    values: dict[tuple[str, str, str], dict[str, object]] = {}
    for execution in facts.executions:
        if (
            execution.broker_fee_contract_id is None
            or execution.broker_fee_contract_version is None
            or execution.broker_fee_contract_fingerprint is None
        ):
            continue
        key = (
            execution.broker_fee_contract_id,
            execution.broker_fee_contract_version,
            execution.broker_fee_contract_fingerprint,
        )
        values[key] = {
            "contract_id": key[0],
            "contract_version": key[1],
            "broker_id": execution.broker_fee_contract_broker_id,
            "account_scope": execution.broker_fee_contract_account_scope,
            "fingerprint": key[2],
        }
    return [values[key] for key in sorted(values)]


def _fee_schedule_rows(facts: OnlyBacktestFacts) -> list[dict[str, object]]:
    values: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for execution in facts.executions:
        groups = (
            (
                "MARKET",
                execution.market_fee_schedule_ids,
                execution.market_fee_schedule_versions,
                execution.market_fee_schedule_fingerprints,
            ),
            (
                "BROKER",
                execution.broker_fee_schedule_ids,
                execution.broker_fee_schedule_versions,
                execution.broker_fee_schedule_fingerprints,
            ),
        )
        for authority, schedule_ids, versions, fingerprints in groups:
            for schedule_id, version, fingerprint in zip(schedule_ids, versions, fingerprints, strict=True):
                key = (authority, schedule_id, version, fingerprint)
                values[key] = {
                    "schedule_id": schedule_id,
                    "version": version,
                    "authority": authority,
                    "fingerprint": fingerprint,
                }
    return [values[key] for key in sorted(values)]


def _order_fee_binding_rows(facts: OnlyBacktestFacts) -> list[dict[str, object]]:
    values: dict[tuple[str, str], dict[str, object]] = {}
    for execution in facts.executions:
        if execution.fee_binding_fingerprint is None:
            continue
        key = (str(execution.order_id), execution.fee_binding_fingerprint)
        values[key] = {
            "order_id": key[0],
            "binding_fingerprint": key[1],
            "market_fee_pack_id": execution.market_fee_pack_id,
            "market_fee_pack_version": execution.market_fee_pack_version,
            "broker_fee_contract_id": execution.broker_fee_contract_id,
            "broker_fee_contract_version": execution.broker_fee_contract_version,
            "market_fee_pack_fingerprint": execution.market_fee_pack_fingerprint,
            "broker_fee_contract_fingerprint": execution.broker_fee_contract_fingerprint,
            "scope_fingerprint": execution.fee_scope_fingerprint,
            "fingerprint": key[1],
        }
    return [values[key] for key in sorted(values)]


def _record(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"cannot create artifact record from {type(value).__name__}")
    return {
        item.name: dict(field_value) if isinstance(field_value := getattr(value, item.name), Mapping) else field_value
        for item in fields(value)
    }


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
