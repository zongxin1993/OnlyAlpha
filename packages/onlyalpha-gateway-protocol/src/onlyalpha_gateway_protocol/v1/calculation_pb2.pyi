from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CalculationEmpty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalculationResolve(_message.Message):
    __slots__ = ("parameters_json",)
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    parameters_json: bytes
    def __init__(self, parameters_json: _Optional[bytes] = ...) -> None: ...

class CalculationCreate(_message.Message):
    __slots__ = ("binding_json", "definition_json", "bar_type_json", "parameters_json", "source_fingerprint")
    BINDING_JSON_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_JSON_FIELD_NUMBER: _ClassVar[int]
    BAR_TYPE_JSON_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    binding_json: bytes
    definition_json: bytes
    bar_type_json: bytes
    parameters_json: bytes
    source_fingerprint: str
    def __init__(self, binding_json: _Optional[bytes] = ..., definition_json: _Optional[bytes] = ..., bar_type_json: _Optional[bytes] = ..., parameters_json: _Optional[bytes] = ..., source_fingerprint: _Optional[str] = ...) -> None: ...

class CalculationInstance(_message.Message):
    __slots__ = ("scope", "revision")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    scope: str
    revision: int
    def __init__(self, scope: _Optional[str] = ..., revision: _Optional[int] = ...) -> None: ...

class CalculationUpdate(_message.Message):
    __slots__ = ("instance", "bars_json", "input_digest")
    INSTANCE_FIELD_NUMBER: _ClassVar[int]
    BARS_JSON_FIELD_NUMBER: _ClassVar[int]
    INPUT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    instance: CalculationInstance
    bars_json: _containers.RepeatedScalarFieldContainer[bytes]
    input_digest: str
    def __init__(self, instance: _Optional[_Union[CalculationInstance, _Mapping]] = ..., bars_json: _Optional[_Iterable[bytes]] = ..., input_digest: _Optional[str] = ...) -> None: ...

class CalculationRestore(_message.Message):
    __slots__ = ("instance", "checkpoint_json", "expected_sha256")
    INSTANCE_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_JSON_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_SHA256_FIELD_NUMBER: _ClassVar[int]
    instance: CalculationInstance
    checkpoint_json: bytes
    expected_sha256: str
    def __init__(self, instance: _Optional[_Union[CalculationInstance, _Mapping]] = ..., checkpoint_json: _Optional[bytes] = ..., expected_sha256: _Optional[str] = ...) -> None: ...

class CalculationNode(_message.Message):
    __slots__ = ("request_json",)
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    request_json: bytes
    def __init__(self, request_json: _Optional[bytes] = ...) -> None: ...

class CalculationRequest(_message.Message):
    __slots__ = ("protocol_version", "generation", "sequence", "handshake", "resolve", "create", "update", "reset", "checkpoint", "restore", "close", "node")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_FIELD_NUMBER: _ClassVar[int]
    RESOLVE_FIELD_NUMBER: _ClassVar[int]
    CREATE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    RESET_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_FIELD_NUMBER: _ClassVar[int]
    RESTORE_FIELD_NUMBER: _ClassVar[int]
    CLOSE_FIELD_NUMBER: _ClassVar[int]
    NODE_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    generation: str
    sequence: int
    handshake: CalculationEmpty
    resolve: CalculationResolve
    create: CalculationCreate
    update: CalculationUpdate
    reset: CalculationInstance
    checkpoint: CalculationInstance
    restore: CalculationRestore
    close: CalculationInstance
    node: CalculationNode
    def __init__(self, protocol_version: _Optional[int] = ..., generation: _Optional[str] = ..., sequence: _Optional[int] = ..., handshake: _Optional[_Union[CalculationEmpty, _Mapping]] = ..., resolve: _Optional[_Union[CalculationResolve, _Mapping]] = ..., create: _Optional[_Union[CalculationCreate, _Mapping]] = ..., update: _Optional[_Union[CalculationUpdate, _Mapping]] = ..., reset: _Optional[_Union[CalculationInstance, _Mapping]] = ..., checkpoint: _Optional[_Union[CalculationInstance, _Mapping]] = ..., restore: _Optional[_Union[CalculationRestore, _Mapping]] = ..., close: _Optional[_Union[CalculationInstance, _Mapping]] = ..., node: _Optional[_Union[CalculationNode, _Mapping]] = ...) -> None: ...

class CalculationError(_message.Message):
    __slots__ = ("code",)
    CODE_FIELD_NUMBER: _ClassVar[int]
    code: str
    def __init__(self, code: _Optional[str] = ...) -> None: ...

class CalculationRecord(_message.Message):
    __slots__ = ("record_json",)
    RECORD_JSON_FIELD_NUMBER: _ClassVar[int]
    record_json: bytes
    def __init__(self, record_json: _Optional[bytes] = ...) -> None: ...

class CalculationResponse(_message.Message):
    __slots__ = ("protocol_version", "generation", "sequence", "artifact_fingerprint", "diagnostic_compute_ns", "result", "error")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    DIAGNOSTIC_COMPUTE_NS_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    generation: str
    sequence: int
    artifact_fingerprint: str
    diagnostic_compute_ns: int
    result: CalculationRecord
    error: CalculationError
    def __init__(self, protocol_version: _Optional[int] = ..., generation: _Optional[str] = ..., sequence: _Optional[int] = ..., artifact_fingerprint: _Optional[str] = ..., diagnostic_compute_ns: _Optional[int] = ..., result: _Optional[_Union[CalculationRecord, _Mapping]] = ..., error: _Optional[_Union[CalculationError, _Mapping]] = ...) -> None: ...
