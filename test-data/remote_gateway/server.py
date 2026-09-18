"""TEST ONLY provider-neutral Gateway subprocess for the K7 protocol foundation."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import uuid
from concurrent import futures
from dataclasses import dataclass
from importlib.resources import files

import grpc
from onlyalpha_gateway_protocol import PROTOCOL_MAJOR, canonical_test_mutation_fingerprint
from onlyalpha_gateway_protocol.v1 import (
    common_pb2,
    error_pb2,
    gateway_pb2,
    gateway_pb2_grpc,
    identity_pb2,
    stream_pb2,
    stream_pb2_grpc,
)


@dataclass(frozen=True, slots=True)
class _Receipt:
    fingerprint: str
    outcome_id: str


class _TestGateway(gateway_pb2_grpc.GatewayServiceServicer, stream_pb2_grpc.GatewayStreamServiceServicer):
    def __init__(
        self,
        *,
        gateway_id: str,
        capabilities: frozenset[int],
        events: tuple[int, ...],
        history_limit: int,
        response_loss_command_id: str | None,
        stream_error: int | None,
        omit_contract_identity: bool,
        omit_implementation_version: bool,
    ) -> None:
        self.gateway_id = gateway_id
        self.gateway_instance_id = str(uuid.uuid4())
        self.capabilities = capabilities
        self.events = events[-history_limit:]
        self.response_loss_command_id = response_loss_command_id
        self.stream_error = stream_error
        self._response_lost = False
        self._receipts: dict[str, _Receipt] = {}
        self._lock = threading.Lock()
        descriptor = files("onlyalpha_gateway_protocol.v1").joinpath("descriptor.pb").read_bytes()
        self.contract_sha256 = "" if omit_contract_identity else hashlib.sha256(descriptor).hexdigest()
        self.implementation_version = "" if omit_implementation_version else "K7_TEST_FIXTURE_V1"

    def Handshake(
        self,
        request: gateway_pb2.HandshakeRequest,
        context: grpc.ServicerContext,
    ) -> gateway_pb2.HandshakeResponse:
        del context
        error = error_pb2.GatewayError()
        required = frozenset(request.required_capabilities)
        if request.protocol_major != PROTOCOL_MAJOR:
            error = error_pb2.GatewayError(
                code=error_pb2.PROTOCOL_MISMATCH,
                message=f"supported protocol major is {PROTOCOL_MAJOR}",
            )
        elif not required <= self.capabilities:
            error = error_pb2.GatewayError(
                code=error_pb2.UNSUPPORTED_CAPABILITY,
                message="one or more required capabilities are unavailable",
            )
        return gateway_pb2.HandshakeResponse(
            identity=identity_pb2.GatewayIdentity(
                gateway_id=self.gateway_id,
                gateway_instance_id=self.gateway_instance_id,
            ),
            protocol_major=PROTOCOL_MAJOR,
            contract_sha256=self.contract_sha256,
            implementation_version=self.implementation_version,
            capabilities=sorted(self.capabilities),
            error=error,
        )

    def ApplyTestMutation(
        self,
        request: gateway_pb2.ApplyTestMutationRequest,
        context: grpc.ServicerContext,
    ) -> gateway_pb2.ApplyTestMutationResponse:
        identity = request.identity
        expected_fingerprint = canonical_test_mutation_fingerprint(request.payload)
        if (
            not identity.command_id
            or not identity.correlation_id
            or identity.command_fingerprint != expected_fingerprint
        ):
            return gateway_pb2.ApplyTestMutationResponse(
                error=error_pb2.GatewayError(
                    code=error_pb2.INVALID_REQUEST,
                    message="command identity or canonical fingerprint is invalid",
                )
            )
        with self._lock:
            receipt = self._receipts.get(identity.command_id)
            if receipt is not None and receipt.fingerprint != identity.command_fingerprint:
                return gateway_pb2.ApplyTestMutationResponse(
                    error=error_pb2.GatewayError(
                        code=error_pb2.COMMAND_CONFLICT,
                        message="command_id is already bound to a different canonical command",
                    )
                )
            replayed = receipt is not None
            if receipt is None:
                outcome_id = hashlib.sha256(
                    f"{identity.command_id}\x00{identity.command_fingerprint}".encode()
                ).hexdigest()
                receipt = _Receipt(identity.command_fingerprint, outcome_id)
                self._receipts[identity.command_id] = receipt
            should_lose_response = identity.command_id == self.response_loss_command_id and not self._response_lost
            if should_lose_response:
                self._response_lost = True
        if should_lose_response:
            context.abort(grpc.StatusCode.UNAVAILABLE, "deterministic test response loss after receipt commit")
        return gateway_pb2.ApplyTestMutationResponse(
            command_id=identity.command_id,
            outcome_id=receipt.outcome_id,
            execution_count=1,
            replayed=replayed,
        )

    def WatchTestEvents(
        self,
        request: stream_pb2.WatchTestEventsRequest,
        context: grpc.ServicerContext,
    ):
        del context
        if request.gateway_instance_id != self.gateway_instance_id:
            yield _resync("gateway instance changed; re-handshake is required")
            return
        if self.stream_error is not None:
            yield stream_pb2.TestStreamItem(
                error=error_pb2.GatewayError(code=self.stream_error, message="deterministic injected stream error")
            )
            return
        remaining = tuple(sequence for sequence in self.events if sequence > request.resume_after)
        if remaining and remaining[0] != request.resume_after + 1:
            yield _resync("bounded stream history cannot satisfy exact continuation")
            return
        for index, sequence in enumerate(remaining):
            yield stream_pb2.TestStreamItem(
                event=stream_pb2.TestEvent(
                    stream_id=request.stream_id,
                    gateway_instance_id=self.gateway_instance_id,
                    sequence=sequence,
                    event_id=f"{request.stream_id}:{sequence}:{index}",
                    observed_at_unix_nanos=sequence * 1_000_000_000,
                    payload=f"test-event-{sequence}",
                )
            )


def _resync(message: str) -> stream_pb2.TestStreamItem:
    return stream_pb2.TestStreamItem(error=error_pb2.GatewayError(code=error_pb2.RESYNC_REQUIRED, message=message))


def _capability(value: str) -> int:
    mapping = {"TEST_UNARY": common_pb2.TEST_UNARY, "TEST_STREAM": common_pb2.TEST_STREAM}
    try:
        return mapping[value]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(f"unknown test capability: {value}") from exc


def _events(value: str) -> tuple[int, ...]:
    if not value:
        return ()
    try:
        result = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("events must be comma-separated integers") from exc
    if any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("event sequences must be positive")
    return result


def _stream_error(value: str) -> int:
    try:
        code = error_pb2.GatewayErrorCode.Value(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"unknown Gateway stream error: {value}") from exc
    if code == error_pb2.GATEWAY_ERROR_CODE_UNSPECIFIED:
        raise argparse.ArgumentTypeError("stream error must be a specified Gateway error code")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the TEST ONLY K7 remote Gateway fixture")
    parser.add_argument("--gateway-id", default="test-gateway")
    parser.add_argument("--capability", action="append", type=_capability, default=[])
    parser.add_argument("--events", type=_events, default=(1, 2, 3, 4))
    parser.add_argument("--history-limit", type=int, default=16)
    parser.add_argument("--response-loss-command-id")
    parser.add_argument("--stream-error", type=_stream_error)
    parser.add_argument("--omit-contract-identity", action="store_true")
    parser.add_argument("--omit-implementation-version", action="store_true")
    args = parser.parse_args()
    if args.history_limit <= 0:
        parser.error("--history-limit must be positive")
    gateway = _TestGateway(
        gateway_id=args.gateway_id,
        capabilities=frozenset(args.capability or (common_pb2.TEST_UNARY, common_pb2.TEST_STREAM)),
        events=args.events,
        history_limit=args.history_limit,
        response_loss_command_id=args.response_loss_command_id,
        stream_error=args.stream_error,
        omit_contract_identity=args.omit_contract_identity,
        omit_implementation_version=args.omit_implementation_version,
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    gateway_pb2_grpc.add_GatewayServiceServicer_to_server(gateway, server)
    stream_pb2_grpc.add_GatewayStreamServiceServicer_to_server(gateway, server)
    port = server.add_insecure_port("127.0.0.1:0")
    if port == 0:
        raise RuntimeError("test Gateway could not bind localhost")
    server.start()
    print(
        json.dumps(
            {
                "gateway_instance_id": gateway.gateway_instance_id,
                "port": port,
                "security": "INSECURE_LOCALHOST_TEST_ONLY",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    server.wait_for_termination()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
