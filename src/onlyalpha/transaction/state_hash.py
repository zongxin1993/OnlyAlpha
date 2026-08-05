"""Canonical hashing for persisted execution authority states."""

from __future__ import annotations

import hashlib
import json

from onlyalpha.domain.base import OnlyDomainModel


def only_execution_state_hash(state: OnlyDomainModel | None) -> str:
    """Return a process-independent SHA-256 digest for one authority state."""

    payload: object = None if state is None else state.to_dict()
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["only_execution_state_hash"]
