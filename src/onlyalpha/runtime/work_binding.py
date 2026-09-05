"""Stable Core port for immutable formal-work RuntimeGeneration binding."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import cast

from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority


def only_load_runtime_generation_work_authority(root: Path) -> OnlyRuntimeGenerationWorkAuthority:
    """Load the sole installed infrastructure authority without importing its implementation into Core."""

    entries = tuple(metadata.entry_points().select(group="onlyalpha.runtime_generation_work_authority"))
    if len(entries) != 1:
        raise RuntimeError("RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE")
    factory = entries[0].load()
    authority = factory(root)
    required = (
        "bind_new_work",
        "release_work",
        "require_work_binding",
        "require_work_generation",
        "work_ids_for_generation",
        "verify_hosted_generation",
    )
    if any(not callable(getattr(authority, name, None)) for name in required):
        raise RuntimeError("RUNTIME_GENERATION_WORK_AUTHORITY_INVALID")
    return cast(OnlyRuntimeGenerationWorkAuthority, authority)


__all__ = ["OnlyRuntimeGenerationWorkAuthority", "only_load_runtime_generation_work_authority"]
