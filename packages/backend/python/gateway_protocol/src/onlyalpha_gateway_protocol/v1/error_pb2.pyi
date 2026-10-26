from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GatewayErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GATEWAY_ERROR_CODE_UNSPECIFIED: _ClassVar[GatewayErrorCode]
    INVALID_REQUEST: _ClassVar[GatewayErrorCode]
    PROTOCOL_MISMATCH: _ClassVar[GatewayErrorCode]
    UNSUPPORTED_CAPABILITY: _ClassVar[GatewayErrorCode]
    NOT_READY: _ClassVar[GatewayErrorCode]
    COMMAND_CONFLICT: _ClassVar[GatewayErrorCode]
    PROVIDER_UNAVAILABLE: _ClassVar[GatewayErrorCode]
    PROVIDER_REJECTED: _ClassVar[GatewayErrorCode]
    DEADLINE_EXCEEDED: _ClassVar[GatewayErrorCode]
    RESYNC_REQUIRED: _ClassVar[GatewayErrorCode]
    INTERNAL_ERROR: _ClassVar[GatewayErrorCode]
GATEWAY_ERROR_CODE_UNSPECIFIED: GatewayErrorCode
INVALID_REQUEST: GatewayErrorCode
PROTOCOL_MISMATCH: GatewayErrorCode
UNSUPPORTED_CAPABILITY: GatewayErrorCode
NOT_READY: GatewayErrorCode
COMMAND_CONFLICT: GatewayErrorCode
PROVIDER_UNAVAILABLE: GatewayErrorCode
PROVIDER_REJECTED: GatewayErrorCode
DEADLINE_EXCEEDED: GatewayErrorCode
RESYNC_REQUIRED: GatewayErrorCode
INTERNAL_ERROR: GatewayErrorCode

class GatewayError(_message.Message):
    __slots__ = ("code", "message", "provider_code", "provider_message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_CODE_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: GatewayErrorCode
    message: str
    provider_code: str
    provider_message: str
    def __init__(self, code: _Optional[_Union[GatewayErrorCode, str]] = ..., message: _Optional[str] = ..., provider_code: _Optional[str] = ..., provider_message: _Optional[str] = ...) -> None: ...
