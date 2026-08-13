"""Shared Engine-only harness for CN A-share Production Durable Backtest V1."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
)
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig, OnlyEngineRunResult
from onlyalpha.plugin.api import OnlyCheckpointCapability
from onlyalpha.runtime.backtest.result import OnlyBacktestResult
from onlyalpha.runtime.defaults import OnlyEngineServices
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId
from onlyalpha.transaction import OnlyCommittedRuntimeTransaction

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "tests" / "fixtures" / "conformance" / "cn_a_share_production_v1"
PRODUCT_ID = "CN_A_SHARE_DURABLE_BACKTEST_V1"
PRODUCT_CONTRACT_VERSION = "1"
MARKET_PRODUCT_ID = "CN_A_SHARE_CASH"
MARKET_PRODUCT_VERSION = "2025.1"
MARKET_FEE_PACK_ID = "CN_A_SHARE_PRODUCTION_MARKET_FEES"
MARKET_FEE_PACK_VERSION = "2025.06.30"
BROKER_FEE_CONTRACT_ID = "VIRTUAL:BACKTEST-ACCOUNT:COMMISSION"
BROKER_FEE_CONTRACT_VERSION = "2025.01"
ACCOUNT_ID = "backtest-account"
CLUSTER_ID = "cn-a-share-production"


class OnlyCnAshareProductScenario(StrEnum):
    ROUND_TRIP = "ROUND_TRIP"
    BUY_ONLY = "BUY_ONLY"
    BUY_PARTIAL_CANCEL = "BUY_PARTIAL_CANCEL"
    SELL_PARTIAL_CANCEL = "SELL_PARTIAL_CANCEL"
    SELL_AFTER_SETTLEMENT = "SELL_AFTER_SETTLEMENT"


@dataclass(frozen=True, slots=True)
class OnlyCnAshareProductionFixture:
    manifest: Mapping[str, object]
    bars: tuple[Mapping[str, object], ...]
    references: tuple[Mapping[str, object], ...]

    @property
    def fingerprint(self) -> str:
        return str(self.manifest["content_fingerprint"])


@dataclass(frozen=True, slots=True)
class OnlyCnAshareProductRun:
    engine: OnlyEngine
    engine_result: OnlyEngineRunResult
    runtime_result: OnlyBacktestResult
    config: OnlyClusterRunConfig


def _json_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    return cast(dict[str, object], value)


def _json_objects(value: object, label: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return tuple(_json_object(item, f"{label}[{index}]") for index, item in enumerate(value))


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def only_load_cn_a_share_production_fixture(root: Path = DATASET) -> OnlyCnAshareProductionFixture:
    """Load only the sealed local fixture; every mismatch fails closed."""

    manifest = _json_object(_read_json(root / "manifest.json"), "manifest")
    files = _json_object(manifest.get("files"), "manifest.files")
    if set(files) != {"bars.json", "references.json"}:
        raise ValueError("CN A-share Production fixture file set is not frozen")
    for name, expected in files.items():
        if Path(name).name != name or not isinstance(expected, str):
            raise ValueError("CN A-share Production fixture file identity is invalid")
        if _sha256(root / name) != expected:
            raise ValueError(f"CN A-share Production fixture fingerprint mismatch: {name}")
    expected_content = manifest.get("content_fingerprint")
    canonical = {key: value for key, value in manifest.items() if key != "content_fingerprint"}
    actual_content = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected_content != actual_content:
        raise ValueError("CN A-share Production fixture manifest fingerprint mismatch")
    if manifest.get("product_id") != PRODUCT_ID or manifest.get("product_contract_version") != PRODUCT_CONTRACT_VERSION:
        raise ValueError("CN A-share Production Product Contract identity mismatch")
    policy = _json_object(manifest.get("runtime_policy"), "manifest.runtime_policy")
    if policy != {
        "data_access": "FROZEN_LOCAL_ONLY",
        "network_access": "FORBIDDEN",
        "implicit_fallback": "FORBIDDEN",
    }:
        raise ValueError("CN A-share Production fixture runtime policy mismatch")
    return OnlyCnAshareProductionFixture(
        manifest,
        _json_objects(_read_json(root / "bars.json"), "bars"),
        _json_objects(_read_json(root / "references.json"), "references"),
    )


def only_cn_a_share_product_broker_fee_contract() -> dict[str, object]:
    """The explicit immutable Broker-owned commission authority for V1."""

    return {
        "schema_version": "1",
        "contract_id": BROKER_FEE_CONTRACT_ID,
        "contract_version": BROKER_FEE_CONTRACT_VERSION,
        "broker_id": "virtual",
        "account_scope": {"scope_type": "EXACT_ACCOUNT", "account_id": ACCOUNT_ID},
        "schedules": [
            {
                "schedule_id": "VIRTUAL_BACKTEST_COMMISSION",
                "version": "1",
                "effective_from": "2025-01-01",
                "currency": {"code": "CNY", "precision": 2},
                "source": "BROKER_CONTRACT:VIRTUAL:BACKTEST-ACCOUNT:COMMISSION:2025.01",
                "rules": [
                    {
                        "rule_id": "cash-equity-commission",
                        "fee_type": "BROKER_COMMISSION",
                        "authority": "BROKER",
                        "economic_direction": "CHARGE",
                        "basis": "NOTIONAL",
                        "rate": "0.0003",
                        "calculation_scope": "ORDER_CUMULATIVE",
                        "resolution_policy": "ORDER_FIXED",
                        "minimum": "5.00",
                        "rounding_quantum": "0.01",
                        "rounding_mode": "HALF_UP",
                        "pipeline": "ROUND_THEN_BOUNDS",
                    }
                ],
            }
        ],
    }


@dataclass(frozen=True, slots=True)
class OnlyCnAshareProductStrategyConfig(OnlyStrategyConfig):
    cluster_id: OnlyClusterId | None = None
    account_id: OnlyAccountId | None = None
    instrument_id: OnlyInstrumentId | None = None
    trade_quantity: OnlyQuantity | None = None
    scenario: OnlyCnAshareProductScenario = OnlyCnAshareProductScenario.ROUND_TRIP

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyCnAshareProductStrategyConfig:
        instruments = values.get("instruments")
        raw_instrument = values.get("instrument_id")
        if not isinstance(instruments, Mapping) or not isinstance(raw_instrument, str):
            raise TypeError("CN A-share Product Strategy requires instrument Reference data")
        instrument_id = next((item for item in instruments if str(item) == raw_instrument), None)
        if not isinstance(instrument_id, OnlyInstrumentId):
            raise ValueError(f"unknown CN A-share Product instrument: {raw_instrument}")
        instrument = instruments[instrument_id]
        cluster_id = values["cluster_id"]
        account_id = values["account_id"]
        return cls(
            OnlyStrategyId(str(values.get("strategy_id", "cn-a-share-product-strategy"))),
            (),
            {},
            cluster_id if isinstance(cluster_id, OnlyClusterId) else OnlyClusterId(str(cluster_id)),
            account_id if isinstance(account_id, OnlyAccountId) else OnlyAccountId(str(account_id)),
            instrument_id,
            OnlyQuantity(Decimal(str(values.get("trade_quantity", "1000"))), instrument.quantity_precision),
            OnlyCnAshareProductScenario(str(values.get("scenario", OnlyCnAshareProductScenario.ROUND_TRIP.value))),
        )


class OnlyCnAshareProductStrategy(OnlyStrategy):
    """Deterministic product intent; all economic writes remain Runtime-owned."""

    def __init__(self, config: OnlyCnAshareProductStrategyConfig) -> None:
        super().__init__(config)
        self.config = config
        self._bar_count = 0
        self._request_sequence = 0
        self._entry_submitted = False
        self._entry_trading_day: date | None = None
        self._same_day_sell_attempted = False
        self._exit_submitted = False
        self._cancel_requested = False
        self._submission_results: list[dict[str, object]] = []
        self._cancel_results: list[dict[str, object]] = []

    def on_initialize(self) -> None:
        if any(
            item is None
            for item in (
                self.config.cluster_id,
                self.config.account_id,
                self.config.instrument_id,
                self.config.trade_quantity,
            )
        ):
            raise ValueError("CN A-share Product Strategy configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._bar_count += 1
        bar = context.primary_bar
        if not isinstance(bar, OnlyBar):
            raise TypeError("CN A-share Product Strategy requires an OnlyBar primary input")
        if not self._entry_submitted:
            self._entry_trading_day = bar.trading_day
            self._submit(context, OnlyOrderSide.BUY, self._quantity(), "PRODUCT_BUY_OPEN")
            self._entry_submitted = True
            return

        open_orders = context.strategy.orders.list_open()
        partial = next(
            (
                item
                for item in open_orders
                if item.status is OnlyOrderStatus.PARTIALLY_FILLED and item.filled_quantity.value > 0
            ),
            None,
        )
        if self.config.scenario is OnlyCnAshareProductScenario.BUY_PARTIAL_CANCEL:
            if partial is not None and partial.side is OnlyOrderSide.BUY and not self._cancel_requested:
                self._cancel(context, partial.order_id, "PRODUCT_BUY_PARTIAL_CANCEL")
            return
        if self.config.scenario is OnlyCnAshareProductScenario.BUY_ONLY:
            return

        if (
            self.config.scenario is OnlyCnAshareProductScenario.SELL_PARTIAL_CANCEL
            and partial is not None
            and partial.side is OnlyOrderSide.SELL
            and not self._cancel_requested
        ):
            self._cancel(context, partial.order_id, "PRODUCT_SELL_PARTIAL_CANCEL")
            return

        instrument_id = self._instrument_id()
        allocation = context.strategy.positions.cluster.get(instrument_id)
        if allocation is None or allocation.total_quantity.value <= 0 or open_orders:
            return
        entry_day = self._entry_trading_day
        if entry_day is None:
            raise RuntimeError("CN A-share Product entry TradingDay is unavailable")
        if (
            self.config.scenario is OnlyCnAshareProductScenario.ROUND_TRIP
            and bar.trading_day == entry_day
            and allocation.total_quantity == self._quantity()
            and not self._same_day_sell_attempted
        ):
            self._submit(context, OnlyOrderSide.SELL, allocation.total_quantity, "PRODUCT_SAME_DAY_SELL")
            self._same_day_sell_attempted = True
            return
        if bar.trading_day > entry_day and allocation.available_quantity.value > 0 and not self._exit_submitted:
            self._submit(context, OnlyOrderSide.SELL, allocation.available_quantity, "PRODUCT_SELL_CLOSE")
            self._exit_submitted = True

    def _submit(
        self,
        context: OnlyStrategyBarContext,
        side: OnlyOrderSide,
        quantity: OnlyQuantity,
        tag: str,
    ) -> None:
        self._request_sequence += 1
        cluster_id = self._cluster_id()
        account_id = self._account_id()
        request_id = OnlyOrderRequestId(f"{cluster_id}-product-{self._request_sequence:04d}-{side.value.lower()}")
        bar = context.primary_bar
        if not isinstance(bar, OnlyBar):
            raise TypeError("CN A-share Product order requires an OnlyBar")
        result = context.strategy.orders.submit(
            OnlyOrderRequest(
                request_id,
                self._instrument_id(),
                side,
                OnlyOrderType.LIMIT,
                quantity,
                account_id=account_id,
                offset=OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
                price=bar.close,
                tags=(PRODUCT_ID, tag),
            )
        )
        rejection = result.risk_rejection
        self._submission_results.append(
            {
                "request_id": str(request_id),
                "tag": tag,
                "side": side.value,
                "created": result.created,
                "submitted": result.submitted,
                "order_id": None if result.order_id is None else str(result.order_id),
                "error": result.error,
                "risk_rejection_code": None if rejection is None else rejection.code.value,
                "market_reason_code": None if rejection is None else rejection.details.get("market_reason_code"),
                "market_rule_code": None if rejection is None else rejection.details.get("market_rule_code"),
                "market_product_id": None if rejection is None else rejection.details.get("market_product_id"),
                "market_product_version": (
                    None if rejection is None else rejection.details.get("market_product_version")
                ),
                "market_reference_fingerprint": (
                    None if rejection is None else rejection.details.get("market_reference_fingerprint")
                ),
                "market_compiled_rule_fingerprint": (
                    None if rejection is None else rejection.details.get("market_compiled_rule_fingerprint")
                ),
            }
        )

    def _cancel(self, context: OnlyStrategyBarContext, order_id: OnlyOrderId, reason: str) -> None:
        result = context.strategy.orders.cancel(order_id, reason=reason)
        self._cancel_requested = True
        self._cancel_results.append(
            {
                "order_id": str(result.snapshot.order_id),
                "requested": result.requested,
                "cancelled": result.cancelled,
                "status": result.snapshot.status.value,
                "error": result.error,
            }
        )

    def _cluster_id(self) -> OnlyClusterId:
        if self.config.cluster_id is None:
            raise RuntimeError("CN A-share Product Cluster identity is unavailable")
        return self.config.cluster_id

    def _account_id(self) -> OnlyAccountId:
        if self.config.account_id is None:
            raise RuntimeError("CN A-share Product Account identity is unavailable")
        return self.config.account_id

    def _instrument_id(self) -> OnlyInstrumentId:
        if self.config.instrument_id is None:
            raise RuntimeError("CN A-share Product Instrument identity is unavailable")
        return self.config.instrument_id

    def _quantity(self) -> OnlyQuantity:
        if self.config.trade_quantity is None:
            raise RuntimeError("CN A-share Product quantity is unavailable")
        return self.config.trade_quantity

    def build_result_extension(self) -> Mapping[str, object]:
        return {
            "product_id": PRODUCT_ID,
            "product_contract_version": PRODUCT_CONTRACT_VERSION,
            "scenario": self.config.scenario.value,
            "bar_count": self._bar_count,
            "submission_results": list(self._submission_results),
            "cancel_results": list(self._cancel_results),
        }

    @property
    def checkpoint_schema_version(self) -> int | None:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability | None:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return {
            "bar_count": self._bar_count,
            "request_sequence": self._request_sequence,
            "entry_submitted": self._entry_submitted,
            "entry_trading_day": None if self._entry_trading_day is None else self._entry_trading_day.isoformat(),
            "same_day_sell_attempted": self._same_day_sell_attempted,
            "exit_submitted": self._exit_submitted,
            "cancel_requested": self._cancel_requested,
            "submission_results": list(self._submission_results),
            "cancel_results": list(self._cancel_results),
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("CN A-share Product Strategy checkpoint must be an object")
        self._bar_count = int(str(payload["bar_count"]))
        self._request_sequence = int(str(payload["request_sequence"]))
        self._entry_submitted = bool(payload["entry_submitted"])
        raw_day = payload["entry_trading_day"]
        self._entry_trading_day = None if raw_day is None else date.fromisoformat(str(raw_day))
        self._same_day_sell_attempted = bool(payload["same_day_sell_attempted"])
        self._exit_submitted = bool(payload["exit_submitted"])
        self._cancel_requested = bool(payload["cancel_requested"])
        self._submission_results = _checkpoint_rows(payload["submission_results"], "submission_results")
        self._cancel_results = _checkpoint_rows(payload["cancel_results"], "cancel_results")


def _checkpoint_rows(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"CN A-share Product Strategy checkpoint {label} must be an array")
    return [dict(cast(Mapping[str, object], item)) for item in value]


def _bar_payload(raw: Mapping[str, object]) -> dict[str, object]:
    timestamp = datetime.fromisoformat(str(raw["ts_event"]).replace("Z", "+00:00"))
    event = OnlyTimestamp.from_datetime(timestamp)
    return {
        "instrument_id": str(raw["instrument_id"]),
        "sequence": int(str(raw["sequence"])),
        "ts_event_ns": event.unix_nanos,
        "ts_init_ns": event.unix_nanos,
        "open": str(raw["open"]),
        "high": str(raw["high"]),
        "low": str(raw["low"]),
        "close": str(raw["close"]),
        "volume": str(raw["volume"]),
    }


def only_cn_a_share_product_config(
    *,
    instrument_id: str = "600000.XSHG",
    scenario: OnlyCnAshareProductScenario = OnlyCnAshareProductScenario.ROUND_TRIP,
    persistence_backend: str = "MEMORY",
    multi_fill: bool = False,
    simulation_submissions: tuple[Mapping[str, object], ...] = (),
) -> OnlyClusterRunConfig:
    """Build the frozen Product V1 config through the public config document."""

    fixture = only_load_cn_a_share_production_fixture()
    identities = _json_objects(fixture.manifest.get("instrument_identities"), "instrument_identities")
    identity = next((item for item in identities if item["instrument_id"] == instrument_id), None)
    if identity is None:
        raise ValueError(f"instrument is outside {PRODUCT_ID}: {instrument_id}")
    selected_bars = tuple(item for item in fixture.bars if item["instrument_id"] == instrument_id)
    if not selected_bars:
        raise ValueError(f"fixture has no Bars for {instrument_id}")

    baseline = OnlyClusterRunConfig.load(ROOT / "tests" / "fixtures" / "legacy_macd" / "cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["authorities"] = {"broker_fee_contracts": [only_cn_a_share_product_broker_fee_contract()]}
    payload["market"] = {
        "plugin_id": "onlyalpha-market-cn-ashare",
        "product_id": MARKET_PRODUCT_ID,
        "product_version": MARKET_PRODUCT_VERSION,
        "config": {"references": [dict(item) for item in fixture.references]},
    }
    payload["cluster"] = {
        "cluster_id": CLUSTER_ID,
        "account_id": ACCOUNT_ID,
        "enabled": True,
        "runtime_type": "BACKTEST",
        "risk_profile_id": "cn-equity-default",
    }
    payload["runtime"] = {
        "start_time": "2026-01-05T01:30:00Z",
        "end_time": "2026-01-06T01:39:00Z",
        "base_currency": "CNY",
        "extensions": {"replay": {"stop_on_data_error": True}},
        "persistence": {
            "backend": persistence_backend,
            "checkpoint": {"enabled": persistence_backend == "SQLITE", "retain_last": 4},
        },
    }
    payload["reference_data"] = {
        "calendars": [
            {
                "calendar_id": "CN_XSHG",
                "venue": "XSHG",
                "timezone": "Asia/Shanghai",
                "sessions": [
                    {
                        "name": "morning",
                        "opens_at": "09:30:00",
                        "closes_at": "11:30:00",
                        "session_type": "CONTINUOUS",
                    },
                    {
                        "name": "afternoon",
                        "opens_at": "13:00:00",
                        "closes_at": "15:00:00",
                        "session_type": "CONTINUOUS",
                    },
                ],
                "holidays": [],
            },
            {
                "calendar_id": "CN_XSHE",
                "venue": "XSHE",
                "timezone": "Asia/Shanghai",
                "sessions": [
                    {
                        "name": "morning",
                        "opens_at": "09:30:00",
                        "closes_at": "11:30:00",
                        "session_type": "CONTINUOUS",
                    },
                    {
                        "name": "afternoon",
                        "opens_at": "13:00:00",
                        "closes_at": "15:00:00",
                        "session_type": "CONTINUOUS",
                    },
                ],
                "holidays": [],
            },
        ],
        "instruments": [
            {
                "instrument_id": item["instrument_id"],
                "asset_class": "EQUITY",
                "timezone": "Asia/Shanghai",
                "trading_calendar_id": item["trading_calendar_id"],
                "price_precision": 2,
                "quantity_precision": 0,
                "price_increment": "0.01",
                "quantity_increment": "100",
                "lot_size": "100",
                "minimum_quantity": "100",
                "maximum_quantity": "100000000",
            }
            for item in identities
        ],
    }
    payload["universes"] = [
        {"universe_id": "cn-a-share-product-universe", "type": "STATIC", "instruments": [instrument_id]}
    ]
    payload["data_sources"] = [
        {
            "source_id": f"cn-a-share-product-{str(identity['venue']).lower()}",
            "plugin": "scenario-exact",
            "data_version": str(fixture.manifest["data_version"]),
            "batch_size": 16,
            "coverage": {"universe_ids": ["cn-a-share-product-universe"]},
            "extensions": {"bars": [_bar_payload(item) for item in selected_bars]},
        }
    ]
    payload["accounts"] = [
        {
            "account_id": ACCOUNT_ID,
            "gateway_id": "virtual-main",
            "initial_cash": {"value": "1000000.00", "currency": "CNY"},
            "broker_fee_contract": {
                "contract_id": BROKER_FEE_CONTRACT_ID,
                "contract_version": BROKER_FEE_CONTRACT_VERSION,
            },
            "fee_reconciliation_policy": {
                "policy_id": "STANDARD_FEE_RECONCILIATION",
                "policy_version": "1",
            },
        }
    ]
    broker_extensions: dict[str, object] = {
        "matching": {"type": "NEXT_BAR"},
        "slippage": {"type": "NONE"},
    }
    if multi_fill:
        cast(dict[str, object], broker_extensions["matching"])["partial_fill"] = {
            "mode": "SCHEDULE",
            "dispatch_mode": "ONE_PER_BAR",
            "steps": [
                {"bar_offset": 1, "quantity": "300"},
                {"bar_offset": 2, "quantity": "400"},
                {"bar_offset": 3, "quantity": "300"},
            ],
        }
    if simulation_submissions:
        broker_extensions["simulation"] = {"submissions": [dict(item) for item in simulation_submissions]}
    payload["brokers"] = [{"gateway_id": "virtual-main", "plugin": "virtual", "extensions": broker_extensions}]
    payload["strategy"] = {
        "class_path": ("tests.conformance.cn_a_share_production.support:OnlyCnAshareProductStrategy"),
        "config_path": ("tests.conformance.cn_a_share_production.support:OnlyCnAshareProductStrategyConfig"),
        "extensions": {
            "strategy_id": "cn-a-share-product-strategy",
            "instrument_id": instrument_id,
            "trade_quantity": "1000",
            "scenario": scenario.value,
        },
    }
    payload["factors"] = [
        {
            "factor_id": "product-bar-clock",
            "factor_type": "TIME_SERIES",
            "type_id": "onlyalpha.test.factor.macd",
            "semantic_version": "1",
            "class_path": "onlyalpha_test_plugin.macd_plugin:OnlyTestMacdFactor",
            "config_path": "onlyalpha_test_plugin.macd_plugin:OnlyTestMacdFactorConfig",
            "required": True,
            "subscriptions": {
                "instrument_bars": [
                    {
                        "instrument_id": instrument_id,
                        "bar_specification": {
                            "step": 1,
                            "aggregation": "TIME",
                            "price_type": "LAST",
                            "source": "EXTERNAL",
                        },
                        "role": "PRIMARY",
                    }
                ]
            },
            "indicators": [
                {
                    "indicator_id": "product-bar-clock-indicator",
                    "type": "MACD",
                    "parameters": {
                        "fast_period": 2,
                        "slow_period": 3,
                        "signal_period": 2,
                        "warmup_bars": 3,
                    },
                }
            ],
        }
    ]
    payload["output"] = {"formats": ["JSON"]}
    return OnlyClusterRunConfig.from_mapping(payload, source_path=DATASET / "product_config.json")


def only_run_cn_a_share_product(
    output_root: Path,
    *,
    engine_id: str,
    config: OnlyClusterRunConfig | None = None,
    services: OnlyEngineServices | None = None,
) -> OnlyCnAshareProductRun:
    """Run one Product scenario exclusively through the formal Engine entry."""

    selected = config or only_cn_a_share_product_config()
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId(engine_id), output_root),
        services=services,
    )
    engine.add_cluster(selected)
    engine_result = engine.run()
    if len(engine_result.runtime_results) != 1:
        raise AssertionError("CN A-share Product run must assemble exactly one Runtime")
    runtime_result = engine_result.runtime_results[0]
    if not isinstance(runtime_result, OnlyBacktestResult):
        raise TypeError("CN A-share Product Runtime did not return OnlyBacktestResult")
    return OnlyCnAshareProductRun(engine, engine_result, runtime_result, selected)


def only_cn_a_share_product_transactions(
    run: OnlyCnAshareProductRun,
) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
    """Read the canonical durable history through the Runtime query port."""

    runtime = run.engine.runtime_sessions[0].runtime
    return runtime.execution_transaction_query.records(runtime.config.runtime_id)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
