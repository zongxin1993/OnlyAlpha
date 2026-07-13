from examples.domain_conformance.fixtures.instruments import build_instruments
from examples.domain_conformance.fixtures.market_data import build_bar, build_quote_tick, build_trade_tick


def test_core_scenario_objects_round_trip_without_float() -> None:
    for instrument in build_instruments().values():
        payload = instrument.to_json()
        assert ".0" not in payload or '"' in payload
        assert type(instrument).from_json(payload) == instrument
    for value in (build_bar(), build_quote_tick(), build_trade_tick()):
        assert type(value).from_json(value.to_json()) == value
