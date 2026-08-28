from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import grpc

from .constants import PROTOCOL_MAJOR
from .identity import canonical_test_mutation_fingerprint
from .v1 import common_pb2, gateway_pb2, stream_pb2


class OnlyGatewayConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    HANDSHAKING = "HANDSHAKING"
    READY = "READY"
    STREAMING = "STREAMING"


class OnlyGatewayProtocolError(RuntimeError):
    pass


class OnlyGatewayApplicationError(OnlyGatewayProtocolError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class OnlyGatewayTransportError(OnlyGatewayProtocolError):
    def __init__(self, message: str, *, outcome_unknown: bool) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


class OnlyGatewayResyncRequired(OnlyGatewayProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyGatewayHandshake:
    gateway_id: str
    gateway_instance_id: str
    protocol_major: int
    contract_sha256: str
    implementation_version: str
    capabilities: frozenset[int]


@dataclass(frozen=True, slots=True)
class OnlyTestMutationOutcome:
    command_id: str
    outcome_id: str
    execution_count: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class OnlyTestStreamEvent:
    stream_id: str
    gateway_instance_id: str
    sequence: int
    event_id: str
    observed_at_unix_nanos: int
    payload: str


@dataclass(frozen=True, slots=True)
class OnlyTestStreamBatch:
    events: tuple[OnlyTestStreamEvent, ...]
    duplicate_sequences: tuple[int, ...]


class OnlyGatewayClient:
    """Small infrastructure client with explicit handshake and stream continuity."""

    def __init__(self, target: str) -> None:
        self._target = target
        self._channel: grpc.Channel | None = None
        self._handshake: OnlyGatewayHandshake | None = None
        self._state = OnlyGatewayConnectionState.DISCONNECTED

    @property
    def state(self) -> OnlyGatewayConnectionState:
        return self._state

    @property
    def handshake(self) -> OnlyGatewayHandshake:
        if self._handshake is None:
            raise OnlyGatewayProtocolError("Gateway handshake is not established")
        return self._handshake

    def connect(
        self,
        *,
        required_capabilities: Iterable[int],
        correlation_id: str,
        protocol_major: int = PROTOCOL_MAJOR,
        timeout: float = 5.0,
    ) -> OnlyGatewayHandshake:
        if self._state is not OnlyGatewayConnectionState.DISCONNECTED:
            raise OnlyGatewayProtocolError(f"cannot connect from {self._state}")
        self._state = OnlyGatewayConnectionState.CONNECTING
        channel = grpc.insecure_channel(self._target)
        self._channel = channel
        self._state = OnlyGatewayConnectionState.HANDSHAKING
        call = channel.unary_unary(
            "/onlyalpha.gateway.v1.GatewayService/Handshake",
            request_serializer=gateway_pb2.HandshakeRequest.SerializeToString,
            response_deserializer=gateway_pb2.HandshakeResponse.FromString,
        )
        request = gateway_pb2.HandshakeRequest(
            protocol_major=protocol_major,
            required_capabilities=[cast(common_pb2.Capability, item) for item in sorted(set(required_capabilities))],
            correlation_id=correlation_id,
        )
        try:
            response = call(request, timeout=timeout)
        except grpc.RpcError as exc:
            self.close()
            raise OnlyGatewayTransportError(str(exc), outcome_unknown=False) from exc
        if response.error.code:
            code = response.error.code
            message = response.error.message
            self.close()
            raise OnlyGatewayApplicationError(code, message)
        if response.protocol_major != protocol_major or response.protocol_major != PROTOCOL_MAJOR:
            self.close()
            raise OnlyGatewayProtocolError("Gateway returned an incompatible protocol major")
        required = frozenset(request.required_capabilities)
        advertised = frozenset(response.capabilities)
        if not required <= advertised:
            self.close()
            raise OnlyGatewayProtocolError("Gateway omitted a required capability")
        identity = response.identity
        if not identity.gateway_id or not identity.gateway_instance_id:
            self.close()
            raise OnlyGatewayProtocolError("Gateway returned an incomplete identity")
        self._handshake = OnlyGatewayHandshake(
            gateway_id=identity.gateway_id,
            gateway_instance_id=identity.gateway_instance_id,
            protocol_major=response.protocol_major,
            contract_sha256=response.contract_sha256,
            implementation_version=response.implementation_version,
            capabilities=advertised,
        )
        self._state = OnlyGatewayConnectionState.READY
        return self._handshake

    def apply_test_mutation(
        self,
        *,
        command_id: str,
        correlation_id: str,
        payload: str,
        timeout: float = 5.0,
    ) -> OnlyTestMutationOutcome:
        channel = self._ready_channel(common_pb2.TEST_UNARY)
        call = channel.unary_unary(
            "/onlyalpha.gateway.v1.GatewayService/ApplyTestMutation",
            request_serializer=gateway_pb2.ApplyTestMutationRequest.SerializeToString,
            response_deserializer=gateway_pb2.ApplyTestMutationResponse.FromString,
        )
        request = gateway_pb2.ApplyTestMutationRequest(
            identity={
                "command_id": command_id,
                "command_fingerprint": canonical_test_mutation_fingerprint(payload),
                "correlation_id": correlation_id,
            },
            payload=payload,
        )
        try:
            response = call(request, timeout=timeout)
        except grpc.RpcError as exc:
            self.close()
            raise OnlyGatewayTransportError(str(exc), outcome_unknown=True) from exc
        if response.error.code:
            raise OnlyGatewayApplicationError(response.error.code, response.error.message)
        return OnlyTestMutationOutcome(
            command_id=response.command_id,
            outcome_id=response.outcome_id,
            execution_count=response.execution_count,
            replayed=response.replayed,
        )

    def watch_test_events(
        self,
        *,
        stream_id: str,
        resume_after: int,
        timeout: float = 5.0,
    ) -> OnlyTestStreamBatch:
        channel = self._ready_channel(common_pb2.TEST_STREAM)
        self._state = OnlyGatewayConnectionState.STREAMING
        call = channel.unary_stream(
            "/onlyalpha.gateway.v1.GatewayStreamService/WatchTestEvents",
            request_serializer=stream_pb2.WatchTestEventsRequest.SerializeToString,
            response_deserializer=stream_pb2.TestStreamItem.FromString,
        )
        request = stream_pb2.WatchTestEventsRequest(
            gateway_instance_id=self.handshake.gateway_instance_id,
            stream_id=stream_id,
            resume_after=resume_after,
        )
        events: list[OnlyTestStreamEvent] = []
        duplicates: list[int] = []
        last_sequence = resume_after
        try:
            responses = call(request, timeout=timeout)
            for raw in responses:
                item = raw
                if item.HasField("error"):
                    if item.error.code:
                        raise OnlyGatewayResyncRequired(item.error.message)
                    raise OnlyGatewayProtocolError("stream returned an unspecified error")
                if not item.HasField("event"):
                    raise OnlyGatewayProtocolError("stream item contains neither event nor error")
                event = item.event
                if event.gateway_instance_id != self.handshake.gateway_instance_id or event.stream_id != stream_id:
                    raise OnlyGatewayProtocolError("stream event identity does not match the active handshake")
                if event.sequence <= last_sequence:
                    duplicates.append(event.sequence)
                    continue
                if event.sequence != last_sequence + 1:
                    raise OnlyGatewayResyncRequired(
                        f"stream gap: expected {last_sequence + 1}, received {event.sequence}"
                    )
                events.append(
                    OnlyTestStreamEvent(
                        stream_id=event.stream_id,
                        gateway_instance_id=event.gateway_instance_id,
                        sequence=event.sequence,
                        event_id=event.event_id,
                        observed_at_unix_nanos=event.observed_at_unix_nanos,
                        payload=event.payload,
                    )
                )
                last_sequence = event.sequence
        except OnlyGatewayProtocolError:
            self._state = OnlyGatewayConnectionState.READY
            raise
        except grpc.RpcError as exc:
            self.close()
            raise OnlyGatewayTransportError(str(exc), outcome_unknown=False) from exc
        self._state = OnlyGatewayConnectionState.READY
        return OnlyTestStreamBatch(tuple(events), tuple(duplicates))

    def close(self) -> None:
        channel = self._channel
        self._channel = None
        self._handshake = None
        self._state = OnlyGatewayConnectionState.DISCONNECTED
        if channel is not None:
            channel.close()

    def _ready_channel(self, capability: int) -> grpc.Channel:
        if self._state is not OnlyGatewayConnectionState.READY or self._channel is None:
            raise OnlyGatewayProtocolError(f"Gateway is not ready: {self._state}")
        if capability not in self.handshake.capabilities:
            raise OnlyGatewayProtocolError(f"Gateway does not advertise required capability {capability}")
        return self._channel

    def __enter__(self) -> OnlyGatewayClient:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
