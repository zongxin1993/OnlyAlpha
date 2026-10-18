import json
from copy import deepcopy
from datetime import timedelta
from decimal import getcontext
from pathlib import Path

import pytest
from onlyalpha_calculation_worker.backend import Backend, resolve
from onlyalpha_calculation_worker.contracts import digest, encode, input_context

from onlyalpha.domain.market import OnlyBar

ROOT = Path(__file__).resolve().parents[3]


def bars(values=(1, 2, 3, 4, 5)):
    row = next(
        json.loads(s)["record"]
        for s in (ROOT / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()
        if json.loads(s).get("id") == "bar"
    )
    base = OnlyBar.from_dict(row)
    result = []
    for i, value in enumerate(values):
        record = deepcopy(row)
        for field in ("open", "high", "low", "close"):
            record[field]["value"] = f"{value:.2f}"
        for field in ("bar_start", "bar_end", "ts_event", "ts_init"):
            record[field] = (getattr(base, field) + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        result.append(encode(record))
    return result


def instance(scope="runtime/cluster/local", period=3, price_field="CLOSE"):
    backend = Backend("a" * 64, "b" * 64)
    resolved = resolve({"period": period, "price_field": price_field})
    bar_type = json.loads(bars()[0])["bar_type"]
    binding = {
        "schema_version": 1,
        "digests": [
            "a" * 64,
            "b" * 64,
            resolved["definition_fingerprint"],
            resolved["native_definition"],
            resolved["implementation"],
            input_context(bar_type, "c" * 64),
        ],
        "scope": scope,
    }
    backend.create(binding, resolved["definition"], bar_type, {"period": period, "price_field": price_field}, "c" * 64)
    return backend, binding


def test_registered_sma_exact_vectors_atomic_rejection_and_restore():
    backend, binding = instance()
    raw = bars()
    result = backend.update(binding["scope"], 0, raw[:2], digest(b"".join(raw[:2])))
    assert [p["value"] for p in result["points"]] == ["1.000000000000", "1.500000000000"]
    assert [p["ready"] for p in result["points"]] == [False, False]
    checkpoint = backend.capture(binding["scope"], 1)
    for rejected in ([raw[1]], [raw[2], raw[1]], [raw[2], b"{}"]):
        with pytest.raises(ValueError):
            backend.update(binding["scope"], 1, rejected, digest(b"".join(rejected)))
        assert backend.capture(binding["scope"], 1) == checkpoint
    remaining = backend.update(binding["scope"], 1, raw[2:], digest(b"".join(raw[2:])))
    assert [p["value"] for p in remaining["points"]] == ["2.000000000000", "3.000000000000", "4.000000000000"]
    assert all(p["ready"] for p in remaining["points"])
    fresh, _ = instance()
    damaged = deepcopy(checkpoint)
    damaged["plugin_state"]["samples"] = True
    with pytest.raises(ValueError):
        fresh.restore(binding["scope"], 0, encode(damaged), digest(encode(checkpoint)))
    fresh.restore(binding["scope"], 0, encode(checkpoint), digest(encode(checkpoint)))
    assert fresh.update(binding["scope"], 1, raw[2:], digest(b"".join(raw[2:]))) == remaining
    with pytest.raises(ValueError):
        fresh.restore(binding["scope"], 2, encode(checkpoint), digest(encode(checkpoint)))


def test_context_zero_scope_reset_close_and_resource_bounds():
    backend, binding = instance()
    original = getcontext().prec
    try:
        getcontext().prec = 3
        raw = bars((0, 0, 0))
        result = backend.update(binding["scope"], 0, raw, digest(b"".join(raw)))
        assert result["points"][-1]["value"] == "0E-12"
        assert result["points"][-1]["ready"] is True
        assert getcontext().prec == 3
    finally:
        getcontext().prec = original
    reset = backend.reset(binding["scope"], 1)
    assert reset["samples"] == 0 and reset["revision"] == 2
    backend.update(binding["scope"], 2, raw, digest(b"".join(raw)))
    backend.close(binding["scope"], 3)
    with pytest.raises(ValueError):
        backend.capture(binding["scope"], 3)
    for bad in ({"period": True}, {"period": 4097}, {"period": 0}, {"price_field": "HIGH"}, {"unknown": 1}):
        with pytest.raises(ValueError):
            resolve(bad)


def test_forged_structurally_invalid_checkpoint_is_atomic_and_scope_isolated():
    backend, bound = instance()
    raw = bars()[:2]
    backend.update(bound["scope"], 0, raw, digest(b"".join(raw)))
    checkpoint = backend.capture(bound["scope"], 1)
    fresh, _ = instance()
    initial = fresh.capture(bound["scope"], 0)
    for key, value in (
        ("samples", True),
        ("values", ["NaN", "2"]),
        ("snapshot_type", "OnlyRsiSnapshot"),
        ("last_event_ns", True),
        ("previous_close", None),
    ):
        damaged = deepcopy(checkpoint)
        damaged["plugin_state"][key] = value
        raw_checkpoint = encode(damaged)
        with pytest.raises(ValueError):
            fresh.restore(bound["scope"], 0, raw_checkpoint, digest(raw_checkpoint))
        assert fresh.capture(bound["scope"], 0) == initial
    second = deepcopy(bound)
    second["scope"] = "another/cluster/local"
    resolved = resolve({"period": 3})
    fresh.create(second, resolved["definition"], json.loads(raw[0])["bar_type"], {"period": 3}, "c" * 64)
    fresh.update(second["scope"], 0, raw, digest(b"".join(raw)))
    assert fresh.capture(bound["scope"], 0) == initial
    for index in range(14):
        third = deepcopy(bound)
        third["scope"] = f"scope/{index}"
        fresh.create(third, resolved["definition"], json.loads(raw[0])["bar_type"], {"period": 3}, "c" * 64)
    third["scope"] = "overflow"
    with pytest.raises(ValueError):
        fresh.create(third, resolved["definition"], json.loads(raw[0])["bar_type"], {"period": 3}, "c" * 64)


def test_caller_cannot_mutate_owner_binding_through_cursor():
    backend, bound = instance()
    cursor = backend.reset(bound["scope"], 0)
    cursor["binding"]["digests"][0] = "0" * 64
    assert backend.capture(bound["scope"], 1)["cursor"]["binding"] == bound


def test_maximum_period_window_remains_checkpointable_after_wraparound():
    backend, bound = instance(period=4096)
    records = bars(range(1, 4099))
    revision = 0
    for start in range(0, 4097, 256):
        batch = records[start : min(start + 256, 4097)]
        result = backend.update(bound["scope"], revision, batch, digest(b"".join(batch)))
        revision += 1
    assert result["points"][-1]["value"] == "2049.500000000000"
    assert result["points"][-1]["ready"] is True
    checkpoint = backend.capture(bound["scope"], revision)
    assert len(checkpoint["plugin_state"]["values"]) == 4097
    fresh, _ = instance(period=4096)
    raw = encode(checkpoint)
    fresh.restore(bound["scope"], 0, raw, digest(raw))
    last = records[4097:]
    assert fresh.update(bound["scope"], revision, last, digest(b"".join(last))) == backend.update(
        bound["scope"], revision, last, digest(b"".join(last))
    )


def test_volume_batch_cannot_commit_unrestorable_previous_close():
    backend, bound = instance(price_field="VOLUME")
    initial = backend.capture(bound["scope"], 0)
    raw = bars((1, 2))
    huge = json.loads(raw[1])
    for key in ("open", "high", "low", "close"):
        huge[key] = {"schema_version": 1, "value": "1E+5000", "precision": 0}
    raw[1] = encode(huge)
    # Still a valid Domain fact; the worker must reject it before committing
    # a plugin checkpoint outside its explicitly bounded restore envelope.
    OnlyBar.from_dict(huge)
    with pytest.raises(ValueError):
        backend.update(bound["scope"], 0, raw, digest(b"".join(raw)))
    assert backend.capture(bound["scope"], 0) == initial


def test_checkpoint_epoch_zero_timestamp_cannot_be_a_boolean():
    backend, bound = instance()
    row = json.loads(bars((1,))[0])
    row.update(
        bar_start="1969-12-31T23:59:00Z",
        bar_end="1970-01-01T00:00:00Z",
        ts_event="1970-01-01T00:00:00Z",
        ts_init="1970-01-01T00:00:01Z",
    )
    raw = [encode(row)]
    backend.update(bound["scope"], 0, raw, digest(b"".join(raw)))
    checkpoint = backend.capture(bound["scope"], 1)
    assert checkpoint["plugin_state"]["snapshot"]["ts_event_ns"] == 0
    original = encode(checkpoint)
    checkpoint["plugin_state"]["snapshot"]["ts_event_ns"] = False
    fresh, _ = instance()
    raw_checkpoint = encode(checkpoint)
    with pytest.raises(ValueError):
        fresh.restore(bound["scope"], 0, raw_checkpoint, digest(raw_checkpoint))

    fresh.restore(bound["scope"], 0, original, digest(original))
    assert fresh.capture(bound["scope"], 1) == json.loads(original)
