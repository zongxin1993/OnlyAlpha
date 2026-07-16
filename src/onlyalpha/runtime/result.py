"""Runtime-agnostic operation and run results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OnlyRuntimeResultStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class OnlyRuntimeResult(Protocol):
    @property
    def runtime_id(self) -> object: ...

    @property
    def runtime_type(self) -> str: ...

    @property
    def status(self) -> object: ...

    @property
    def determinism_fingerprint(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyUnsupportedRuntimeResult:
    runtime_id: object
    runtime_type: str
    failure_code: str
    failure_message: str

    @property
    def status(self) -> OnlyRuntimeResultStatus:
        return OnlyRuntimeResultStatus.UNSUPPORTED

    @property
    def determinism_fingerprint(self) -> str:
        return ""

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_id": str(self.runtime_id),
            "runtime_type": self.runtime_type,
            "status": self.status.value,
            "failure": {"code": self.failure_code, "message": self.failure_message},
            "determinism_fingerprint": "",
        }
