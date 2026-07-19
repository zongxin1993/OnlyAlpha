from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from onlyalpha.scenario import (
    OnlyMarketScenarioParser,
    OnlyMarketScenarioPlanner,
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
