"""Kernel-internal Cluster, Runtime session, and infrastructure coordinator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import uuid4

from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.artifact import OnlyBacktestArtifactWriter, OnlyRunArtifactTarget
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.engine.composition import OnlyClusterComposition
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
from onlyalpha.factor.factory import only_load_factor_type
from onlyalpha.market.product import OnlyResolvedMarketProductBinding
from onlyalpha.output import OnlyEngineResultExporter, OnlyUserDataLayout
from onlyalpha.report import OnlyConsoleBacktestReport, OnlyJsonBacktestReport, OnlyMarkdownBacktestReport
from onlyalpha.runtime.backtest.result import OnlyBacktestResult
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder
from onlyalpha.runtime.planning import (
    OnlyEngineExecutionPlan,
    OnlyRuntimePlanner,
)
from onlyalpha.runtime.product import (
    OnlyFiniteRuntime,
    OnlyPluginResourceSnapshotRuntime,
    OnlyRuntimeProduct,
)
from onlyalpha.runtime.research import (
    OnlyResearchRuntime,
    OnlyResearchRuntimeExecutionControl,
    OnlyResearchRuntimePlan,
    OnlyResearchWorkloadPlan,
    only_research_runtime_plan,
)
from onlyalpha.runtime.result import OnlyRuntimeResult
from onlyalpha.runtime.runtime import OnlyRuntime
from onlyalpha.storage.base import OnlyStorage


class OnlyEngine:
    """Own internal Cluster, Runtime, and infrastructure composition lifecycle."""

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
        self._research_plans: dict[str, OnlyResearchRuntimePlan] = {}
        self._handles: dict[OnlyClusterId, OnlyClusterHandle] = {}
        self._infrastructure = OnlyInfrastructureRegistry()
        self._environment_builder = OnlyRuntimeEnvironmentBuilder()
        self._planner = OnlyRuntimePlanner(self._environment_builder)
        self._execution_plan: OnlyEngineExecutionPlan | None = None
        self._market_products: dict[OnlyClusterId, OnlyResolvedMarketProductBinding] = {}
        self._stop_attempted = False

    @property
    def runtimes(self) -> tuple[OnlyRuntimeProduct, ...]:
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

    def add_cluster(self, config: OnlyClusterRunConfig) -> OnlyClusterHandle:
        if self.state is OnlyEngineState.RUNNING:
            raise OnlyClusterLoadError("DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE")
        if self.state not in {OnlyEngineState.CREATED, OnlyEngineState.CONFIGURING, OnlyEngineState.READY}:
            raise OnlyLifecycleError(f"cannot add Cluster while Engine is {self.state}")
        if config.cluster_id in self._cluster_definitions:
            raise OnlyDuplicateIdError(f"cluster already registered: {config.cluster_id}")
        previous = self.state
        self.state = OnlyEngineState.CONFIGURING
        try:
            services = self._require_services()
            self._validate_extension_types(config)
            composition = OnlyClusterComposition(
                self._infrastructure,
                services.assembler.components,
                self._environment_builder,
                services.market_product_resources,
            )
            plan = composition.plan(config)
            fingerprint = self._config_fingerprint(config)
            handle = OnlyClusterHandle(
                config.cluster_id,
                config.runtime_id,
                OnlyEngineClusterStatus.LOADED,
                fingerprint,
            )
            resources = composition.commit(plan)
            self._cluster_definitions[config.cluster_id] = config
            self._market_products[config.cluster_id] = plan.market_product
            self._handles[config.cluster_id] = handle
            if resources != self._infrastructure.references_for(config.cluster_id):
                raise RuntimeError("infrastructure references were not registered atomically")
            self.state = OnlyEngineState.READY
            return handle
        except Exception:
            self.state = previous
            raise

    def add_research_workload(self, workload: OnlyResearchWorkloadPlan) -> OnlyRuntimeId:
        if self.state not in {OnlyEngineState.CREATED, OnlyEngineState.CONFIGURING, OnlyEngineState.READY}:
            raise OnlyLifecycleError(f"cannot add Research workload while Engine is {self.state}")
        if not isinstance(workload, OnlyResearchWorkloadPlan):
            raise TypeError("workload must be OnlyResearchWorkloadPlan")
        plan = only_research_runtime_plan(workload)
        key = str(plan.runtime_id)
        if key in self._research_plans:
            raise OnlyDuplicateIdError(f"Research Runtime already registered: {plan.runtime_id}")
        self._research_plans[key] = plan
        self.state = OnlyEngineState.READY
        return plan.runtime_id

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
        del self._market_products[cluster_id]
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
        if self._research_plans and self._cluster_definitions:
            errors.append("MIXED_RESEARCH_TRADING_NOT_SUPPORTED")
        plan = self._planner.plan(self.config.engine_id, self.cluster_definitions, self._market_products)
        services = self._require_services()
        for runtime_plan in plan.runtime_plans:
            validation = services.assembler.validate(runtime_plan, self.config.user_data_root)
            if validation.failure_code is not None:
                errors.append(f"{runtime_plan.cluster_ids}: {validation.failure_code}: {validation.failure_message}")
        for research_plan in self._research_plans.values():
            validation = services.assembler.validate(research_plan, self.config.user_data_root)
            if validation.failure_code is not None:
                errors.append(f"{research_plan.runtime_id}: {validation.failure_code}: {validation.failure_message}")
        return OnlyEngineValidationResult(
            not errors and bool(self._cluster_definitions or self._research_plans),
            len(self._cluster_definitions),
            len(plan.runtime_plans) + len(self._research_plans),
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
        if self._runtime_sessions:
            if self.state is OnlyEngineState.READY:
                return
            raise OnlyLifecycleError("Engine sessions are already initialized")
        if self.state not in {OnlyEngineState.CREATED, OnlyEngineState.READY}:
            raise OnlyLifecycleError(f"cannot initialize Engine while {self.state}")
        if not self._cluster_definitions and not self._research_plans:
            raise OnlyLifecycleError("Engine requires at least one Runtime product definition")
        validation = self.validate()
        if not validation.valid:
            raise OnlyLifecycleError("; ".join(validation.errors))
        plan = self._planner.plan(self.config.engine_id, self.cluster_definitions, self._market_products)
        created: list[OnlyRuntimeProduct] = []
        try:
            for runtime_plan in plan.runtime_plans:
                build = self._require_services().assembler.build(runtime_plan, self.config.user_data_root)
                if build.runtime is None:
                    raise RuntimeError(f"{build.failure_code}: {build.failure_message}")
                runtime = cast(OnlyRuntime, build.runtime)
                created.append(runtime)
                runtime.initialize()
                runtime_session = OnlyRuntimeSession(
                    runtime_plan.runtime_id,
                    runtime,
                    runtime_plan.environment,
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
            for research_plan in self._research_plans.values():
                build = self._require_services().assembler.build(research_plan, self.config.user_data_root)
                if build.runtime is None:
                    raise RuntimeError(f"{build.failure_code}: {build.failure_message}")
                research_runtime = build.runtime
                created.append(research_runtime)
                research_runtime.initialize()
                self._runtime_sessions[str(research_plan.runtime_id)] = OnlyRuntimeSession(
                    research_plan.runtime_id,
                    research_runtime,
                    research_plan.environment,
                    (),
                    "READY",
                )
            self._execution_plan = plan
            self.state = OnlyEngineState.READY
        except Exception as failure:
            for created_runtime in reversed(created):
                try:
                    created_runtime.close()
                except Exception as cleanup_failure:
                    failure.add_note(
                        f"Runtime initialization cleanup also failed: "
                        f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                    )
            self._runtime_sessions.clear()
            self._cluster_sessions.clear()
            self._execution_plan = None
            for cluster_id in reversed(tuple(self._cluster_definitions)):
                try:
                    self._infrastructure.release(cluster_id)
                except Exception as cleanup_failure:
                    failure.add_note(
                        f"Infrastructure initialization cleanup also failed: "
                        f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                    )
            self.state = OnlyEngineState.FAILED
            raise

    def start(self) -> None:
        if self.state is not OnlyEngineState.READY:
            raise OnlyLifecycleError("engine can only start from READY")
        try:
            for session in self.runtime_sessions:
                session.runtime.start()
                session.state = "RUNNING"
                for cluster_id in session.bound_cluster_ids:
                    self._cluster_sessions[cluster_id].state = OnlyEngineClusterStatus.RUNNING
                    self._handles[cluster_id] = replace(
                        self._handles[cluster_id], status=OnlyEngineClusterStatus.RUNNING
                    )
        except BaseException as failure:
            self._converge_failed_start(failure)
            raise
        self.state = OnlyEngineState.RUNNING

    def _converge_failed_start(self, failure: BaseException) -> None:
        """Close the entire initialized world while preserving the startup failure."""

        self._stop_attempted = True
        for session in reversed(self.runtime_sessions):
            try:
                session.runtime.close()
            except BaseException as cleanup_failure:
                failure.add_note(
                    f"Runtime startup cleanup also failed for {session.runtime_id}: "
                    f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                )
            session.state = "FAILED"
            for cluster_id in reversed(session.bound_cluster_ids):
                self._cluster_sessions[cluster_id].state = OnlyEngineClusterStatus.FAILED
                self._handles[cluster_id] = replace(self._handles[cluster_id], status=OnlyEngineClusterStatus.FAILED)
        for cluster_id in reversed(tuple(self._cluster_definitions)):
            try:
                self._infrastructure.release(cluster_id)
            except BaseException as cleanup_failure:
                failure.add_note(
                    f"Infrastructure startup cleanup also failed for {cluster_id}: "
                    f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                )
        if self.storage is not None:
            try:
                self.storage.close()
            except BaseException as cleanup_failure:
                failure.add_note(
                    f"Storage startup cleanup also failed: {type(cleanup_failure).__name__}: {cleanup_failure}"
                )
        self.state = OnlyEngineState.FAILED

    def wait(self, timeout: float | None = None) -> None:
        """Wait for all long-lived Runtime sessions through the sole product entry."""

        if self.state is not OnlyEngineState.RUNNING:
            raise OnlyLifecycleError("engine can only wait while RUNNING")
        budget = None if timeout is None else max(0.0, timeout)
        deadline = None if budget is None else monotonic() + budget
        for session in self.runtime_sessions:
            wait = getattr(session.runtime, "wait", None)
            if not callable(wait):
                raise OnlyLifecycleError(f"{session.runtime.runtime_type} Runtime is finite and cannot wait")
            remaining = None if deadline is None or budget is None else min(budget, max(0.0, deadline - monotonic()))
            wait(remaining)

    def run_runtime(
        self,
        runtime_id: OnlyRuntimeId | str,
        *,
        research_control: OnlyResearchRuntimeExecutionControl | None = None,
    ) -> OnlyRuntimeResult:
        if self.state is not OnlyEngineState.RUNNING:
            raise OnlyLifecycleError("engine can only run a finite Runtime while RUNNING")
        try:
            session = self._runtime_sessions[str(runtime_id)]
        except KeyError as exc:
            raise OnlyLifecycleError(f"RUNTIME_NOT_FOUND: {runtime_id}") from exc
        if not isinstance(session.runtime, OnlyFiniteRuntime):
            raise OnlyLifecycleError(f"RUNTIME_NOT_FINITE: {runtime_id}")
        if research_control is None:
            result = session.runtime.run()
        elif isinstance(session.runtime, OnlyResearchRuntime):
            result = session.runtime.run(research_control)
        else:
            raise OnlyLifecycleError("EXECUTION_CONTROL_REQUIRES_RESEARCH_RUNTIME")
        session.state = "FAILED" if str(result.status) == "FAILED" else "COMPLETED"
        return result

    def run(self) -> OnlyEngineRunResult:
        self._require_not_terminated("run")
        runtime_types = {config.runtime.runtime_type for config in self.cluster_definitions}
        if runtime_types != {"BACKTEST"}:
            raise OnlyLifecycleError("OnlyEngine.run() is restricted to finite BACKTEST execution")
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
                    if not isinstance(session.runtime, OnlyFiniteRuntime):
                        raise OnlyLifecycleError("BACKTEST Runtime must expose finite execution")
                    result = session.runtime.run()
                    if not hasattr(result, "to_dict"):
                        raise TypeError("Runtime.run() must return a serializable result")
                    typed_result = result
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
            tuple(backtest_results),
        )

    def stop(self) -> None:
        if self._stop_attempted:
            return
        self._stop_attempted = True
        self.state = OnlyEngineState.STOPPING
        failure: BaseException | None = None
        for session in reversed(self.runtime_sessions):
            try:
                session.runtime.close()
            except BaseException as exc:
                failure = failure or exc
                session.state = "FAILED"
            else:
                session.state = "STOPPED"
            for cluster_id in reversed(session.bound_cluster_ids):
                if self._cluster_sessions[cluster_id].state is not OnlyEngineClusterStatus.FAILED:
                    self._cluster_sessions[cluster_id].state = OnlyEngineClusterStatus.STOPPED
                    self._handles[cluster_id] = replace(
                        self._handles[cluster_id], status=OnlyEngineClusterStatus.STOPPED
                    )
        for cluster_id in reversed(tuple(self._cluster_definitions)):
            try:
                self._infrastructure.release(cluster_id)
            except BaseException as exc:
                failure = failure or exc
        if self.storage is not None:
            try:
                self.storage.close()
            except BaseException as exc:
                failure = failure or exc
        self.state = OnlyEngineState.FAILED if failure is not None else OnlyEngineState.STOPPED
        if failure is not None:
            raise failure

    def close(self) -> None:
        """Idempotently close all Engine-owned resources after an operational run."""

        self.stop()

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
            if isinstance(session.runtime, OnlyPluginResourceSnapshotRuntime)
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
        components = services.assembler.components
        for record in (*components.data_sources.records(), *components.brokers.records()):
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
        paths: list[str] = []
        for factor in config.factors:
            paths.extend((factor.factor_path, factor.config_path))
        for path in paths:
            only_load_factor_type(path)

    @staticmethod
    def _config_fingerprint(config: OnlyClusterRunConfig) -> str:
        payload = json.dumps(dict(config.normalized_payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _engine_fingerprint(
        configs: tuple[OnlyClusterRunConfig, ...], projections: tuple[dict[str, object], ...]
    ) -> str:
        payload = {
            "clusters": [str(item.cluster_id) for item in sorted(configs, key=lambda item: str(item.cluster_id))],
            "market_products": [item.market for item in sorted(configs, key=lambda item: str(item.cluster_id))],
            "results": sorted(str(item.get("determinism_fingerprint", "")) for item in projections),
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
        trades = result.get("trades")
        if isinstance(trades, list):
            result["trades"] = [
                item
                for item in trades
                if isinstance(item, dict) and _nested_identifier(item, "cluster_id") == cluster_value
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
