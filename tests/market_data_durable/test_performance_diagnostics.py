from __future__ import annotations

import json
import logging

import pytest

from onlyalpha.market_data.durable import performance


def test_nested_phase_accounting_does_not_double_count(caplog, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter((0, 10_000_000, 20_000_000, 50_000_000, 80_000_000, 100_000_000))
    monkeypatch.setattr(performance, "perf_counter_ns", lambda: next(ticks))
    with caplog.at_level(logging.INFO):
        with performance.only_market_data_performance("COMMAND") as measurement:
            measurement.bind(acquisition_id="acquisition:exact", scope_fingerprint="scope:exact")
            with performance.only_market_data_phase("recovery"):
                with performance.only_market_data_phase("batch_store"):
                    pass
    [record] = [item for item in caplog.records if item.msg == "market_data_performance %s"]
    data = json.loads(record.args[0])
    assert data["total_ms"] == 100
    assert data["accounted_ms"] == 70
    assert data["residual_ms"] == 30
    assert data["residual_ratio"] == 0.3
    assert data["phases"]["recovery"] == {"calls": 1, "inclusive_ms": 70, "exclusive_ms": 40}
    assert data["phases"]["batch_store"] == {"calls": 1, "inclusive_ms": 30, "exclusive_ms": 30}
    assert data["correlation"]["acquisition_id"] == "acquisition:exact"
    assert data["correlation"]["scope_fingerprint"] == "scope:exact"


def test_failed_operation_emits_incomplete_measurement_and_preserves_error(caplog) -> None:
    error = RuntimeError("secret=must-not-be-logged")
    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError) as caught:
            with performance.only_market_data_performance("QUERY"):
                with performance.only_market_data_phase("fact_read"):
                    raise error
    assert caught.value is error
    [record] = [item for item in caplog.records if item.msg == "market_data_performance %s"]
    data = json.loads(record.args[0])
    assert data["outcome"] == "ERROR"
    assert data["error_type"] == "RuntimeError"
    assert "must-not-be-logged" not in record.getMessage()
    assert data["correlation"]["acquisition_id"] is None
    assert data["phases"]["fact_read"]["calls"] == 1
    assert data["total_ms"] >= data["accounted_ms"] >= 0


def test_phase_outside_request_is_noop_and_request_context_does_not_leak(caplog) -> None:
    with caplog.at_level(logging.INFO):
        with performance.only_market_data_phase("not_in_request"):
            pass
        with performance.only_market_data_performance("COMMAND") as first:
            first.bind(acquisition_id="first")
        with performance.only_market_data_performance("COMMAND"):
            pass
    records = [item for item in caplog.records if item.msg == "market_data_performance %s"]
    assert len(records) == 2
    first, second = (json.loads(record.args[0]) for record in records)
    assert first["correlation"]["acquisition_id"] == "first"
    assert second["correlation"]["acquisition_id"] is None
    assert first["phases"] == second["phases"] == {}


def test_diagnostic_logging_failure_never_changes_operation_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_logging(*_args, **_kwargs) -> None:
        raise OSError("diagnostic transport unavailable")

    monkeypatch.setattr(performance._LOGGER, "info", fail_logging)
    with performance.only_market_data_performance("COMMAND"):
        pass
    error = RuntimeError("original outcome")
    with pytest.raises(RuntimeError) as caught:
        with performance.only_market_data_performance("QUERY"):
            raise error
    assert caught.value is error
    assert performance.only_current_market_data_performance() is None


def test_adapter_and_application_share_one_request_measurement(caplog) -> None:
    with caplog.at_level(logging.INFO):
        with performance.only_market_data_performance("QUERY") as adapter:
            with performance.only_market_data_performance("QUERY") as application:
                assert application is adapter
                application.bind(scope_fingerprint="exact-query")
                with performance.only_market_data_phase("fact_read"):
                    pass
            with performance.only_market_data_phase("serialization_projection"):
                pass
    records = [item for item in caplog.records if item.msg == "market_data_performance %s"]
    assert len(records) == 1
    data = json.loads(records[0].args[0])
    assert data["correlation"]["scope_fingerprint"] == "exact-query"
    assert set(data["phases"]) == {"fact_read", "serialization_projection"}
    assert data["residual_ms"] <= max(1000, data["total_ms"] * 0.05)
