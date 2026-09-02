from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from typing import ClassVar as _ClassVar

DESCRIPTOR: _descriptor.FileDescriptor

class Capability(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CAPABILITY_UNSPECIFIED: _ClassVar[Capability]
    TEST_UNARY: _ClassVar[Capability]
    TEST_STREAM: _ClassVar[Capability]
CAPABILITY_UNSPECIFIED: Capability
TEST_UNARY: Capability
TEST_STREAM: Capability
