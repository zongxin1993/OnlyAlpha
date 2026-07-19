"""Product-level Cluster, Runtime session, and infrastructure coordinator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.artifact import OnlyBacktestArtifactWriter, OnlyRunArtifactTarget
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.engine.infrastructure import OnlyInfrastructureRegistry
from onlyalpha.engine.models import (
    OnlyClusterHandle,
    OnlyClusterLoadError,
    OnlyClusterOperationResult,
    OnlyClusterRemovalPolicy,
    OnlyClusterRemovalResult,
    OnlyClusterSession,
    OnlyEngineClusterStatus,
    OnlyEngineConfig,
    OnlyEngineRunResult,
    OnlyEngineSnapshot,
    OnlyEngineState,
    OnlyEngineValidationResult,
    OnlyRuntimeSession,
)
from onlyalpha.output import OnlyEngineResultExporter, OnlyUserDataLayout
from onlyalpha.report import OnlyConsoleBacktestReport, OnlyJsonBacktestReport, OnlyMarkdownBacktestReport
from onlyalpha.runtime.backtest.result import OnlyBacktestResult
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.planning import (
    OnlyEngineExecutionPlan,
    OnlyRuntimeCompatibilityKey,
    OnlyRuntimePlanner,
)
from onlyalpha.runtime.result import OnlyRuntimeResult
from onlyalpha.runtime.runtime import OnlyRuntime
from onlyalpha.storage.base import OnlyStorage
from onlyalpha.strategy.factory import only_load_type


class OnlyEngine:
    """Sole product owner of Cluster, Runtime, and infrastructure lifecycle."""

    def __init__(
        self,
        config: OnlyEngineConfig,
        storage: OnlyStorage | None = None,
        *,
        services: OnlyEngineServices | None = None,
    ) -> None:
        if not isinstance(config, OnlyEngineConfig):
            raise TypeError("config must be OnlyEngineConfig")
        self.config = config
        self.engine_id = str(self.config.engine_id)
        self.storage = storage
        self.state = OnlyEngineState.CREATED
        self._services = services
        self._cluster_definitions: dict[OnlyClusterId, OnlyClusterRunConfig] = {}
        self._cluster_sessions: dict[OnlyClusterId, OnlyClusterSession] = {}
        self._runtime_sessions: dict[str, OnlyRuntimeSession] = {}
        self._handles: dict[OnlyClusterId, OnlyClusterHandle] = {}
        self._infrastructure = OnlyInfrastructureRegistry()
        self._planner = OnlyRuntimePlanner()
        self._execution_plan: OnlyEngineExecutionPlan | None = None

    @property
    def runtimes(self) -> tuple[OnlyRuntime, ...]:
        return tuple(item.runtime for item in self._runtime_sessions.values())

    @property
    def cluster_definitions(self) -> tuple[OnlyClusterRunConfig, ...]:
        return tuple(self._cluster_definitions.values())

    @property
    def cluster_sessions(self) -> tuple[OnlyClusterSession, ...]:
        return tuple(self._cluster_sessions.values())

    @property
    def runtime_sessions(self) -> tuple[OnlyRuntimeSession, ...]:
        return tuple(self._runtime_sessions.values())

    @property
    def cluster_handles(self) -> tuple[OnlyClusterHandle, ...]:
        return tuple(self._handles.values())

    @property
    def infrastructure_registry(self) -> OnlyInfrastructureRegistry:
        return self._infrastructure

    def add_cluster_from_file(self, path: str | Path) -> OnlyClusterHandle:
        return self.add_cluster(OnlyClusterRunConfig.load(path))

    def add_cluster(self, config: OnlyClusterRunConfig) -> OnlyClusterHandle:
        if self.state is OnlyEngineState.RUNNING:
            raise OnlyClusterLoadError("DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE")
        if self.state not in {OnlyEngineState.CREATED, OnlyEngineState.CONFIGURING, OnlyEngineState.READY}:
            raise OnlyLifecycleError(f"cannot add Cluster while Engine is {self.state}")
        if config.cluster_id in self._cluster_definitions:
            raise OnlyDuplicateIdError(f"cluster already registered: {config.cluster_id}")
        previous = self.state
        self.state = OnlyEngineState.CONFIGURING
        acquired = False
        try:
            resources = self._infrastructure.acquire(config)
            acquired = True
            self._validate_extension_types(config)
            fingerprint = self._config_fingerprint(config)
            handle = OnlyClusterHandle(
                config.cluster_id,
                config.runtime_id,
                OnlyEngineClusterStatus.LOADED,
                fingerprint,
            )
            self._cluster_definitions[config.cluster_id] = config
            self._handles[config.cluster_id] = handle
            if resources != self._infrastructure.references_for(config.cluster_id):
                raise RuntimeError("infrastructure references were not registered atomically")
            self.state = OnlyEngineState.READY
            return handle
        except Exception:
            if acquired:
                self._infrastructure.release(config.cluster_id)
            self.state = previous
            raise

    def remove_cluster(
        self,
        cluster_id: OnlyClusterId,
        *,
        policy: OnlyClusterRemovalPolicy = OnlyClusterRemovalPolicy.STOP_ONLY,
    ) -> OnlyClusterRemovalResult:
        if cluster_id not in self._cluster_definitions:
            return OnlyClusterRemovalResult(False, cluster_id, "CLUSTER_NOT_FOUND")
        if self._cluster_sessions:
            return OnlyClusterRemovalResult(False, cluster_id, "CLUSTER_ALREADY_INITIALIZED")
        if policy is not OnlyClusterRemovalPolicy.STOP_ONLY:
            return OnlyClusterRemovalResult(
                False,
                cluster_id,
                "CLUSTER_REMOVAL_POLICY_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE",
                message=policy.value,
            )
        released = self._infrastructure.release(cluster_id)
        del self._cluster_definitions[cluster_id]
        del self._handles[cluster_id]
        self.state = OnlyEngineState.READY if self._cluster_definitions else OnlyEngineState.CREATED
        return OnlyClusterRemovalResult(True, cluster_id, "REMOVED", released_resources=released)

    def start_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "START")

    def pause_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "PAUSE")

    def resume_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "RESUME")

    def validate(self) -> OnlyEngineValidationResult:
        errors: list[str] = []
        plan = self._planner.plan(self.config.engine_id, self.cluster_definitions)
        services = self._require_services()
        for runtime_plan in plan.runtime_plans:
            validation = services.assembler.validate(runtime_plan)
            if validation.failure_code is not None:
                errors.append(f"{runtime_plan.cluster_ids}: {validation.failure_code}: {validation.failure_message}")
        return OnlyEngineValidationResult(
            not errors and bool(self._cluster_definitions),
            len(self._cluster_definitions),
            len(plan.runtime_plans),
            tuple(errors),
            self.config.user_data_root,
            self._plugin_descriptions(services),
            tuple(
                sorted(
                    (
                        f"data_source:{source.source_id}->{source.plugin_id}"
                        for config in self.cluster_definitions
                        for source in config.data_sources
                        if source.enabled
                    ),
                )
            )
            + tuple(
                sorted(
                    (
                        f"broker:{broker.gateway_id}->{broker.plugin_id}"
                        for config in self.cluster_definitions
                        for broker in config.brokers
                        if broker.enabled
                    ),
                )
            ),
        )

    def initialize(self) -> None:
        self._require_not_terminated("initialize")
        if self._cluster_sessions:
            if self.state is OnlyEngineState.READY:
                return
            raise OnlyLifecycleError("Engine sessions are already initialized")
        if self.state not in {OnlyEngineState.CREATED, OnlyEngineState.READY}:
            raise OnlyLifecycleError(f"cannot initialize Engine while {self.state}")
        if not self._cluster_definitions:
            raise OnlyLifecycleError("Engine requires at least one Cluster definition")
        plan = self._planner.plan(self.config.engine_id, self.cluster_definitions)
        created: list[OnlyRuntime] = []
        try:
            for runtime_plan in plan.runtime_plans:
                build = self._require_services().assembler.build(runtime_plan, self.config.user_data_root)
                if build.runtime is None:
                    raise RuntimeError(f"{build.failure_code}: {build.failure_message}")
                runtime = build.runtime
                created.append(runtime)
                runtime.initialize()
                runtime_session = OnlyRuntimeSession(
                    runtime_plan.runtime_id,
                    runtime,
                    runtime_plan.compatibility_key,
                    runtime_plan.cluster_ids,
                    "READY",
                )
                self._runtime_sessions[str(runtime_plan.runtime_id)] = runtime_session
                clusters = {OnlyClusterId(item.config.cluster_id): item for item in runtime.clusters}
                for config in runtime_plan.cluster_configs:
                    cluster = clusters[config.cluster_id]
                    session = OnlyClusterSession(
                        config.cluster_id,
                        cluster,
                        runtime_plan.runtime_id,
                        OnlyEngineClusterStatus.READY,
                        self._infrastructure.references_for(config.cluster_id),
                        self._config_fingerprint(config),
                    )
                    self._cluster_sessions[config.cluster_id] = session
                    self._handles[config.cluster_id] = replace(
                        self._handles[config.cluster_id],
                        runtime_id=runtime_plan.runtime_id,
                        status=OnlyEngineClusterStatus.READY,
                    )
            self._execution_plan = plan
            self.state = OnlyEngineState.READY
        except Exception:
            for runtime in reversed(created):
                runtime.close()
            self._runtime_sessions.clear()
            self._cluster_sessions.clear()
            self._execution_plan = None
            for cluster_id in reversed(tuple(self._cluster_definitions)):
                self._infrastructure.release(cluster_id)
            self.state = OnlyEngineState.FAILED
            raise

    def start(self) -> None:
        if self.state is not OnlyEngineState.READY:
            raise OnlyLifecycleError("engine can only start from READY")
        for session in self.runtime_sessions:
            session.runtime.start()
            session.state = "RUNNING"
            for cluster_id in session.bound_cluster_ids:
                self._cluster_sessions[cluster_id].state = OnlyEngineClusterStatus.RUNNING
                self._handles[cluster_id] = replace(self._handles[cluster_id], status=OnlyEngineClusterStatus.RUNNING)
        self.state = OnlyEngineState.RUNNING

    def run(self) -> OnlyEngineRunResult:
        self._require_not_terminated("run")
        validation = self.validate()
        if not validation.valid:
            return OnlyEngineRunResult(
                self.config.engine_id,
                "",
                "FAILED",
                (),
                validation.errors or ("no Cluster configured",),
                None,
                "",
            )
        projections: list[dict[str, object]] = []
        backtest_results: list[OnlyBacktestResult] = []
        backtest_reports: list[dict[str, object]] = []
        console_reports: list[str] = []
        report_paths: list[Path] = []
        failures: list[str] = []
        executed: list[OnlyClusterRunConfig] = []
        try:
            self.initialize()
            self.start()
            if self._execution_plan is None:
                raise RuntimeError("Engine execution plan is unavailable")
            plans = {str(item.runtime_id): item for item in self._execution_plan.runtime_plans}
            for session in self.runtime_sessions:
                runtime_plan = plans[str(session.runtime_id)]
                try:
                    result = session.runtime.run()
                    if not hasattr(result, "to_dict"):
                        raise TypeError("Runtime.run() must return a serializable result")
                    typed_result = cast(OnlyRuntimeResult, result)
                    if isinstance(result, OnlyBacktestResult):
                        backtest_results.append(result)
                    projection = typed_result.to_dict()
                    for config in runtime_plan.cluster_configs:
                        projections.append(self._cluster_projection(projection, config.cluster_id))
                        executed.append(config)
                    if str(typed_result.status) in {"FAILED", "UNSUPPORTED"}:
                        failures.append(f"{runtime_plan.cluster_ids}: {typed_result.status}")
                except Exception as exc:
                    failures.append(f"{runtime_plan.cluster_ids}: {type(exc).__name__}: {exc}")
                    for config in runtime_plan.cluster_configs:
                        projections.append(
                            {"run": {"status": "FAILED", "cluster_ids": [str(config.cluster_id)]}, "error": str(exc)}
                        )
                        executed.append(config)
                        self._cluster_sessions[config.cluster_id].state = OnlyEngineClusterStatus.FAILED
                        self._handles[config.cluster_id] = replace(
                            self._handles[config.cluster_id], status=OnlyEngineClusterStatus.FAILED
                        )
                    if self.config.fail_fast:
                        break
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                self.stop()
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        for config in executed:
            if self._cluster_sessions.get(config.cluster_id) is not None:
                status = self._cluster_sessions[config.cluster_id].state
                if status is not OnlyEngineClusterStatus.FAILED:
                    self._cluster_sessions[config.cluster_id].state = OnlyEngineClusterStatus.STOPPED
                    self._handles[config.cluster_id] = replace(
                        self._handles[config.cluster_id], status=OnlyEngineClusterStatus.STOPPED
                    )
        if failures:
            self.state = OnlyEngineState.FAILED
        executed_tuple = tuple(executed)
        engine_fingerprint = self._engine_fingerprint(executed_tuple, tuple(projections))
        run_id = f"run-{uuid4().hex}"
        manifest = OnlyEngineResultExporter(OnlyUserDataLayout(self.config.user_data_root)).export(
            self.config.engine_id,
            run_id,
            executed_tuple,
            tuple(projections),
            engine_fingerprint,
            self._execution_plan,
        )
        for result in backtest_results:
            artifact_written = False
            try:
                analysis = OnlyBacktestAnalyticsService().analyze(result)
                artifact_root = (
                    manifest.path.parent
                    if len(backtest_results) == 1
                    else manifest.path.parent / "runtimes" / str(result.runtime_id) / "artifacts"
                )
                artifact_manifest = OnlyBacktestArtifactWriter().write(
                    result,
                    analysis,
                    OnlyRunArtifactTarget(artifact_root),
                )
                artifact_written = True
                backtest_reports.append(OnlyJsonBacktestReport().render(result, analysis, artifact_manifest))
                console_reports.append(OnlyConsoleBacktestReport().render(result, analysis, artifact_manifest))
                report_path = artifact_root / "report.md"
                report_temp = artifact_root / ".report.md.tmp"
                report_temp.write_text(
                    OnlyMarkdownBacktestReport().render(result, analysis, artifact_manifest),
                    encoding="utf-8",
                )
                report_temp.replace(report_path)
                report_paths.append(report_path)
            except Exception as exc:
                stage = "REPORT" if artifact_written else "ARTIFACT_WRITE"
                failures.append(f"{stage}: {type(exc).__name__}: {exc}")
        if failures:
            self.state = OnlyEngineState.FAILED
        return OnlyEngineRunResult(
            self.config.engine_id,
            run_id,
            "COMPLETED" if not failures else "FAILED",
            tuple(projections),
            tuple(failures),
            manifest.path,
            engine_fingerprint,
            tuple(backtest_reports),
            tuple(console_reports),
            tuple(report_paths),
        )

    def stop(self) -> None:
        if self.state is OnlyEngineState.STOPPED:
            return
        if not self._runtime_sessions:
            for cluster_id in reversed(tuple(self._cluster_definitions)):
                self._infrastructure.release(cluster_id)
            if self.storage is not None:
                self.storage.close()
            self.state = OnlyEngineState.STOPPED
            return
        self.state = OnlyEngineState.STOPPING
        for session in reversed(self.runtime_sessions):
            for cluster_id in reversed(session.bound_cluster_ids):
                session.runtime.stop_cluster(cluster_id)
                if self._cluster_sessions[cluster_id].state is not OnlyEngineClusterStatus.FAILED:
                    self._cluster_sessions[cluster_id].state = OnlyEngineClusterStatus.STOPPED
                    self._handles[cluster_id] = replace(
                        self._handles[cluster_id], status=OnlyEngineClusterStatus.STOPPED
                    )
            session.runtime.close()
            session.state = "STOPPED"
        for cluster_id in reversed(tuple(self._cluster_definitions)):
            self._infrastructure.release(cluster_id)
        if self.storage is not None:
            self.storage.close()
        self.state = OnlyEngineState.STOPPED

    def snapshot(self) -> OnlyEngineSnapshot:
        reference_counts = dict(self._infrastructure.reference_counts)
        plugin_resources = tuple(
            replace(
                snapshot,
                reference_count=reference_counts.get(
                    f"{'data_source' if snapshot.plugin_type == 'DATA_SOURCE' else 'broker'}:{snapshot.resource_id}",
                    snapshot.reference_count,
                ),
            )
            for session in self.runtime_sessions
            for snapshot in session.runtime.plugin_resource_snapshots
        )
        return OnlyEngineSnapshot(
            self.config.engine_id,
            self.state,
            self.cluster_handles,
            self._infrastructure.reference_counts,
            plugin_resources,
        )

    def _require_not_terminated(self, operation: str) -> None:
        if self.state in {OnlyEngineState.STOPPED, OnlyEngineState.FAILED}:
            raise OnlyLifecycleError(f"ENGINE_ALREADY_TERMINATED: cannot {operation}")

    def _require_services(self) -> OnlyEngineServices:
        if self._services is None:
            self._services = only_default_engine_services()
        return self._services

    @staticmethod
    def _plugin_descriptions(services: OnlyEngineServices) -> tuple[str, ...]:
        values = []
        for record in (*services.data_sources.records(), *services.brokers.records()):
            descriptor = record.descriptor
            values.append(
                f"{descriptor.plugin_type.value}:{descriptor.plugin_id}@{descriptor.plugin_version} "
                f"api={descriptor.api_version} origin={record.origin} capabilities={descriptor.capabilities}"
            )
        values.extend(
            f"FAILED:{item.group}:{item.name}:{item.code}:{item.message}" for item in services.plugin_discovery.failures
        )
        return tuple(sorted(values))

    def _unsupported_cluster_operation(self, cluster_id: OnlyClusterId, operation: str) -> OnlyClusterOperationResult:
        if cluster_id not in self._cluster_definitions:
            return OnlyClusterOperationResult(False, cluster_id, "CLUSTER_NOT_FOUND")
        return OnlyClusterOperationResult(False, cluster_id, f"{operation}_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE")

    @staticmethod
    def _validate_extension_types(config: OnlyClusterRunConfig) -> None:
        paths = [config.strategy.strategy_path, config.strategy.config_path]
        for factor in config.factors:
            paths.extend((factor.factor_path, factor.config_path))
        for path in paths:
            only_load_type(path)

    @staticmethod
    def _config_fingerprint(config: OnlyClusterRunConfig) -> str:
        payload = json.dumps(dict(config.normalized_payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _engine_fingerprint(
        configs: tuple[OnlyClusterRunConfig, ...], projections: tuple[dict[str, object], ...]
    ) -> str:
        payload = {
            "cluster_order": [str(item.cluster_id) for item in configs],
            "runtime_groups": [OnlyRuntimeCompatibilityKey.from_config(item) for item in configs],
            "results": [item.get("determinism_fingerprint", "") for item in projections],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    @staticmethod
    def _cluster_projection(projection: dict[str, object], cluster_id: OnlyClusterId) -> dict[str, object]:
        result = cast(dict[str, object], json.loads(json.dumps(projection)))
        cluster_value = str(cluster_id)
        run = result.get("run")
        if isinstance(run, dict):
            run["cluster_ids"] = [cluster_value]
        cluster_results = result.get("cluster_results")
        if isinstance(cluster_results, list):
            result["cluster_results"] = [
                item for item in cluster_results if isinstance(item, dict) and item.get("cluster_id") == cluster_value
            ]
        orders = result.get("orders")
        if isinstance(orders, list):
            result["orders"] = [item for item in orders if _nested_identifier(item, "cluster_id") == cluster_value]
        filtered_orders = result.get("orders", [])
        order_ids = (
            {_nested_identifier(item, "order_id") for item in filtered_orders}
            if isinstance(filtered_orders, list)
            else set()
        )
        trades = result.get("trades")
        if isinstance(trades, list):
            result["trades"] = [
                item
                for item in trades
                if isinstance(item, dict)
                and isinstance(item.get("fill"), dict)
                and _nested_identifier(item["fill"], "order_id") in order_ids
            ]
        filtered_trades = result.get("trades", [])
        if isinstance(filtered_orders, list) and isinstance(filtered_trades, list):
            result["execution"] = {
                "order_count": len(filtered_orders),
                "rejected_order_count": sum(
                    isinstance(item, dict) and item.get("status") == "REJECTED" for item in filtered_orders
                ),
                "trade_count": len(filtered_trades),
            }
        for key in ("final_allocations", "final_ledgers"):
            values = result.get(key)
            if isinstance(values, list):
                result[key] = [
                    item for item in values if _nested_identifier(item, "cluster_id", "key") == cluster_value
                ]
        return result


def _nested_identifier(value: object, field: str, parent: str | None = None) -> str | None:
    if not isinstance(value, dict):
        return None
    selected = value.get(parent) if parent is not None else value
    if not isinstance(selected, dict):
        return None
    identifier = selected.get(field)
    if isinstance(identifier, dict):
        raw = identifier.get("value")
        return raw if isinstance(raw, str) else None
    return identifier if isinstance(identifier, str) else None


__all__ = ["OnlyEngine", "OnlyEngineState"]
