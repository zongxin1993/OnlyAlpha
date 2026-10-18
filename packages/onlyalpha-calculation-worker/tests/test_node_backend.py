from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from onlyalpha_calculation_worker.contracts import digest, encode
from onlyalpha_calculation_worker.node_backend import NodeBackend


def resolution(type_id="onlyalpha.indicator.sma", period=3):
    return {
        "schema_version": 1,
        "op": "RESOLVE",
        "reference": {"kind": "INDICATOR", "type_id": type_id, "semantic_version": "1"},
        "parameters": {"period": {"type": "INTEGER", "value": period}},
        "input_bindings": {"value": {"node_fingerprint": None, "output_name": "value", "source": "bar.close"}},
    }


def create(backend, request=None):
    request = request or resolution()
    d = backend.dispatch(request)
    bar = next(
        json.loads(line)["record"]
        for line in (Path(__file__).resolve().parents[3] / "test-data/domain/fact-records-v1.jsonl")
        .read_text()
        .splitlines()
        if json.loads(line)["id"] == "bar"
    )
    bt = bar["bar_type"]
    context = digest(
        encode({"schema_version": 1, "bar_type": bt, "source_fingerprint": "c" * 64, "strategy_fingerprint": "d" * 64})
    )
    b = {
        "schema_version": 1,
        "digests": [
            "a" * 64,
            "b" * 64,
            d["definition_fingerprint"],
            d["native_definition"],
            d["implementation"],
            context,
        ],
        "scope": "test",
    }
    cp = backend.dispatch(
        {
            "schema_version": 1,
            "op": "CREATE",
            "binding": b,
            "resolution": request,
            "bar_type": bt,
            "source": "c" * 64,
            "strategy_fingerprint": "d" * 64,
        }
    )
    return b, bar, cp


def update(backend, b, bar, i):
    from datetime import datetime, timedelta

    row = copy.deepcopy(bar)
    for f in ("bar_start", "bar_end", "ts_event", "ts_init"):
        row[f] = (datetime.fromisoformat(row[f]) + timedelta(minutes=i - 1)).isoformat()
    for f in ("open", "high", "low", "close"):
        row[f]["value"] = str(i)
    from onlyalpha.domain.market import OnlyBar

    row = OnlyBar.from_dict(row).to_dict()
    inputs = {"value": {"type": "DECIMAL", "value": str(i)}}
    input_digest = digest(encode({"schema_version": 1, "binding": b, "bar": row, "inputs": inputs}))
    return backend.dispatch(
        {
            "schema_version": 1,
            "op": "UPDATE",
            "scope": b["scope"],
            "revision": i - 1,
            "bar": row,
            "inputs": inputs,
            "input_digest": input_digest,
        }
    )["receipt"]


def test_resolver_uses_exact_registry_and_declared_state():
    backend = NodeBackend("a" * 64, "b" * 64)
    d = backend.dispatch(resolution())
    assert d["definition"]["schema_version"] == 3
    assert d["native_definition"] != d["definition_fingerprint"]
    assert d["state_capability"] == "CHECKPOINTABLE"
    assert d["definition"]["warmup"]["minimum_observations"] == 3
    for change in ("version", "backend", "parameter", "binding"):
        r = resolution()
        if change == "version":
            r["reference"]["semantic_version"] = "999"
        elif change == "backend":
            r["backend"] = "RESEARCH"
        elif change == "parameter":
            r["parameters"]["period"] = {"type": "BOOLEAN", "value": True}
        else:
            r["input_bindings"]["value"]["source"] = "bar.open"
        with pytest.raises((ValueError, TypeError)):
            backend.dispatch(r)


def test_registered_sma_atomic_rejection_and_fresh_continuation():
    a = NodeBackend("a" * 64, "b" * 64)
    binding, bar, initial = create(a)
    for i in range(1, 4):
        result = update(a, binding, bar, i)
        assert result["ready"] == (i >= 3)
    assert result["outputs"] == {"value": {"type": "DECIMAL", "value": "2"}}
    cp = a.capture("test")
    with pytest.raises((ValueError, TypeError)):
        update(a, binding, bar, 3)
    assert a.capture("test") == cp
    b = NodeBackend("a" * 64, "b" * 64)
    create(b)
    b.restore("test", cp)
    for i in range(4, 7):
        assert update(a, binding, bar, i) == update(b, binding, bar, i)
    assert a.capture("test") == b.capture("test")
    with pytest.raises(ValueError):
        b.restore("test", initial)


def test_checkpoint_binding_rejects_before_committing():
    a = NodeBackend("a" * 64, "b" * 64)
    b, bar, initial = create(a)
    update(a, b, bar, 1)
    cp = a.capture("test")
    for field in ("cursor", "binding", "definition_fingerprint", "state_capability", "plugin_state"):
        target = NodeBackend("a" * 64, "b" * 64)
        create(target)
        v = copy.deepcopy(cp)
        if field == "cursor":
            v[field]["samples"] = 0
        elif field == "binding":
            v[field]["digests"][0] = "e" * 64
        elif field == "definition_fingerprint":
            v[field] = "e" * 64
        elif field == "state_capability":
            v[field] = "STATELESS"
        else:
            v[field] = {}
        with pytest.raises((ValueError, KeyError, TypeError)):
            target.restore("test", v)
        assert target.capture("test") == initial


def test_native_state_cannot_be_spliced_under_a_newer_receipt():
    a = NodeBackend("a" * 64, "b" * 64)
    binding, bar, initial = create(a)
    update(a, binding, bar, 1)
    old = a.capture("test")
    update(a, binding, bar, 2)
    cp = a.capture("test")
    cp["plugin_state"] = old["plugin_state"]
    target = NodeBackend("a" * 64, "b" * 64)
    create(target)
    with pytest.raises(ValueError):
        target.restore("test", cp)
    assert target.capture("test") == initial


def test_restore_schema_requires_plain_integer():
    backend = NodeBackend("a" * 64, "b" * 64)
    _, _, initial = create(backend)
    damaged = copy.deepcopy(initial)
    damaged["schema_version"] = True
    with pytest.raises(ValueError):
        backend.restore("test", damaged)
    assert backend.capture("test") == initial


def test_old_full_operator_window_is_rejected_under_new_receipt():
    request = resolution("onlyalpha.operator.rolling_mean", 3)
    backend = NodeBackend("a" * 64, "b" * 64)
    binding, bar, initial = create(backend, request)
    for i in range(1, 4):
        update(backend, binding, bar, i)
    old = backend.capture("test")
    update(backend, binding, bar, 4)
    current = backend.capture("test")
    current["plugin_state"] = old["plugin_state"]
    target = NodeBackend("a" * 64, "b" * 64)
    create(target, request)
    with pytest.raises(ValueError):
        target.restore("test", current)
    assert target.capture("test") == initial
