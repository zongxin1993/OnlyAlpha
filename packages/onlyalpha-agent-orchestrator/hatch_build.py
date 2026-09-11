"""Hatch build hook for immutable Orchestrator distribution provenance."""

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
        helper = run_path(str(root / "provenance_build.py"), run_name="onlyalpha_agent_orchestrator_provenance")
        resolve = cast(Callable[[Path], bytes], helper["resolve_build_provenance_bytes"])
        write = cast(Callable[[Path, bytes], None], helper["write_build_provenance"])
        generated = root / "build" / "onlyalpha-agent-orchestrator-provenance" / "_build_provenance.json"
        write(generated, resolve(root))
        destination = (
            "onlyalpha_agent_orchestrator/_build_provenance.json"
            if self.target_name == "wheel"
            else "src/onlyalpha_agent_orchestrator/_build_provenance.json"
        )
        build_data["force_include"][str(generated)] = destination
        if self.target_name == "sdist":
            build_data["force_include"][str(generated.with_name("_build_provenance.sha256"))] = (
                "src/onlyalpha_agent_orchestrator/_build_provenance.sha256"
            )
