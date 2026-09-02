from onlyalpha_gateway_protocol.v1 import common_pb2 as _common_pb2
from onlyalpha_gateway_protocol.v1 import error_pb2 as _error_pb2
from onlyalpha_gateway_protocol.v1 import identity_pb2 as _identity_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HandshakeRequest(_message.Message):
    __slots__ = ("protocol_major", "required_capabilities", "correlation_id")
    PROTOCOL_MAJOR_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    protocol_major: int
    required_capabilities: _containers.RepeatedScalarFieldContainer[_common_pb2.Capability]
    correlation_id: str
    def __init__(self, protocol_major: _Optional[int] = ..., required_capabilities: _Optional[_Iterable[_Union[_common_pb2.Capability, str]]] = ..., correlation_id: _Optional[str] = ...) -> None: ...

class HandshakeResponse(_message.Message):
    __slots__ = ("identity", "protocol_major", "contract_sha256", "implementation_version", "capabilities", "error")
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_MAJOR_FIELD_NUMBER: _ClassVar[int]
    CONTRACT_SHA256_FIELD_NUMBER: _ClassVar[int]
    IMPLEMENTATION_VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    identity: _identity_pb2.GatewayIdentity
    protocol_major: int
    contract_sha256: str
    implementation_version: str
    capabilities: _containers.RepeatedScalarFieldContainer[_common_pb2.Capability]
    error: _error_pb2.GatewayError
    def __init__(self, identity: _Optional[_Union[_identity_pb2.GatewayIdentity, _Mapping]] = ..., protocol_major: _Optional[int] = ..., contract_sha256: _Optional[str] = ..., implementation_version: _Optional[str] = ..., capabilities: _Optional[_Iterable[_Union[_common_pb2.Capability, str]]] = ..., error: _Optional[_Union[_error_pb2.GatewayError, _Mapping]] = ...) -> None: ...

class ApplyTestMutationRequest(_message.Message):
    __slots__ = ("identity", "payload")
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    identity: _identity_pb2.RemoteCommandIdentity
    payload: str
    def __init__(self, identity: _Optional[_Union[_identity_pb2.RemoteCommandIdentity, _Mapping]] = ..., payload: _Optional[str] = ...) -> None: ...

class ApplyTestMutationResponse(_message.Message):
    __slots__ = ("command_id", "outcome_id", "execution_count", "replayed", "error")
    COMMAND_ID_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_ID_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_COUNT_FIELD_NUMBER: _ClassVar[int]
    REPLAYED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    command_id: str
    outcome_id: str
    execution_count: int
    replayed: bool
    error: _error_pb2.GatewayError
    def __init__(self, command_id: _Optional[str] = ..., outcome_id: _Optional[str] = ..., execution_count: _Optional[int] = ..., replayed: bool = ..., error: _Optional[_Union[_error_pb2.GatewayError, _Mapping]] = ...) -> None: ...
