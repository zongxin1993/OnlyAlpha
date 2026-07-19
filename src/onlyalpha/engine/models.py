"""Typed Engine configuration, handles, lifecycle results and snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId

if TYPE_CHECKING:
    from onlyalpha.cluster.base import OnlyCluster
    from onlyalpha.runtime.planning import OnlyRuntimeCompatibilityKey
    from onlyalpha.runtime.runtime import OnlyRuntime


class OnlyClusterLoadError(Exception):
    """Structured transactional Cluster load failure."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


class OnlyEngineState(StrEnum):
    CREATED = "CREATED"
    CONFIGURING = "CONFIGURING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OnlyEngineClusterStatus(StrEnum):
    LOADED = "LOADED"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OnlyClusterRemovalPolicy(StrEnum):
    STOP_ONLY = "STOP_ONLY"
    CANCEL_OPEN_ORDERS = "CANCEL_OPEN_ORDERS"
    CANCEL_AND_WAIT = "CANCEL_AND_WAIT"
    FAIL_IF_OPEN_ORDERS = "FAIL_IF_OPEN_ORDERS"
    KEEP_EXTERNAL_ORDERS = "KEEP_EXTERNAL_ORDERS"


@dataclass(frozen=True, slots=True)
class OnlyEngineConfig:
    engine_id: OnlyEngineId
    user_data_root: Path
    fail_fast: bool = True
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_data_root", self.user_data_root.expanduser().resolve())


@dataclass(frozen=True, slots=True)
class OnlyClusterHandle:
    cluster_id: OnlyClusterId
    runtime_id: OnlyRuntimeId
    status: OnlyEngineClusterStatus
    config_fingerprint: str


@dataclass(slots=True)
class OnlyClusterSession:
    cluster_id: OnlyClusterId
    cluster: OnlyCluster
    runtime_id: OnlyRuntimeId
    state: OnlyEngineClusterStatus
    resource_references: tuple[str, ...]
    configuration_fingerprint: str


@dataclass(slots=True)
class OnlyRuntimeSession:
    runtime_id: OnlyRuntimeId
    runtime: OnlyRuntime
    compatibility_key: OnlyRuntimeCompatibilityKey
    bound_cluster_ids: tuple[OnlyClusterId, ...]
    state: str


@dataclass(frozen=True, slots=True)
class OnlyClusterOperationResult:
    success: bool
    cluster_id: OnlyClusterId
    code: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class OnlyClusterRemovalResult(OnlyClusterOperationResult):
    released_resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyEngineValidationResult:
    valid: bool
    cluster_count: int
    runtime_group_count: int
    errors: tuple[str, ...]
    output_root: Path
    plugins: tuple[str, ...] = ()
    plugin_bindings: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.valid else 2

    def render(self) -> str:
        lines = [
            f"valid={str(self.valid).lower()}",
            f"clusters={self.cluster_count}",
            f"runtime_groups={self.runtime_group_count}",
            f"output_root={self.output_root}",
        ]
        lines.extend(f"error={item}" for item in self.errors)
        lines.extend(f"plugin={item}" for item in self.plugins)
        lines.extend(f"binding={item}" for item in self.plugin_bindings)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class OnlyEngineRunResult:
    engine_id: OnlyEngineId
    run_id: str
    status: str
    cluster_results: tuple[dict[str, object], ...]
    failures: tuple[str, ...]
    manifest_path: Path | None
    determinism_fingerprint: str
    backtest_reports: tuple[dict[str, object], ...] = ()
    console_reports: tuple[str, ...] = ()
    report_paths: tuple[Path, ...] = ()
    runtime_results: tuple[object, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "COMPLETED" else 2

    def to_dict(self) -> dict[str, object]:
        return {
            "engine_id": str(self.engine_id),
            "run_id": self.run_id,
            "status": self.status,
            "cluster_results": list(self.cluster_results),
            "failures": list(self.failures),
            "manifest_path": None if self.manifest_path is None else str(self.manifest_path),
            "determinism_fingerprint": self.determinism_fingerprint,
            "backtest_reports": list(self.backtest_reports),
            "report_paths": [str(item) for item in self.report_paths],
        }


@dataclass(frozen=True, slots=True)
class OnlyEngineSnapshot:
    engine_id: OnlyEngineId
    state: OnlyEngineState
    clusters: tuple[OnlyClusterHandle, ...]
    resource_reference_counts: tuple[tuple[str, int], ...]
    plugin_resources: tuple[object, ...] = ()
