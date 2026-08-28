from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from onlyalpha_gateway_protocol import (
    OnlyGatewayApplicationError,
    OnlyGatewayClient,
    OnlyGatewayConnectionState,
    OnlyGatewayResyncRequired,
    OnlyGatewayTransportError,
)
from onlyalpha_gateway_protocol.v1 import common_pb2, error_pb2

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tests/fixtures/remote_gateway/server.py"


@dataclass(frozen=True, slots=True)
class _GatewayProcess:
    process: subprocess.Popen[str]
    target: str
    gateway_instance_id: str


@contextmanager
def _gateway(*arguments: str) -> Iterator[_GatewayProcess]:
    process = subprocess.Popen(
        [sys.executable, str(SERVER), *arguments],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    readiness_line = process.stdout.readline()
    if not readiness_line:
        assert process.stderr is not None
        diagnostic = process.stderr.read()
        process.wait(timeout=5)
        raise AssertionError(f"test Gateway exited before readiness: {diagnostic}")
    readiness = json.loads(readiness_line)
    gateway = _GatewayProcess(
        process=process,
        target=f"127.0.0.1:{readiness['port']}",
        gateway_instance_id=readiness["gateway_instance_id"],
    )
    try:
        yield gateway
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def _connect(gateway: _GatewayProcess, *capabilities: int) -> OnlyGatewayClient:
    client = OnlyGatewayClient(gateway.target)
    client.connect(required_capabilities=capabilities, correlation_id="handshake-attempt")
    return client


@pytest.mark.integration
def test_handshake_proves_identity_instance_protocol_and_capabilities() -> None:
    with _gateway() as gateway, _connect(gateway, common_pb2.TEST_UNARY, common_pb2.TEST_STREAM) as client:
        handshake = client.handshake
        assert handshake.gateway_id == "test-gateway"
        assert handshake.gateway_instance_id == gateway.gateway_instance_id
        assert handshake.protocol_major == 1
        assert handshake.contract_sha256 == "5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e"
        assert handshake.capabilities == frozenset((common_pb2.TEST_UNARY, common_pb2.TEST_STREAM))
        assert client.state is OnlyGatewayConnectionState.READY


@pytest.mark.integration
def test_protocol_major_mismatch_fails_closed_before_ready() -> None:
    with _gateway() as gateway:
        client = OnlyGatewayClient(gateway.target)
        with pytest.raises(OnlyGatewayApplicationError) as captured:
            client.connect(required_capabilities=(), correlation_id="mismatch", protocol_major=2)
        assert captured.value.code == error_pb2.PROTOCOL_MISMATCH
        assert client.state is OnlyGatewayConnectionState.DISCONNECTED


@pytest.mark.integration
def test_missing_required_capability_fails_closed_without_side_effect() -> None:
    with _gateway("--capability", "TEST_STREAM") as gateway:
        client = OnlyGatewayClient(gateway.target)
        with pytest.raises(OnlyGatewayApplicationError) as captured:
            client.connect(required_capabilities=(common_pb2.TEST_UNARY,), correlation_id="capability")
        assert captured.value.code == error_pb2.UNSUPPORTED_CAPABILITY
        assert client.state is OnlyGatewayConnectionState.DISCONNECTED


@pytest.mark.integration
def test_first_mutation_executes_once_and_same_identity_replays() -> None:
    with _gateway() as gateway, _connect(gateway, common_pb2.TEST_UNARY) as client:
        first = client.apply_test_mutation(command_id="command-a", correlation_id="attempt-1", payload="intent")
        replay = client.apply_test_mutation(command_id="command-a", correlation_id="attempt-2", payload="intent")
        assert first.execution_count == replay.execution_count == 1
        assert first.outcome_id == replay.outcome_id
        assert first.replayed is False
        assert replay.replayed is True


@pytest.mark.integration
def test_response_loss_retry_same_command_converges_without_second_execution() -> None:
    with (
        _gateway("--response-loss-command-id", "lost-command") as gateway,
        _connect(gateway, common_pb2.TEST_UNARY) as client,
    ):
        with pytest.raises(OnlyGatewayTransportError) as captured:
            client.apply_test_mutation(
                command_id="lost-command", correlation_id="attempt-before-loss", payload="intent"
            )
        assert captured.value.outcome_unknown is True
        assert client.state is OnlyGatewayConnectionState.DISCONNECTED
        client.connect(required_capabilities=(common_pb2.TEST_UNARY,), correlation_id="re-handshake")
        replay = client.apply_test_mutation(
            command_id="lost-command", correlation_id="attempt-after-loss", payload="intent"
        )
        assert replay.execution_count == 1
        assert replay.replayed is True


@pytest.mark.integration
def test_same_command_id_with_different_canonical_intent_conflicts() -> None:
    with _gateway() as gateway, _connect(gateway, common_pb2.TEST_UNARY) as client:
        first = client.apply_test_mutation(command_id="command-a", correlation_id="attempt-1", payload="intent-a")
        with pytest.raises(OnlyGatewayApplicationError) as captured:
            client.apply_test_mutation(command_id="command-a", correlation_id="attempt-2", payload="intent-b")
        assert first.execution_count == 1
        assert captured.value.code == error_pb2.COMMAND_CONFLICT


@pytest.mark.integration
def test_stream_uses_sequence_authority_and_detects_duplicate() -> None:
    with _gateway("--events", "1,2,2,3") as gateway, _connect(gateway, common_pb2.TEST_STREAM) as client:
        batch = client.watch_test_events(stream_id="test-stream", resume_after=0)
        assert tuple(event.sequence for event in batch.events) == (1, 2, 3)
        assert batch.duplicate_sequences == (2,)
        assert client.state is OnlyGatewayConnectionState.READY


@pytest.mark.integration
def test_stream_gap_fails_explicitly_without_wall_clock_ordering() -> None:
    with _gateway("--events", "1,2,4") as gateway, _connect(gateway, common_pb2.TEST_STREAM) as client:
        with pytest.raises(OnlyGatewayResyncRequired, match="expected 3, received 4"):
            client.watch_test_events(stream_id="test-stream", resume_after=0)
        assert client.state is OnlyGatewayConnectionState.READY


@pytest.mark.integration
def test_reconnect_rehandshakes_and_resumes_exactly_at_next_sequence() -> None:
    with _gateway("--events", "1,2,3,4") as gateway:
        first = _connect(gateway, common_pb2.TEST_STREAM)
        try:
            prefix = first.watch_test_events(stream_id="test-stream", resume_after=0)
            assert tuple(event.sequence for event in prefix.events) == (1, 2, 3, 4)
        finally:
            first.close()
        with _connect(gateway, common_pb2.TEST_STREAM) as resumed:
            suffix = resumed.watch_test_events(stream_id="test-stream", resume_after=2)
            assert tuple(event.sequence for event in suffix.events) == (3, 4)
            assert resumed.handshake.gateway_instance_id == gateway.gateway_instance_id


@pytest.mark.integration
def test_bounded_history_returns_explicit_resync_required() -> None:
    with (
        _gateway("--events", "1,2,3,4,5", "--history-limit", "3") as gateway,
        _connect(gateway, common_pb2.TEST_STREAM) as client,
    ):
        with pytest.raises(OnlyGatewayResyncRequired, match="bounded stream history"):
            client.watch_test_events(stream_id="test-stream", resume_after=1)


@pytest.mark.integration
def test_non_resync_stream_application_error_preserves_gateway_error_taxonomy() -> None:
    with (
        _gateway("--stream-error", "INTERNAL_ERROR") as gateway,
        _connect(gateway, common_pb2.TEST_STREAM) as client,
    ):
        with pytest.raises(OnlyGatewayApplicationError, match="deterministic injected stream error") as captured:
            client.watch_test_events(stream_id="test-stream", resume_after=0)
        assert captured.value.code == error_pb2.INTERNAL_ERROR
        assert not isinstance(captured.value, OnlyGatewayResyncRequired)
        assert client.state is OnlyGatewayConnectionState.READY


@pytest.mark.integration
def test_gateway_restart_changes_instance_and_requires_new_handshake() -> None:
    with _gateway() as first_gateway:
        with _connect(first_gateway, common_pb2.TEST_STREAM) as client:
            first_instance = client.handshake.gateway_instance_id
    with _gateway() as second_gateway:
        with _connect(second_gateway, common_pb2.TEST_STREAM) as client:
            second_instance = client.handshake.gateway_instance_id
            assert second_instance == second_gateway.gateway_instance_id
    assert first_instance != second_instance
