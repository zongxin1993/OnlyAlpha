from onlyalpha_gateway_protocol.v1 import error_pb2 as _error_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WatchTestEventsRequest(_message.Message):
    __slots__ = ("gateway_instance_id", "stream_id", "resume_after")
    GATEWAY_INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    RESUME_AFTER_FIELD_NUMBER: _ClassVar[int]
    gateway_instance_id: str
    stream_id: str
    resume_after: int
    def __init__(self, gateway_instance_id: _Optional[str] = ..., stream_id: _Optional[str] = ..., resume_after: _Optional[int] = ...) -> None: ...

class TestEvent(_message.Message):
    __slots__ = ("stream_id", "gateway_instance_id", "sequence", "event_id", "observed_at_unix_nanos", "payload")
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    GATEWAY_INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_AT_UNIX_NANOS_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    stream_id: str
    gateway_instance_id: str
    sequence: int
    event_id: str
    observed_at_unix_nanos: int
    payload: str
    def __init__(self, stream_id: _Optional[str] = ..., gateway_instance_id: _Optional[str] = ..., sequence: _Optional[int] = ..., event_id: _Optional[str] = ..., observed_at_unix_nanos: _Optional[int] = ..., payload: _Optional[str] = ...) -> None: ...

class TestStreamItem(_message.Message):
    __slots__ = ("event", "error")
    EVENT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    event: TestEvent
    error: _error_pb2.GatewayError
    def __init__(self, event: _Optional[_Union[TestEvent, _Mapping]] = ..., error: _Optional[_Union[_error_pb2.GatewayError, _Mapping]] = ...) -> None: ...
