from datetime import date
from decimal import Decimal

import pytest
from onlyalpha_calculation_worker.backtest_external import dispatch

from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.value import OnlyMultiplier, OnlyPrice, OnlyQuantity
from tests.support.virtual_broker import ACCOUNT, CNY, INSTRUMENT, bar, order


def configuration():
    instrument = OnlyEquity(
        instrument_id=INSTRUMENT,
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=CNY,
        settlement_currency=CNY,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
    )
    from datetime import time

    from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
    from onlyalpha.domain.enums import OnlySessionType
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
    from onlyalpha.domain.time import OnlyTimeZone

    calendar = OnlyTradingCalendar(
        OnlyCalendarId("calendar"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("all", time(0), time(0), OnlySessionType.REGULAR),),
    )
    return {
        "calendar": calendar.to_dict(),
        "schema_version": 1,
        "execution": {
            "engine": "engine",
            "runtime": "runtime",
            "account": str(ACCOUNT),
            "gateway": "gateway",
            "generation": "a" * 64,
            "runtime_kind": "BACKTEST",
            "currency": CNY.to_dict(),
            "initial_cash": "100000.00",
        },
        "instrument": instrument.to_dict(),
        "maximum_fill_quantity": "50",
        "requests": [],
    }


def call(op, state=None, payload=None):
    from onlyalpha.domain.market import OnlyBar
    from onlyalpha.domain.time import OnlyTimestamp

    now = (
        1767576600000000000
        if not payload or "bar" not in payload
        else OnlyTimestamp.from_datetime(OnlyBar.from_dict(payload["bar"]).ts_event).unix_nanos
    )
    return dispatch(
        {
            "schema_version": 1,
            "configuration": configuration(),
            "checkpoint": state,
            "operation": op,
            "payload": payload or {},
            "now": now,
        }
    )


def test_actual_virtual_gateway_partial_fills_and_checkpoint_reconstruction():
    first = call("INIT")
    request = order(1).to_dict()
    request["account_id"] = ACCOUNT.to_dict()
    request["order_id"] = {"schema_version": 1, "value": "order-1"}
    request["submitted_at"] = {"schema_version": 1, "unix_nanos": 1767576600000000000}
    accepted = call("SUBMIT", first["checkpoint"], {"request": request})
    assert any(row["kind"] == "ACCEPT" for row in accepted["updates"])
    record = bar(date(2026, 1, 5), 1).to_dict()
    first_fill = call("BAR", accepted["checkpoint"], {"bar": record})
    fill = next(row["update"]["fill"] for row in first_fill["updates"] if row["kind"] == "FILL")
    assert fill["quantity"]["value"] == "50"
    assert len(first_fill["open_orders"]) == 1
    record = bar(date(2026, 1, 5), 2).to_dict()
    second_fill = call("BAR", first_fill["checkpoint"], {"bar": record})
    assert not second_fill["open_orders"]
    assert second_fill["pending"] == 0
    assert first_fill["checkpoint"]["trade_sequence"] == 1
    assert second_fill["checkpoint"]["trade_sequence"] == 2
    damaged = dict(second_fill["checkpoint"])
    damaged["fill_plans"] = {}
    with pytest.raises((KeyError, ValueError)):
        call("VALIDATE", damaged)


def test_external_bridge_refuses_live_and_unknown_operations():
    request = {
        "schema_version": 1,
        "configuration": configuration(),
        "checkpoint": None,
        "operation": "INIT",
        "payload": {},
        "now": 0,
    }
    request["configuration"]["execution"]["runtime_kind"] = "LIVE"
    with pytest.raises(ValueError, match="BACKTEST"):
        dispatch(request)
    with pytest.raises(ValueError):
        call("FORCE_SUBMIT")


def test_replay_wire_operation_and_loaded_plugin_provenance_are_explicit():
    from onlyalpha_calculation_worker.artifact import manifest
    from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

    request = wire.CalculationRequest(replay=wire.BacktestExternal(request_json=b"{}"))
    assert request.WhichOneof("operation") == "replay"
    paths = {resource.relative_path for resource in manifest().resources}
    assert "broker-virtual/gateway.py" in paths
    assert "generic-t0/compiler.py" in paths


def test_python_plugin_clock_never_truncates_submicrosecond_input():
    request = {
        "schema_version": 1,
        "configuration": configuration(),
        "checkpoint": None,
        "operation": "INIT",
        "payload": {},
        "now": 1,
    }
    with pytest.raises(ValueError, match="TIME_PRECISION"):
        dispatch(request)


@pytest.mark.parametrize("field", ["maximum", "request"])
def test_fill_history_quantities_are_bounded_before_fraction_materialization(monkeypatch, field):
    import json
    from pathlib import Path

    import onlyalpha_calculation_worker.backtest_external as external

    config = configuration()
    record = json.loads((Path(__file__).resolve().parents[3] / "test-data/execution/domain-inputs.json").read_text())[
        "request"
    ]
    record["instrument_id"] = config["instrument"]["instrument_id"]
    config["requests"] = [record]
    if field == "maximum":
        config["maximum_fill_quantity"] = "1E+1000000000"
    else:
        record["quantity"]["value"] = "1E+1000000000"

    def forbidden_fraction(value):
        raise AssertionError("unbounded quantity reached Fraction")

    monkeypatch.setattr(external, "Fraction", forbidden_fraction)
    with pytest.raises(ValueError, match="DECIMAL_INVALID"):
        external.dispatch(
            {
                "schema_version": 1,
                "configuration": config,
                "checkpoint": None,
                "operation": "INIT",
                "payload": {},
                "now": 0,
            }
        )
