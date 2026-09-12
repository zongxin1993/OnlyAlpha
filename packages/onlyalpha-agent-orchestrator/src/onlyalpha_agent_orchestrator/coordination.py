"""Crash-releasing same-host coordination for one Agent Session transition."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class OnlyAgentSessionExecutionBusy(RuntimeError):
    """Operational contention signal; never persisted as Session semantics."""


class OnlyAgentSessionExecutionCoordinatorV1:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("AGENT_SESSION_COORDINATION_ROOT_INVALID")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("AGENT_SESSION_COORDINATION_ROOT_INVALID")
        self._root = root

    @contextmanager
    def acquire(self, session_fingerprint: str) -> Iterator[None]:
        if len(session_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in session_fingerprint
        ):
            raise ValueError("AGENT_SESSION_COORDINATION_ID_INVALID")
        path = self._root / f"{session_fingerprint}.lock"
        descriptor = os.open(path, os.O_CLOEXEC | os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise OnlyAgentSessionExecutionBusy(session_fingerprint) from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


__all__ = ["OnlyAgentSessionExecutionBusy", "OnlyAgentSessionExecutionCoordinatorV1"]
