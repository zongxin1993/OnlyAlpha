from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class GatewayIdentity(_message.Message):
    __slots__ = ("gateway_id", "gateway_instance_id")
    GATEWAY_ID_FIELD_NUMBER: _ClassVar[int]
    GATEWAY_INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    gateway_id: str
    gateway_instance_id: str
    def __init__(self, gateway_id: _Optional[str] = ..., gateway_instance_id: _Optional[str] = ...) -> None: ...

class RemoteCommandIdentity(_message.Message):
    __slots__ = ("command_id", "command_fingerprint", "correlation_id")
    COMMAND_ID_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    command_id: str
    command_fingerprint: str
    correlation_id: str
    def __init__(self, command_id: _Optional[str] = ..., command_fingerprint: _Optional[str] = ..., correlation_id: _Optional[str] = ...) -> None: ...
