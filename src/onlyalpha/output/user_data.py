"""Central user_data layout and Engine result exporter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId

if TYPE_CHECKING:
    from onlyalpha.runtime.planning import OnlyEngineExecutionPlan


@dataclass(frozen=True, slots=True)
class OnlyUserDataLayout:
    root: Path

    @property
    def historical_market_data_cache_root(self) -> Path:
        return self.root / "cache" / "market_data"

    def run_root(self, engine_id: OnlyEngineId, run_id: str) -> Path:
        return self.root / "runs" / str(engine_id) / run_id

    def cluster_root(self, engine_id: OnlyEngineId, run_id: str, cluster_id: OnlyClusterId) -> Path:
        return self.run_root(engine_id, run_id) / "clusters" / str(cluster_id)


@dataclass(frozen=True, slots=True)
class OnlyOutputManifest:
    path: Path
    files: tuple[str, ...]


class OnlyEngineResultExporter:
    def __init__(self, layout: OnlyUserDataLayout) -> None:
        self._layout = layout

    def export(
        self,
        engine_id: OnlyEngineId,
        run_id: str,
        configs: tuple[OnlyClusterRunConfig, ...],
        projections: tuple[dict[str, object], ...],
        engine_fingerprint: str,
        execution_plan: OnlyEngineExecutionPlan | None = None,
    ) -> OnlyOutputManifest:
        root = self._layout.run_root(engine_id, run_id)
        for directory in ("engine", "clusters", "runtimes", "shared", "logs"):
            (root / directory).mkdir(parents=True, exist_ok=False if directory == "engine" else True)
        files: list[Path] = []
        manifest_payload = {
            "schema_version": 1,
            "engine_id": str(engine_id),
            "run_id": run_id,
            "determinism_fingerprint": engine_fingerprint,
            "clusters": [
                {
                    "cluster_id": str(config.cluster_id),
                    "runtime_id": _planned_runtime_id(execution_plan, config),
                    "config_fingerprint": _config_fingerprint(config),
                }
                for config in configs
            ],
        }
        files.append(_write_json(root / "manifest.json", manifest_payload))
        files.append(_write_json(root / "engine/config.json", manifest_payload))
        files.append(_write_json(root / "engine/summary.json", {"cluster_results": list(projections)}))
        if execution_plan is not None:
            projections_by_cluster = {
                config.cluster_id: projection for config, projection in zip(configs, projections, strict=True)
            }
            for runtime_plan in execution_plan.runtime_plans:
                runtime_root = root / "runtimes" / str(runtime_plan.runtime_id)
                runtime_root.mkdir(parents=True, exist_ok=True)
                files.append(
                    _write_json(
                        runtime_root / "summary.json",
                        {
                            "runtime_id": str(runtime_plan.runtime_id),
                            "compatibility_key": {
                                field: str(getattr(runtime_plan.compatibility_key, field))
                                for field in runtime_plan.compatibility_key.__dataclass_fields__
                            },
                            "cluster_ids": [str(item) for item in runtime_plan.cluster_ids],
                        },
                    )
                )
                files.append(
                    _write_json(
                        runtime_root / "result.json",
                        {
                            "runtime_id": str(runtime_plan.runtime_id),
                            "cluster_results": [
                                projections_by_cluster[cluster_id]
                                for cluster_id in runtime_plan.cluster_ids
                                if cluster_id in projections_by_cluster
                            ],
                        },
                    )
                )
        for config, projection in zip(configs, projections, strict=True):
            cluster_root = self._layout.cluster_root(engine_id, run_id, config.cluster_id)
            for directory in ("strategy", "factors", "indicators", "orders", "portfolio"):
                (cluster_root / directory).mkdir(parents=True, exist_ok=True)
            files.append(_write_json(cluster_root / "normalized_config.json", dict(config.normalized_payload)))
            fingerprint_path = cluster_root / "fingerprint.txt"
            fingerprint_path.write_text(_config_fingerprint(config) + "\n", encoding="utf-8")
            files.append(fingerprint_path)
            if config.source_path.is_file():
                source = cluster_root / f"source_config{config.source_path.suffix.lower()}"
                copyfile(config.source_path, source)
                files.append(source)
            files.append(_write_json(cluster_root / "summary.json", projection))
            files.append(_write_json(cluster_root / "orders/orders.json", projection.get("orders", [])))
            files.append(
                _write_json(
                    cluster_root / "portfolio/snapshot.json",
                    {
                        key: projection.get(key, [])
                        for key in ("final_positions", "final_allocations", "final_ledgers", "final_accounts")
                    },
                )
            )
            report = cluster_root / "report.md"
            run_projection = projection.get("run", {})
            status = run_projection.get("status", "UNKNOWN") if isinstance(run_projection, dict) else "UNKNOWN"
            report.write_text(
                f"# Cluster {config.cluster_id}\n\n- Status: {status}\n",
                encoding="utf-8",
            )
            files.append(report)
        return OnlyOutputManifest(root / "manifest.json", tuple(str(item.relative_to(root)) for item in files))


def _config_fingerprint(config: OnlyClusterRunConfig) -> str:
    import hashlib

    payload = json.dumps(dict(config.normalized_payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _planned_runtime_id(execution_plan: OnlyEngineExecutionPlan | None, config: OnlyClusterRunConfig) -> str:
    if execution_plan is None:
        return str(config.runtime_id)
    for runtime_plan in execution_plan.runtime_plans:
        if config.cluster_id in runtime_plan.cluster_ids:
            return str(runtime_plan.runtime_id)
    return str(config.runtime_id)


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
