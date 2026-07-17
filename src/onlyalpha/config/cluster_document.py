"""Single-Cluster product configuration document.

The established ``OnlyRunConfig`` remains the runtime assembly DTO.  This
module is the product-facing adapter and deliberately rejects the legacy
multi-Cluster document shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from onlyalpha.config.document import OnlyOutputConfig, OnlyRunConfig, OnlyRunConfigError
from onlyalpha.config.models import OnlyJsonMapping, _load_document, _normalize_mapping
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId


@dataclass(frozen=True, slots=True)
class OnlyClusterRunConfig:
    """Validated product document defining exactly one Cluster."""

    run_config: OnlyRunConfig

    @property
    def cluster_id(self) -> OnlyClusterId:
        return self.run_config.clusters[0].cluster_id

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.run_config.runtime_id

    @property
    def runtime_type(self) -> str:
        return self.run_config.runtime.runtime_type

    @property
    def source_path(self) -> Path:
        return self.run_config.source_path

    @property
    def normalized_payload(self) -> OnlyJsonMapping:
        return self.run_config.normalized_payload

    @classmethod
    def load(cls, path: str | Path) -> OnlyClusterRunConfig:
        source = Path(path).expanduser().resolve()
        return cls._parse(_load_document(source), source)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        source_path: str | Path = "<mapping>",
    ) -> OnlyClusterRunConfig:
        normalized = _normalize_mapping(cast(Mapping[object, object], payload), "$")
        return cls._parse(normalized, Path(source_path))

    @classmethod
    def _parse(cls, root: OnlyJsonMapping, source: Path) -> OnlyClusterRunConfig:
        if "clusters" in root:
            raise OnlyRunConfigError("single-Cluster documents must use 'cluster', not 'clusters'")
        common = root.get("cluster")
        if not isinstance(common, Mapping):
            raise OnlyRunConfigError("$.cluster must be a mapping")
        cluster_id = common.get("cluster_id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            raise OnlyRunConfigError("$.cluster.cluster_id must be a non-empty string")
        runtime = root.get("runtime")
        if not isinstance(runtime, Mapping):
            raise OnlyRunConfigError("$.runtime must be a mapping")
        strategy = root.get("strategy")
        if not isinstance(strategy, Mapping):
            raise OnlyRunConfigError("$.strategy must be a mapping")
        factors = root.get("factors", [])
        if not isinstance(factors, list):
            raise OnlyRunConfigError("$.factors must be a list")

        runtime_payload = dict(runtime)
        runtime_payload["runtime_id"] = str(runtime_payload.get("runtime_id", f"{cluster_id}-runtime"))
        runtime_payload["type"] = str(common.get("runtime_type", runtime_payload.get("type", "BACKTEST")))
        cluster_payload = dict(common)
        cluster_payload.pop("runtime_type", None)
        cluster_payload["strategy"] = dict(strategy)
        cluster_payload["factors"] = factors
        output = root.get("output", {})
        if not isinstance(output, Mapping):
            raise OnlyRunConfigError("$.output must be a mapping")
        output_payload = dict(output)
        output_payload.pop("enabled", None)
        legacy: dict[str, object] = {
            "schema_version": root.get("schema_version", "1.0"),
            "engine": {"engine_id": "onlyalpha"},
            "runtime": runtime_payload,
            "reference_data": root.get("reference_data"),
            "universes": root.get("universes", []),
            "data_sources": root.get("data_sources"),
            "accounts": root.get("accounts"),
            "brokers": root.get("brokers"),
            "clusters": [cluster_payload],
            "output": output_payload,
        }
        parsed = OnlyRunConfig.from_mapping(legacy, source_path=source)
        if len(parsed.clusters) != 1:
            raise OnlyRunConfigError("a product config must define exactly one Cluster")
        normalized = _normalize_mapping(cast(Mapping[object, object], root), "$")
        return cls(replace(parsed, normalized_payload=normalized))

    def for_engine(self, engine_id: OnlyEngineId) -> OnlyRunConfig:
        """Return the internal Runtime assembly DTO bound to an Engine."""

        return replace(
            self.run_config,
            runtime=replace(self.run_config.runtime, engine_id=engine_id),
            output=OnlyOutputConfig(overwrite=True),
        )
