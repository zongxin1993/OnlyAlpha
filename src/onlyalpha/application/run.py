"""Unified Engine run use case."""

from __future__ import annotations

from typing import cast

from onlyalpha.config import OnlyRunConfig
from onlyalpha.output import OnlyRuntimeOutputManifest, OnlyRuntimeResultExporter
from onlyalpha.runtime.assembler import OnlyEngineRunAssembler
from onlyalpha.runtime.result import OnlyRuntimeResult, OnlyUnsupportedRuntimeResult


class OnlyEngineRunService:
    def __init__(self, assembler: OnlyEngineRunAssembler, exporter: OnlyRuntimeResultExporter) -> None:
        self._assembler = assembler
        self._exporter = exporter
        self._last_manifest: OnlyRuntimeOutputManifest | None = None

    @property
    def last_manifest(self) -> OnlyRuntimeOutputManifest | None:
        return self._last_manifest

    def run(self, config: OnlyRunConfig, *, export: bool = True) -> OnlyRuntimeResult:
        build = self._assembler.build(config)
        if build.runtime is None:
            return OnlyUnsupportedRuntimeResult(
                config.runtime_id,
                config.runtime.runtime_type,
                build.failure_code or "RUNTIME_FACTORY_NOT_AVAILABLE",
                build.failure_message or "Runtime factory did not create a Runtime",
            )
        runtime = build.runtime
        try:
            runtime.initialize()
            result = runtime.run()
        finally:
            runtime.close()
        if not hasattr(result, "to_dict"):
            raise TypeError("Runtime.run() must return OnlyRuntimeResult")
        typed_result = cast(OnlyRuntimeResult, result)
        if export:
            self._last_manifest = self._exporter.export(config, typed_result)
        return typed_result
