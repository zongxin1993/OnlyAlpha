from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.scenario import (
    OnlyMarketScenarioParser,
    OnlyMarketScenarioPlanner,
    OnlyMarketScenarioRunner,
    OnlyMarketScenarioRunRequest,
    OnlyScenarioAssertionEngine,
    OnlyScenarioAssertionStatus,
    OnlyScenarioError,
    OnlyScenarioErrorCode,
    OnlyScenarioFactType,
    only_scenario_fingerprint,
)


def scenario_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "scenario": {"id": "GENERIC_T0_BASIC", "version": "1.0", "description": "T0 cash"},
        "runtime": {
            "mode": "BACKTEST",
            "start_time": "2026-01-05T01:30:00Z",
            "end_time": "2026-01-05T02:00:00Z",
            "base_currency": "CNY",
        },
        "market": {"profile": "GENERIC_T0_CASH"},
        "reference": {
            "calendars": [
                {
                    "calendar_id": "GENERIC",
                    "venue": "XSHG",
                    "timezone": "UTC",
                    "sessions": [
                        {
                            "name": "continuous",
                            "opens_at": "00:00:00",
                            "closes_at": "23:59:00",
                            "session_type": "CONTINUOUS",
                        }
                    ],
                    "holidays": [],
                }
            ],
            "instruments": [
                {
                    "instrument_id": "TEST.XSHG",
                    "asset_class": "EQUITY",
                    "timezone": "UTC",
                    "trading_calendar_id": "GENERIC",
                    "price_precision": 2,
                    "quantity_precision": 2,
                    "price_increment": "0.01",
                    "quantity_increment": "0.01",
                    "lot_size": "0.01",
                }
            ],
        },
        "data": {
            "bars": [
                {
                    "instrument_id": "TEST.XSHG",
                    "ts_event": "2026-01-05T01:31:00Z",
                    "ts_init": "2026-01-05T01:31:00Z",
                    "sequence": 1,
                    "open": "10.00",
                    "high": "10.10",
                    "low": "9.90",
                    "close": "10.05",
                    "volume": "100.00",
                }
            ]
        },
        "actions": [
            {
                "action_id": "BUY_1",
                "trigger": {"type": "ON_BAR_SEQUENCE", "sequence": 1},
                "command": {
                    "type": "SUBMIT_ORDER",
                    "instrument_id": "TEST.XSHG",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "quantity": "0.25",
                    "position_effect": "AUTO",
                },
            }
        ],
        "expectations": [
            {
                "assertion_id": "FILLED",
                "fact": "ORDER",
                "selector": {"action_id": "BUY_1"},
                "field": "status",
                "operator": "EQUALS",
                "expected": "FILLED",
            }
        ],
    }


def test_parser_reuses_product_reference_and_preserves_decimal() -> None:
    scenario = OnlyMarketScenarioParser().parse(scenario_payload())
    assert scenario.actions[0].command.quantity.value == Decimal("0.25")
    assert scenario.reference_data.instruments[0].quantity_precision == 2
    assert only_scenario_fingerprint(scenario) == only_scenario_fingerprint(scenario)


def test_parser_rejects_unknown_fields_and_unquoted_decimal() -> None:
    unknown = scenario_payload()
    unknown["typo"] = True
    with pytest.raises(OnlyScenarioError) as caught:
        OnlyMarketScenarioParser().parse(unknown)
    assert caught.value.code is OnlyScenarioErrorCode.SCENARIO_FIELD_UNKNOWN

    decimal = deepcopy(scenario_payload())
    decimal["actions"][0]["command"]["quantity"] = 0.25  # type: ignore[index]
    with pytest.raises(OnlyScenarioError) as caught:
        OnlyMarketScenarioParser().parse(decimal)
    assert caught.value.code is OnlyScenarioErrorCode.SCENARIO_DECIMAL_INVALID


def test_assertion_engine_only_compares_supplied_standard_facts() -> None:
    scenario = OnlyMarketScenarioParser().parse(scenario_payload())
    summary = OnlyScenarioAssertionEngine().evaluate(
        scenario.expectations,
        {OnlyScenarioFactType.ORDER: ({"action_id": "BUY_1", "status": "FILLED"},)},
    )
    assert summary.passed
    assert summary.results[0].status is OnlyScenarioAssertionStatus.PASSED


def test_scenario_runner_traverses_engine_and_is_deterministic(tmp_path: Path) -> None:
    payload = scenario_payload()
    second = deepcopy(payload["data"]["bars"][0])  # type: ignore[index]
    second.update({"ts_event": "2026-01-05T01:32:00Z", "ts_init": "2026-01-05T01:32:00Z", "sequence": 2})
    payload["data"]["bars"].append(second)  # type: ignore[index]
    scenario = OnlyMarketScenarioParser().parse(payload)

    first = OnlyMarketScenarioRunner().run(OnlyMarketScenarioRunRequest(scenario, tmp_path / "first"))
    second_run = OnlyMarketScenarioRunner().run(OnlyMarketScenarioRunRequest(scenario, tmp_path / "second"))

    assert first.status == second_run.status == "PASSED"
    assert first.result_fingerprint == second_run.result_fingerprint
    assert first.facts[OnlyScenarioFactType.ORDER][0]["status"] == "FILLED"
    assert first.facts[OnlyScenarioFactType.PROFILE_TIMELINE]
    assert first.facts[OnlyScenarioFactType.COMPILED_RULE]
    assert (first.artifact_path / "manifest.json").is_file()  # type: ignore[operator]


@pytest.mark.parametrize(
    ("open_side", "close_side", "position_side"),
    (("BUY", "SELL", "LONG"), ("SELL", "BUY", "SHORT")),
)
def test_generic_futures_committed_execution_vertical_slice(
    tmp_path: Path,
    open_side: str,
    close_side: str,
    position_side: str,
) -> None:
    payload = scenario_payload()
    payload["scenario"] = {
        "id": f"GENERIC_FUTURES_{position_side}",
        "version": "1.0",
        "description": f"Generic futures {position_side}",
    }
    payload["market"] = {"profile": "GENERIC_MARGIN_FUTURES"}
    instrument = payload["reference"]["instruments"][0]  # type: ignore[index]
    instrument.update(  # type: ignore[union-attr]
        {
            "asset_class": "FUTURES",
            "underlying": "BASE.XSHG",
            "expiration_time": "2026-12-31T08:00:00Z",
            "last_trade_time": "2026-12-30T08:00:00Z",
            "quantity_precision": 2,
            "quantity_increment": "1",
            "lot_size": "1",
            "contract_multiplier": "300",
        }
    )
    bars = payload["data"]["bars"]  # type: ignore[index]
    for sequence in range(2, 18):
        bar = deepcopy(bars[0])  # type: ignore[index]
        bar.update(
            {
                "ts_event": f"2026-01-05T01:{30 + sequence:02d}:00Z",
                "ts_init": f"2026-01-05T01:{30 + sequence:02d}:00Z",
                "sequence": sequence,
            }
        )
        bars.append(bar)  # type: ignore[union-attr]
    actions = [
        {
            "action_id": "OPEN",
            "trigger": {"type": "ON_BAR_SEQUENCE", "sequence": 1},
            "command": {
                "type": "SUBMIT_ORDER",
                "instrument_id": "TEST.XSHG",
                "side": open_side,
                "order_type": "MARKET",
                "quantity": "1",
                "position_effect": "OPEN",
            },
        },
    ]
    actions.append(
        {
            "action_id": "CLOSE",
            "trigger": {"type": "ON_BAR_SEQUENCE", "sequence": 5},
            "command": {
                "type": "SUBMIT_ORDER",
                "instrument_id": "TEST.XSHG",
                "side": close_side,
                "order_type": "MARKET",
                "quantity": "1",
                "position_effect": "CLOSE_TODAY",
            },
        }
    )
    payload["actions"] = actions
    payload["expectations"] = []
    scenario = OnlyMarketScenarioParser().parse(payload)

    result = OnlyMarketScenarioRunner().run(OnlyMarketScenarioRunRequest(scenario, tmp_path / position_side))

    assert result.status == "PASSED", (
        result.diagnostics,
        result.facts[OnlyScenarioFactType.ACTION],
        result.facts[OnlyScenarioFactType.ORDER],
        result.facts[OnlyScenarioFactType.EXECUTION],
    )
    expected_count = 2
    assert len(result.facts[OnlyScenarioFactType.ACTION]) == expected_count
    assert all(item["status"] == "EXECUTED" for item in result.facts[OnlyScenarioFactType.ACTION])
    executions = result.facts[OnlyScenarioFactType.EXECUTION]
    assert len(executions) == expected_count, [
        result.facts[OnlyScenarioFactType.ACTION],
        [
            {
                key: item.get(key)
                for key in (
                    "position_side",
                    "total_quantity",
                    "settled_quantity",
                    "unsettled_quantity",
                    "available_quantity",
                    "position_mode",
                )
            }
            for item in result.facts[OnlyScenarioFactType.POSITION]
        ],
        result.facts[OnlyScenarioFactType.DIAGNOSTIC],
        [
            (item.get("status"), item.get("rejection_code"), item.get("rejection_message"))
            for item in result.facts[OnlyScenarioFactType.ORDER]
        ],
    ]
    assert {item["position_side"] for item in executions} == {position_side}
    expected_effects = ["OPEN", "CLOSE_TODAY"]
    assert [item["position_effect"] for item in executions] == expected_effects
    assert all(item["contract_multiplier"] == Decimal("300") for item in executions)
    assert all(
        item["turnover"] == item["price"] * item["quantity"] * item["contract_multiplier"] for item in executions
    )
    expected_margin = ["OCCUPY", "RELEASE"]
    assert [item["margin_action"] for item in executions] == expected_margin


@pytest.mark.parametrize("mode", ["PAPER", "LIVE", "SHADOW"])
def test_runtime_modes_share_commands_and_fail_capability_explicitly(mode: str) -> None:
    backtest = OnlyMarketScenarioParser().parse(scenario_payload())
    payload = scenario_payload()
    payload["runtime"]["mode"] = mode  # type: ignore[index]
    other = OnlyMarketScenarioParser().parse(payload)
    backtest_plan = OnlyMarketScenarioPlanner().plan(backtest)
    other_plan = OnlyMarketScenarioPlanner().plan(other)
    assert backtest_plan.executable
    assert not other_plan.executable
    assert backtest_plan.commands == other_plan.commands
    assert other_plan.issues[0].code is OnlyScenarioErrorCode.SCENARIO_RUNTIME_MODE_UNSUPPORTED
