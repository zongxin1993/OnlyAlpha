"""Hatch build hook for immutable packaged OnlyAlpha provenance."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import Any, cast

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface[Any]):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        root = Path(self.root)
        generator = run_path(str(root / "scripts" / "embed_build_provenance.py"), run_name="onlyalpha_build_provenance")
        resolve = cast(Callable[[Path], str], generator["resolve_build_source_revision"])
        write = cast(Callable[[Path, Path, str], Path], generator["write_build_provenance"])
        generated = root / "build" / "onlyalpha-build-provenance" / "_build_provenance.json"
        write(root, generated, resolve(root))
        destination = (
            "onlyalpha/_build_provenance.json"
            if self.target_name == "wheel"
            else "src/onlyalpha/_build_provenance.json"
        )
        build_data["force_include"][str(generated)] = destination
