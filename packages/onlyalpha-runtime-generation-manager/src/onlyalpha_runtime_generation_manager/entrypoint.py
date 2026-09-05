"""Installed infrastructure SPI implementation for formal work generation binding."""

from __future__ import annotations

from pathlib import Path

from .registry import OnlyRuntimeGenerationRegistry


def runtime_generation_work_authority(root: Path) -> OnlyRuntimeGenerationRegistry:
    return OnlyRuntimeGenerationRegistry(root)


__all__ = ["runtime_generation_work_authority"]
