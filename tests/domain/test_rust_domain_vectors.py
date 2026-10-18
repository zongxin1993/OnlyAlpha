"""Independent shared Domain vectors; neither language generates expected results."""

import json
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from onlyalpha.domain import identifiers, numeric, value
from onlyalpha.domain.errors import OnlySerializationError

ROOT = Path(__file__).resolve().parents[2]
ROWS = [json.loads(line) for line in (ROOT / "test-data/domain/value-records-v1.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_independent_value_record_vectors(row: dict[str, object]) -> None:
    classes = {
        name: getattr(value, name)
        for name in (
            "OnlyCurrency",
            "OnlyPrice",
            "OnlyQuantity",
            "OnlyMoney",
            "OnlyRate",
            "OnlyPercentage",
            "OnlyMultiplier",
        )
    }
    classes.update({name: getattr(identifiers, name) for name in ("OnlySymbol", "OnlyVenueId", "OnlyInstrumentId")})
    cls = classes[row["type"]]
    if "error" in row:
        with pytest.raises(OnlySerializationError):
            cls.from_dict(row["input"])
    else:
        assert cls.from_dict(row["input"]).to_json() == row["expected"]


def test_independent_numeric_policy_vectors_under_hostile_context() -> None:
    operations = {
        name: getattr(numeric, "only_" + name)
        for name in ("add", "subtract", "multiply", "divide", "quantize", "remainder")
    }
    for line in (ROOT / "test-data/domain/numeric-v1.tsv").read_text().splitlines():
        if line.startswith("#"):
            continue
        operation, left, right, expected = line.split("\t")
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            assert str(operations[operation](Decimal(left), Decimal(right))) == expected, line


def test_independent_business_rounding_vectors() -> None:
    for line in (ROOT / "test-data/domain/rounding-v1.tsv").read_text().splitlines():
        if line.startswith("#"):
            continue
        operation, rounding, value, quantum, expected = line.split("\t")
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            result = getattr(numeric, "only_" + operation)(Decimal(value), Decimal(quantum), rounding=rounding)
            assert str(result) == expected, line


def test_independent_fee_fingerprint_preimages() -> None:
    from onlyalpha.domain.fee import only_fee_fingerprint

    for line in (ROOT / "test-data/domain/fee-authority-v1.jsonl").read_text().splitlines():
        row = json.loads(line)
        assert only_fee_fingerprint(row["payload"]) == row["sha256"]
        assert (
            json.dumps(row["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            == row["canonical_json"]
        )


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/instrument-records-v2.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_independent_instrument_records(row) -> None:
    from onlyalpha.domain.instrument import OnlyInstrument

    if row.get("error"):
        with pytest.raises(OnlySerializationError):
            OnlyInstrument.from_dict(row["record"])
    else:
        assert OnlyInstrument.from_dict(row["record"]).to_dict() == row["record"]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_independent_market_and_execution_records(row) -> None:
    from onlyalpha.domain import execution, market

    classes = {
        cls.__name__: cls
        for cls in (
            execution.OnlyOrderSnapshot,
            execution.OnlyOrderFill,
            market.OnlyBar,
            market.OnlyQuoteTick,
            market.OnlyReferencePriceFact,
        )
    }
    if row.get("error"):
        with pytest.raises(OnlySerializationError):
            classes[row["type"]].from_dict(row["record"])
    else:
        assert classes[row["type"]].from_dict(row["record"]).to_dict() == row["record"]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/temporal-records-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_independent_temporal_records_reject_implicit_formats_and_precision_loss(row) -> None:
    from onlyalpha.domain.calendar import OnlyTradingSession
    from onlyalpha.domain.market import OnlyReferencePriceFact
    from onlyalpha.domain.time import OnlyTradingDay

    def decode():
        if row["kind"] == "utc":
            reference = next(
                json.loads(line)["record"]
                for line in (ROOT / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()
                if json.loads(line)["id"] == "reference"
            )
            reference["ts_event"] = row["input"]
            reference["ts_init"] = "9999-12-31T23:59:59.999999Z"
            return OnlyReferencePriceFact.from_dict(reference).ts_event.isoformat().replace("+00:00", "Z")
        if row["kind"] == "date":
            return OnlyTradingDay.from_dict({"schema_version": 1, "value": row["input"]}).value.isoformat()
        return OnlyTradingSession.from_dict(
            {
                "schema_version": 1,
                "name": "day",
                "opens_at": row["input"],
                "closes_at": "17:00:00",
                "session_type": "REGULAR",
                "belongs_to_trading_day_offset": 0,
                "allows_orders": True,
                "allows_market_data": True,
            }
        ).opens_at.isoformat()

    if row.get("error"):
        with pytest.raises(OnlySerializationError):
            decode()
    else:
        assert decode() == row["expected"]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/timezone-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_independent_timezone_conversion_vectors(row) -> None:
    from datetime import datetime, time

    from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
    from onlyalpha.domain.errors import OnlyValidationError
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
    from onlyalpha.domain.time import OnlyTimeZone

    calendar = OnlyTradingCalendar(
        OnlyCalendarId("test"),
        OnlyVenueId("test"),
        OnlyTimeZone(row["zone"]),
        (OnlyTradingSession("all", time(0), time(0)),),
        weekend_days=(),
    )

    def convert():
        value = datetime.fromisoformat(row["input"])
        if row["op"] == "to_utc":
            return calendar.to_utc(value, fold=row["fold"]).isoformat().replace("+00:00", "Z")
        value = calendar.to_local(value)
        return [value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond]

    if row.get("error"):
        with pytest.raises(OnlyValidationError):
            convert()
    else:
        assert convert() == row["expected"]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/calendar-boundaries-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_calendar_boundary_direction_vectors(row) -> None:
    from datetime import datetime, time

    from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
    from onlyalpha.domain.errors import OnlyValidationError
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
    from onlyalpha.domain.time import OnlyTimeZone

    calendar = OnlyTradingCalendar(
        OnlyCalendarId("test"),
        OnlyVenueId("test"),
        OnlyTimeZone("America/New_York"),
        tuple(
            OnlyTradingSession(f"day-{index}", time.fromisoformat(wall), time(4))
            for index, wall in enumerate(row.get("walls", [row.get("wall")]))
        ),
        weekend_days=(),
    )

    def query():
        return getattr(calendar, row["method"])(datetime.fromisoformat(row["query"])).isoformat().replace("+00:00", "Z")

    if row.get("error"):
        with pytest.raises(OnlyValidationError):
            query()
    else:
        assert query() == row["expected"]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/bar-identity-v3.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_canonical_bar_identity_vectors(row) -> None:
    from onlyalpha.domain.market import OnlyBarSemantic, OnlyValueBarFormation, OnlyVolumeBarFormation

    constructor = OnlyVolumeBarFormation if row["kind"] == "VOLUME" else OnlyValueBarFormation
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        semantic = OnlyBarSemantic(constructor(Decimal(row["input"])))
        assert semantic.to_dict() == row["record"]
        assert semantic.fingerprint == row["fingerprint"]
        assert OnlyBarSemantic.from_dict(row["record"]) == semantic
    noncanonical = semantic.to_dict()
    noncanonical["formation"][row["field"]] = row["input"]
    from onlyalpha.domain.errors import OnlyValidationError

    if noncanonical == row["record"]:
        assert OnlyBarSemantic.from_dict(noncanonical) == semantic
    else:
        with pytest.raises(OnlyValidationError):
            OnlyBarSemantic.from_dict(noncanonical)
    old = semantic.to_dict()
    old["schema_version"] = 2
    from onlyalpha.domain.errors import OnlyValidationError

    with pytest.raises(OnlyValidationError):
        OnlyBarSemantic.from_dict(old)
    old_formation = semantic.to_dict()
    old_formation["formation"]["schema_version"] = 1
    with pytest.raises(OnlySerializationError):
        OnlyBarSemantic.from_dict(old_formation)
