"""Unified Engine run use case."""

from __future__ import annotations

from typing import cast

from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.output import OnlyRuntimeOutputManifest, OnlyRuntimeResultExporter
from onlyalpha.runtime.assembler import OnlyEngineRunAssembler
from onlyalpha.runtime.planning import OnlyRuntimeCompatibilityKey, OnlyRuntimePlan
from onlyalpha.runtime.result import OnlyRuntimeResult, OnlyUnsupportedRuntimeResult


class OnlyEngineRunService:
    """Deprecated adapter retained only for legacy Runtime tests."""

    def __init__(self, assembler: OnlyEngineRunAssembler, exporter: OnlyRuntimeResultExporter) -> None:
        self._assembler = assembler
        self._exporter = exporter
        self._last_manifest: OnlyRuntimeOutputManifest | None = None

    @property
    def last_manifest(self) -> OnlyRuntimeOutputManifest | None:
        return self._last_manifest

    def run(self, config: OnlyRuntimeAssemblyPlan, *, export: bool = True) -> OnlyRuntimeResult:
        key = OnlyRuntimeCompatibilityKey(
            config.runtime.runtime_type,
            "" if config.start_time is None else config.start_time.isoformat(),
            "" if config.end_time is None else config.end_time.isoformat(),
            "HISTORICAL_REPLAY" if config.runtime.runtime_type == "BACKTEST" else "LIVE_CLOCK",
            "legacy",
            ",".join(str(item.data_version) for item in config.data_sources),
            "legacy",
            "legacy",
        )
        plan = OnlyRuntimePlan(
            config.runtime_id,
            key,
            tuple(OnlyClusterId(str(item.cluster_id)) for item in config.clusters),
            (),
            config,
        )
        build = self._assembler.build(plan)
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
            runtime.start()
            result = runtime.run()
        finally:
            runtime.close()
        if not hasattr(result, "to_dict"):
            raise TypeError("Runtime.run() must return OnlyRuntimeResult")
        typed_result = cast(OnlyRuntimeResult, result)
        if export:
            self._last_manifest = self._exporter.export(config, typed_result)
        return typed_result
