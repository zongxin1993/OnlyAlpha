"""Materialize existing verified Product values for the admitted native executable."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from onlyalpha.backtest.model import OnlyBacktestRun
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.strategy.revision import OnlyStrategyRevision


def only_build_native_backtest_plan(
    run: OnlyBacktestRun,
    *,
    config: OnlyClusterRunConfig,
    strategy: OnlyStrategyRevision,
    inputs: dict[str, Any],
    generation: str,
    native_artifact: str,
    worker_artifact: str,
    python: Path,
) -> dict[str, Any]:
    """No admission is granted here; the caller retains the owning verified readers."""
    spec = run.specification
    policy = spec.order_policy
    if policy is None or len(strategy.universe.instruments) != 1:
        raise ValueError("BACKTEST_NATIVE_SHAPE_UNSUPPORTED")
    if str(strategy.strategy_fingerprint) != spec.strategy_fingerprint:
        raise ValueError("BACKTEST_NATIVE_STRATEGY_MISMATCH")
    market = config.normalized_payload["market"]
    if market != {
        "plugin_id": "onlyalpha-plugin-generic-t0-cash",
        "product_id": "GENERIC_T0_CASH",
        "product_version": "1",
        "config": {},
    }:
        raise ValueError("BACKTEST_NATIVE_MARKET_UNSUPPORTED")
    recipe = strategy.market_input_contract.construction_requirement.recipe
    if recipe is None or recipe.kind.value != "PROVIDER_NATIVE":
        raise ValueError("BACKTEST_NATIVE_RECIPE_UNSUPPORTED")
    instruments = config.reference_data.instruments
    if len(instruments) != 1 or instruments[0].instrument_id != strategy.universe.instruments[0]:
        raise ValueError("BACKTEST_NATIVE_INSTRUMENT_MISMATCH")
    instrument = instruments[0]
    currency = instrument.settlement_currency
    if currency.code != spec.base_currency or currency.precision != 2 or instrument.contract_multiplier.value != 1:
        raise ValueError("BACKTEST_NATIVE_CURRENCY_UNSUPPORTED")
    if (
        len(inputs["sources"]) != 1
        or inputs["sources"][0]["snapshot"] != run.admission_resolution.base_dataset_snapshot_fingerprint
        or inputs["sources"][0]["dataset_binding"] != spec.dataset_binding_fingerprint
        or len(inputs["records"]) != inputs["sources"][0]["rows"]
        or len(inputs["records"]) > 4096
    ):
        raise ValueError("BACKTEST_NATIVE_INPUT_CLOSURE")
    if instrument.trading_calendar_id is None or config.runtime.start_time is None:
        raise ValueError("BACKTEST_NATIVE_REFERENCE_DATA_INCOMPLETE")
    calendar = config.reference_data.calendar_by_id[instrument.trading_calendar_id]
    scope = f"backtest-{run.run_id.value}"
    cluster = scope
    initial_cash = format(OnlyMoney(Decimal(spec.initial_capital), currency).amount, f".{currency.precision}f")
    configuration = {
        "schema_version": 1,
        "engine": f"{scope}-engine",
        "runtime": f"{scope}-runtime",
        "account": "backtest-account",
        "gateway": "virtual-main",
        "generation": generation,
        "runtime_kind": "BACKTEST",
        "currency": currency.to_dict(),
        "initial_cash": initial_cash,
        "capitals": {cluster: initial_cash},
        "profiles": {
            cluster: {
                "schema_version": 1,
                "revision": spec.strategy_fingerprint,
                "instruments": [str(instrument.instrument_id)],
                "rules": [],
            }
        },
        "instruments": [
            {
                "schema_version": 1,
                "id": str(instrument.instrument_id),
                "price_precision": instrument.price_precision,
                "quantity_precision": instrument.quantity_precision,
                "multiplier": format(instrument.contract_multiplier.value, "f"),
            }
        ],
    }
    requests = []
    for slot in range(policy.round_trips):
        for side, offset, price in (
            (OnlyOrderSide.BUY, OnlyOffset.OPEN, policy.entry_limit),
            (OnlyOrderSide.SELL, OnlyOffset.CLOSE, policy.exit_limit),
        ):
            requests.append(
                OnlyOrderRequest(
                    request_id=OnlyOrderRequestId(f"BACKTEST-{run.specification_fingerprint}-{slot}-{side.value}"),
                    instrument_id=instrument.instrument_id,
                    side=side,
                    order_type=OnlyOrderType.LIMIT,
                    quantity=OnlyQuantity(Decimal(policy.quantity), instrument.quantity_precision),
                    offset=offset,
                    price=OnlyPrice(Decimal(price), instrument.price_precision),
                ).to_dict()
            )
    trading = {
        "schema_version": 1,
        "execution": configuration,
        "instrument": instrument.to_dict(),
        "maximum_fill_quantity": policy.maximum_fill_quantity,
        "requests": requests,
    }
    value = {
        "schema_version": 1,
        "work_id": run.run_id.value,
        "native_artifact": native_artifact,
        "generation": generation,
        "worker_artifact": worker_artifact,
        "python": str(python),
        "configuration": configuration,
        "strategy": strategy.to_dict(),
        "inputs": inputs,
        "node_identities": [node.fingerprint for node in strategy.decision_graph.ordered_nodes],
        "source": inputs["sources"][0]["source"],
        "cluster": cluster,
        "calendar": calendar.to_dict(),
        "instrument_id": str(instrument.instrument_id),
        "trading": trading,
        "initial_ns": str(OnlyTimestamp.from_datetime(config.runtime.start_time).unix_nanos),
    }
    canonical: dict[str, Any] = json.loads(only_canonical_json(value))
    return canonical


def only_native_backtest_plan_fingerprint(plan: Mapping[str, object]) -> str:
    # The Generation verifies executable bytes; installation location is not trading identity.
    semantic = dict(plan)
    semantic.pop("python")
    return only_canonical_fingerprint(semantic)
