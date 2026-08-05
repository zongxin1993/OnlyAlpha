import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.scenario import OnlyMarketScenarioParser

SCENARIO = Path("tests/fixtures/scenarios/cn_a_share_t1.yaml")
REFERENCES = Path("tests/fixtures/reference/cn_a_share_v1/references.json")


def _scenario_payload() -> dict[str, object]:
    value = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("index", range(5))
def test_scenario_schema_resolves_every_frozen_ashare_reference_case(index: int) -> None:
    payload = _scenario_payload()
    record = deepcopy(json.loads(REFERENCES.read_text(encoding="utf-8"))[index])
    record["effective_from"] = "2026-01-05"
    record["effective_to"] = "2026-01-06"
    instrument_id = record["instrument_id"]
    venue = instrument_id.rsplit(".", 1)[1]
    calendar_id = f"CN_{venue}"
    payload["reference"]["calendars"][0]["calendar_id"] = calendar_id
    payload["reference"]["calendars"][0]["venue"] = venue
    payload["reference"]["instruments"][0]["instrument_id"] = instrument_id
    payload["reference"]["instruments"][0]["trading_calendar_id"] = calendar_id
    payload["reference"]["ashare_instruments"] = [record]
    for bar in payload["data"]["bars"]:
        bar["instrument_id"] = instrument_id
    payload["actions"][0]["command"]["instrument_id"] = instrument_id
    payload["expectations"][2]["selector"]["instrument_id"] = instrument_id
    scenario = OnlyMarketScenarioParser().parse(payload)
    resolved = scenario.reference_data.ashare_registry.resolve(
        scenario.reference_data.instruments[0].instrument_id,
        OnlyTradingDay(date(2026, 1, 5)),
    ).require_snapshot()
    assert resolved.board.value == record["board"]
    assert resolved.st_status is record["st_status"]
    assert resolved.suspended is record["suspended"]


def test_scenario_missing_and_conflicting_reference_fail_closed() -> None:
    missing = _scenario_payload()
    missing["reference"]["ashare_instruments"] = []
    with pytest.raises(ValueError, match="REFERENCE_NOT_FOUND"):
        OnlyMarketScenarioParser().parse(missing)

    conflict = _scenario_payload()
    duplicate = deepcopy(conflict["reference"]["ashare_instruments"][0])
    duplicate["previous_close"] = "9.99"
    conflict["reference"]["ashare_instruments"].append(duplicate)
    with pytest.raises(ValueError, match="REFERENCE_RUNTIME_CONFLICT|REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        OnlyMarketScenarioParser().parse(conflict)
