"""Shared Engine-only harness for CN A-share Production Durable Backtest V1."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import (
    OnlyEngineId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngineConfig, OnlyEngineRunResult
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.runtime.backtest.result import OnlyBacktestResult
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.scenario.data_source import OnlyScenarioDataSourceFactory
from onlyalpha.transaction import OnlyCommittedRuntimeTransaction
from tests.runtime_runner import only_migrate_cluster_to_strategy

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
    payload["strategy"] = {"fingerprint": "0" * 64}
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
    action = {
        "type": "SUBMIT_ORDER",
        "instrument_id": instrument_id,
        "order_type": "LIMIT",
        "quantity": "1000",
        "tags": [PRODUCT_ID],
    }
    actions: list[dict[str, object]] = [
        {
            **action,
            "action_id": "PRODUCT_BUY_OPEN",
            "tag": "PRODUCT_BUY_OPEN",
            "sequence": 1,
            "side": "BUY",
            "price": "10.00",
            "offset": "OPEN",
            "result_metadata": {
                "product_id": PRODUCT_ID,
                "product_contract_version": PRODUCT_CONTRACT_VERSION,
                "scenario": scenario.value,
            },
        }
    ]
    if scenario is OnlyCnAshareProductScenario.ROUND_TRIP:
        actions.extend(
            (
                {
                    **action,
                    "action_id": "PRODUCT_SAME_DAY_SELL",
                    "tag": "PRODUCT_SAME_DAY_SELL",
                    "sequence": 3,
                    "side": "SELL",
                    "price": "10.00",
                    "offset": "CLOSE",
                },
                {
                    **action,
                    "action_id": "PRODUCT_SELL_CLOSE",
                    "tag": "PRODUCT_SELL_CLOSE",
                    "sequence": 9,
                    "side": "SELL",
                    "price": "10.20",
                    "offset": "CLOSE",
                },
            )
        )
    elif scenario in {
        OnlyCnAshareProductScenario.SELL_AFTER_SETTLEMENT,
        OnlyCnAshareProductScenario.SELL_PARTIAL_CANCEL,
    }:
        actions.append(
            {
                **action,
                "action_id": "PRODUCT_SELL_CLOSE",
                "tag": "PRODUCT_SELL_CLOSE",
                "sequence": 9,
                "side": "SELL",
                "price": "10.20",
                "offset": "CLOSE",
            }
        )
    if scenario is OnlyCnAshareProductScenario.BUY_PARTIAL_CANCEL:
        actions.append(
            {
                "action_id": "PRODUCT_BUY_PARTIAL_CANCEL",
                "sequence": 2,
                "type": "CANCEL_ORDER",
                "target_action_id": "PRODUCT_BUY_OPEN",
            }
        )
    elif scenario is OnlyCnAshareProductScenario.SELL_PARTIAL_CANCEL:
        actions.append(
            {
                "action_id": "PRODUCT_SELL_PARTIAL_CANCEL",
                "sequence": 10,
                "type": "CANCEL_ORDER",
                "target_action_id": "PRODUCT_SELL_CLOSE",
            }
        )
    payload["scenario_actions"] = actions
    payload["output"] = {"formats": ["JSON"]}
    return OnlyClusterRunConfig.from_mapping(payload, source_path=DATASET / "product_config.json")


def only_run_cn_a_share_product(
    output_root: Path,
    *,
    engine_id: str,
    config: OnlyClusterRunConfig | None = None,
    services: OnlyEngineServices | None = None,
) -> OnlyCnAshareProductRun:
    """Run one conformance scenario through the internal Engine composition boundary."""

    selected = only_migrate_cluster_to_strategy(config or only_cn_a_share_product_config(), output_root)
    selected_services = only_cn_a_share_conformance_services(services)
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId(engine_id), output_root),
        services=selected_services,
    )
    engine.add_cluster(selected)
    engine_result = engine.run()
    if len(engine_result.runtime_results) != 1:
        raise AssertionError(f"CN A-share Product run must assemble exactly one Runtime: {engine_result.failures}")
    runtime_result = engine_result.runtime_results[0]
    if not isinstance(runtime_result, OnlyBacktestResult):
        raise TypeError("CN A-share Product Runtime did not return OnlyBacktestResult")
    return OnlyCnAshareProductRun(engine, engine_result, runtime_result, selected)


def only_cn_a_share_conformance_services(services: OnlyEngineServices | None = None) -> OnlyEngineServices:
    """Register Scenario fixtures only in the CN A-share conformance composition root."""

    selected_services = services or only_default_engine_services()
    selected_services.assembler.components.data_sources.register(
        OnlyScenarioDataSourceFactory(),
        origin=OnlyPluginOrigin(OnlyPluginOriginType.BUILTIN, "onlyalpha-scenario-verification"),
    )
    return selected_services


def only_cn_a_share_product_transactions(
    run: OnlyCnAshareProductRun,
) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
    """Read the canonical durable history through the Runtime query port."""

    runtime = run.engine.runtime_sessions[0].runtime
    return runtime.execution_transaction_query.records(runtime.config.runtime_id)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
