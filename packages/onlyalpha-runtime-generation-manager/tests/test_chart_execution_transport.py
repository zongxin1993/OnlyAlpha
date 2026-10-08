"""Deterministic pipe fault injection; no real clock progression or sleeps."""

import os
from types import SimpleNamespace

import pytest
from onlyalpha_runtime_generation_manager import host_manager

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationProtocolMismatch,
    OnlyHistoricalGenerationWorkerUnavailable,
)

pytestmark = pytest.mark.contract


@pytest.fixture
def pipe_transport(tmp_path):
    incoming_read, incoming_write = os.pipe()
    outgoing_read, outgoing_write = os.pipe()
    stdin = os.fdopen(incoming_write, "w")
    stdout = os.fdopen(outgoing_read, "r")
    process = SimpleNamespace(stdin=stdin, stdout=stdout, poll=lambda: None)
    manager = host_manager.OnlyHistoricalGenerationHostManager(
        registry=object(),
        builder=object(),
        cache_root=tmp_path,
        startup_timeout_seconds=1,
    )
    try:
        yield manager, process, outgoing_write
    finally:
        stdin.close()
        stdout.close()
        os.close(incoming_read)
        os.close(outgoing_write)


@pytest.mark.parametrize("fault", ["half_line", "blocked_write", "no_response"])
def test_pipe_deadline_bounds_partial_lines_and_blocked_writes(pipe_transport, monkeypatch, fault):
    manager, process, outgoing_write = pipe_transport
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(host_manager.time, "monotonic", lambda: next(ticks))
    if fault == "half_line":
        os.write(outgoing_write, b'{"schema_version":')
    monkeypatch.setattr(
        host_manager.select,
        "select",
        lambda reads, writes, errors, timeout: (
            reads if fault == "half_line" else [],
            [] if fault == "blocked_write" else writes,
            [],
        ),
    )
    with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable, match="timeout"):
        manager._exchange_chart(process, {"fixture": "request"}, None)
    assert os.get_blocking(process.stdin.fileno()) is True
    assert os.get_blocking(process.stdout.fileno()) is True


def test_pipe_cancellation_during_transport_is_not_success(pipe_transport, monkeypatch):
    from threading import Event

    manager, process, _ = pipe_transport
    cancellation = Event()

    def cancelling(reads, writes, errors, timeout):
        cancellation.set()
        return [], [], []

    monkeypatch.setattr(host_manager.select, "select", cancelling)
    with pytest.raises(OnlyChartCalculationError, match="CHART_EXECUTION_CANCELLED"):
        manager._exchange_chart(process, {}, cancellation)


def test_dispatch_fences_cover_complete_write_not_numerical_wait(pipe_transport, monkeypatch):
    from contextlib import contextmanager

    manager, process, outgoing_write = pipe_transport
    state = {"held": False, "dispatched": False}

    @contextmanager
    def guard():
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    original_write = os.write

    def writing(fd, payload):
        assert state["held"] is True
        sent = original_write(fd, payload)
        state["dispatched"] = True
        original_write(outgoing_write, b"{}\n")
        return sent

    def select(reads, writes, errors, timeout):
        if state["dispatched"]:
            assert state["held"] is False, "numeric response wait must not hold lifecycle/Run fences"
            return reads, [], []
        return [], writes, []

    monkeypatch.setattr(host_manager.os, "write", writing)
    monkeypatch.setattr(host_manager.select, "select", select)
    assert manager._exchange_chart(process, {}, None, dispatch_guard=guard()) == {}
    assert state == {"held": False, "dispatched": True}


def test_pipe_closure_during_transport_preserves_typed_host_loss(pipe_transport, monkeypatch):
    manager, process, _ = pipe_transport

    def closed(reads, writes, errors, timeout):
        process.stdout.close()
        raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(host_manager.select, "select", closed)
    with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable, match="pipe closed"):
        manager._exchange_chart(process, {}, None)


@pytest.mark.parametrize("response", [b"x" * 17, b"[]\n", b"{oops}\n", b"{}\n{}\n", b"\xff\n"])
def test_pipe_malformed_or_oversized_response_is_not_projection(pipe_transport, monkeypatch, response):
    manager, process, outgoing_write = pipe_transport
    monkeypatch.setattr(host_manager, "ONLYALPHA_CHART_CALCULATION_EXECUTION_MAX_WIRE_BYTES", 16)
    os.write(outgoing_write, response)
    monkeypatch.setattr(host_manager.select, "select", lambda reads, writes, errors, timeout: (reads, writes, []))
    with pytest.raises(OnlyHistoricalGenerationProtocolMismatch):
        manager._exchange_chart(process, {}, None)
