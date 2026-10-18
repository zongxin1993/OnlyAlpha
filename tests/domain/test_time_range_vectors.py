"""Shared contracts map Python's existing paths to Rust Domain responsibilities."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from onlyalpha.core.errors import OnlyValidationError
from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges, only_missing_ranges
from onlyalpha.core.time import only_datetime_to_unix_ns, only_unix_ns_to_datetime_utc
from onlyalpha.domain.time import OnlyTimestamp

ROOT = Path(__file__).resolve().parents[2]
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def test_shared_exact_and_lossy_instant_conversion_vectors() -> None:
    for line in (ROOT / "test-data/domain/instant-conversion-v1.tsv").read_text().splitlines():
        if line.startswith("#"):
            continue
        name, nanos, exact, floored = line.split("\t")
        for truncate, expected in ((False, exact), (True, floored)):
            if expected == "ERROR":
                with pytest.raises(OnlyValidationError):
                    only_unix_ns_to_datetime_utc(int(nanos), allow_truncation=truncate)
            else:
                value = datetime.fromisoformat(expected)
                assert only_unix_ns_to_datetime_utc(int(nanos), allow_truncation=truncate) == value, name
                if not truncate:
                    assert only_datetime_to_unix_ns(value) == int(nanos), name
        if floored != "ERROR":
            assert OnlyTimestamp(int(nanos)).to_datetime() == datetime.fromisoformat(floored), name


def _range(value: list[int]) -> OnlyTimeRange:
    return OnlyTimeRange(EPOCH + timedelta(microseconds=value[0]), EPOCH + timedelta(microseconds=value[1]))


def _encode(values: tuple[OnlyTimeRange, ...]) -> list[list[int]]:
    return [
        [only_datetime_to_unix_ns(value.start) // 1000, only_datetime_to_unix_ns(value.end) // 1000] for value in values
    ]


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (ROOT / "test-data/domain/time-ranges-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_shared_half_open_range_operations(row: dict[str, Any]) -> None:
    actual: bool | list[list[int]]
    op = row["op"]
    if op == "create":
        with pytest.raises(ValueError):
            _range(row["range"])
        return
    inputs = tuple(_range(value) for value in row.get("ranges", []))
    if op == "merge":
        actual = _encode(only_merge_ranges(inputs))
    elif op == "missing":
        actual = _encode(only_missing_ranges(_range(row["range"]), inputs))
    elif op == "contains":
        actual = _range(row["range"]).contains(EPOCH + timedelta(microseconds=row["point"]))
    elif op == "overlaps":
        actual = _range(row["range"]).overlaps(_range(row["other"]))
    elif op == "intersection":
        intersection = _range(row["range"]).intersection(_range(row["other"]))
        actual = _encode(()) if intersection is None else _encode((intersection,))
    elif op == "subtract":
        actual = _encode(_range(row["range"]).subtract(_range(row["other"])))
    else:
        raise AssertionError("unknown operation")
    assert actual == row["expected"]
