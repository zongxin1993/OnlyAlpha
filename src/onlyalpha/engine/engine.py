"""Product-level Cluster lifecycle and shared infrastructure coordinator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from onlyalpha.config import OnlyClusterRunConfig, OnlyRunConfig
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.engine.infrastructure import OnlyInfrastructureRegistry, OnlyRuntimeCompatibilityKey
from onlyalpha.engine.models import (
    OnlyClusterHandle,
    OnlyClusterLoadError,
    OnlyClusterOperationResult,
    OnlyClusterRemovalPolicy,
    OnlyClusterRemovalResult,
    OnlyEngineClusterStatus,
    OnlyEngineConfig,
    OnlyEngineRunResult,
    OnlyEngineSnapshot,
    OnlyEngineState,
    OnlyEngineValidationResult,
)
from onlyalpha.output import OnlyEngineResultExporter, OnlyUserDataLayout
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.runtime import OnlyRuntime
from onlyalpha.storage.base import OnlyStorage


class OnlyEngine:
    """The sole product entry; Runtime-specific behavior stays in factories."""

    def __init__(
        self,
        config: OnlyEngineConfig | str,
        storage: OnlyStorage | None = None,
        *,
        services: OnlyEngineServices | None = None,
    ) -> None:
        if isinstance(config, str):
            if not config.strip():
                raise ValueError("engine_id is required")
            self.config = OnlyEngineConfig(OnlyEngineId(config), Path.cwd() / "user_data")
            self._product_mode = False
        else:
            self.config = config
            self._product_mode = True
        self.engine_id = str(self.config.engine_id)
        self.storage = storage
        self.state = OnlyEngineState.CREATED
        self._services = services
        self._runtimes: dict[str, OnlyRuntime] = {}
        self._configs: dict[OnlyClusterId, OnlyClusterRunConfig] = {}
        self._handles: dict[OnlyClusterId, OnlyClusterHandle] = {}
        self._infrastructure = OnlyInfrastructureRegistry()
        self._runtime_groups: dict[OnlyRuntimeCompatibilityKey, list[OnlyClusterId]] = {}

    @property
    def runtimes(self) -> tuple[OnlyRuntime, ...]:
        return tuple(self._runtimes.values())

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
        if config.cluster_id in self._configs:
            raise OnlyDuplicateIdError(f"cluster already registered: {config.cluster_id}")
        previous = self.state
        self.state = OnlyEngineState.CONFIGURING
        acquired = False
        try:
            self._infrastructure.acquire(config)
            acquired = True
            build = self._require_services().assembler.build(config.for_engine(self.config.engine_id))
            if build.runtime is None:
                raise ValueError(f"{build.failure_code}: {build.failure_message}")
            build.runtime.close()
            fingerprint = self._config_fingerprint(config)
            handle = OnlyClusterHandle(
                config.cluster_id,
                config.runtime_id,
                OnlyEngineClusterStatus.LOADED,
                fingerprint,
            )
            self._configs[config.cluster_id] = config
            self._handles[config.cluster_id] = handle
            key = OnlyRuntimeCompatibilityKey.from_config(config)
            self._runtime_groups.setdefault(key, []).append(config.cluster_id)
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
        if cluster_id not in self._configs:
            return OnlyClusterRemovalResult(False, cluster_id, "CLUSTER_NOT_FOUND")
        if policy is not OnlyClusterRemovalPolicy.STOP_ONLY:
            return OnlyClusterRemovalResult(
                False,
                cluster_id,
                "CLUSTER_REMOVAL_POLICY_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE",
                message=policy.value,
            )
        if self.state is OnlyEngineState.RUNNING:
            return OnlyClusterRemovalResult(
                False,
                cluster_id,
                "DYNAMIC_CLUSTER_REMOVE_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE",
            )
        key = OnlyRuntimeCompatibilityKey.from_config(self._configs[cluster_id])
        group = self._runtime_groups[key]
        group.remove(cluster_id)
        if not group:
            del self._runtime_groups[key]
        released = self._infrastructure.release(cluster_id)
        del self._configs[cluster_id]
        del self._handles[cluster_id]
        if not self._configs:
            self.state = OnlyEngineState.CREATED
        return OnlyClusterRemovalResult(True, cluster_id, "REMOVED", released_resources=released)

    def start_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "START")

    def pause_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "PAUSE")

    def resume_cluster(self, cluster_id: OnlyClusterId) -> OnlyClusterOperationResult:
        return self._unsupported_cluster_operation(cluster_id, "RESUME")

    def validate(self) -> OnlyEngineValidationResult:
        errors: list[str] = []
        services = self._require_services()
        for cluster_ids in self._runtime_groups.values():
            configs = tuple(self._configs[cluster_id] for cluster_id in cluster_ids)
            build = services.assembler.build(self._merge_runtime_group(configs))
            if build.runtime is None:
                errors.append(f"{cluster_ids}: {build.failure_code}: {build.failure_message}")
            else:
                build.runtime.close()
        return OnlyEngineValidationResult(
            not errors and bool(self._configs),
            len(self._configs),
            len(self._runtime_groups),
            tuple(errors),
            self.config.user_data_root,
        )

    def run(self) -> OnlyEngineRunResult:
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
        self.state = OnlyEngineState.RUNNING
        projections: list[dict[str, object]] = []
        executed_configs: list[OnlyClusterRunConfig] = []
        failures: list[str] = []
        services = self._require_services()
        try:
            for cluster_ids in self._runtime_groups.values():
                group_configs = tuple(self._configs[cluster_id] for cluster_id in cluster_ids)
                try:
                    result = services.run_service.run(self._merge_runtime_group(group_configs), export=False)
                    projection = result.to_dict()
                    for config in group_configs:
                        projections.append(self._cluster_projection(projection, config.cluster_id))
                        executed_configs.append(config)
                        self._handles[config.cluster_id] = replace(
                            self._handles[config.cluster_id], status=OnlyEngineClusterStatus.STOPPED
                        )
                    if str(result.status) in {"FAILED", "UNSUPPORTED"}:
                        failures.append(f"{cluster_ids}: {result.status}")
                except Exception as exc:
                    failures.append(f"{cluster_ids}: {type(exc).__name__}: {exc}")
                    for config in group_configs:
                        projections.append(
                            {"run": {"status": "FAILED", "cluster_ids": [str(config.cluster_id)]}, "error": str(exc)}
                        )
                        executed_configs.append(config)
                        self._handles[config.cluster_id] = replace(
                            self._handles[config.cluster_id], status=OnlyEngineClusterStatus.FAILED
                        )
                    if self.config.fail_fast:
                        break
        finally:
            self.state = OnlyEngineState.STOPPED if not failures else OnlyEngineState.FAILED
        executed = tuple(executed_configs)
        engine_fingerprint = self._engine_fingerprint(executed, tuple(projections))
        run_id = f"run-{uuid4().hex}"
        manifest = OnlyEngineResultExporter(OnlyUserDataLayout(self.config.user_data_root)).export(
            self.config.engine_id,
            run_id,
            executed,
            tuple(projections),
            engine_fingerprint,
        )
        return OnlyEngineRunResult(
            self.config.engine_id,
            run_id,
            "COMPLETED" if not failures else "FAILED",
            tuple(projections),
            tuple(failures),
            manifest.path,
            engine_fingerprint,
        )

    def snapshot(self) -> OnlyEngineSnapshot:
        return OnlyEngineSnapshot(
            self.config.engine_id,
            self.state,
            self.cluster_handles,
            self._infrastructure.reference_counts,
        )

    def register_runtime(self, runtime: OnlyRuntime) -> None:
        """Legacy skeleton API; product callers register Cluster configs."""

        if self.state is not OnlyEngineState.CREATED:
            raise OnlyLifecycleError("runtimes must be registered before initialization")
        if runtime.runtime_id in self._runtimes:
            raise OnlyDuplicateIdError(f"runtime already registered: {runtime.runtime_id}")
        self._runtimes[runtime.runtime_id] = runtime

    def initialize(self) -> None:
        if self.state is not OnlyEngineState.CREATED:
            raise OnlyLifecycleError("engine can only initialize from CREATED")
        for runtime in self._runtimes.values():
            runtime.initialize()
        self.state = OnlyEngineState.READY

    def start(self) -> None:
        if self.state is not OnlyEngineState.READY:
            raise OnlyLifecycleError("engine can only start from READY")
        self.state = OnlyEngineState.RUNNING
        for runtime in self._runtimes.values():
            runtime.start()

    def stop(self) -> None:
        if self.state is OnlyEngineState.STOPPED:
            return
        self.state = OnlyEngineState.STOPPING
        for runtime in reversed(tuple(self._runtimes.values())):
            runtime.stop()
        if self.storage is not None:
            self.storage.close()
        self.state = OnlyEngineState.STOPPED

    def _require_services(self) -> OnlyEngineServices:
        if self._services is None:
            self._services = only_default_engine_services()
        return self._services

    def _unsupported_cluster_operation(self, cluster_id: OnlyClusterId, operation: str) -> OnlyClusterOperationResult:
        if cluster_id not in self._configs:
            return OnlyClusterOperationResult(False, cluster_id, "CLUSTER_NOT_FOUND")
        return OnlyClusterOperationResult(
            False,
            cluster_id,
            f"{operation}_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE",
        )

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

    def _merge_runtime_group(self, configs: tuple[OnlyClusterRunConfig, ...]) -> OnlyRunConfig:
        first = configs[0].for_engine(self.config.engine_id)
        group_key = OnlyRuntimeCompatibilityKey.from_config(configs[0])
        group_fingerprint = hashlib.sha256(str(group_key).encode()).hexdigest()[:16]
        return replace(
            first,
            runtime=replace(
                first.runtime, runtime_id=OnlyRuntimeId(f"{first.runtime.runtime_type.lower()}-{group_fingerprint}")
            ),
            clusters=tuple(config.run_config.clusters[0] for config in configs),
        )

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
