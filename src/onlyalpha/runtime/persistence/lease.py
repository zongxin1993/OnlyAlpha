"""Cross-process single-writer ownership for one Runtime state root."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from onlyalpha.domain.identifiers import OnlyRuntimeId


class OnlyRuntimeStateLeaseAlreadyHeld(RuntimeError):
    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self.code = "RUNTIME_STATE_LEASE_ALREADY_HELD"
        super().__init__(f"{self.code}: runtime_id={runtime_id}")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeStateLeaseOwner:
    runtime_id: OnlyRuntimeId
    runtime_instance_id: str
    process_id: int


class OnlyRuntimeStateLease:
    """An OS-released advisory write lease; metadata is diagnostic only."""

    def __init__(self, state_root: Path, runtime_id: OnlyRuntimeId) -> None:
        state_root.mkdir(parents=True, exist_ok=True)
        self._path = state_root / "runtime.lock"
        self._file = self._path.open("a+", encoding="utf-8")
        self._owner = OnlyRuntimeStateLeaseOwner(runtime_id, str(uuid4()), os.getpid())
        self._closed = False
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._file.close()
            raise OnlyRuntimeStateLeaseAlreadyHeld(runtime_id) from exc
        self._file.seek(0)
        self._file.truncate()
        json.dump(
            {
                "process_id": self._owner.process_id,
                "runtime_id": str(runtime_id),
                "runtime_instance_id": self._owner.runtime_instance_id,
            },
            self._file,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._file.flush()

    @property
    def owner(self) -> OnlyRuntimeStateLeaseOwner:
        return self._owner

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()


__all__ = [
    "OnlyRuntimeStateLease",
    "OnlyRuntimeStateLeaseAlreadyHeld",
    "OnlyRuntimeStateLeaseOwner",
]
