"""Standard runtime result layout; Runtime objects never write files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile

from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.result import OnlyRuntimeResult


@dataclass(frozen=True, slots=True)
class OnlyRuntimeOutputLayout:
    root: Path
    engine_id: str
    runtime_id: str
    run_id: str

    @property
    def run_directory(self) -> Path:
        return self.root / self.engine_id / self.runtime_id / self.run_id


@dataclass(frozen=True, slots=True)
class OnlyRuntimeOutputManifest:
    layout: OnlyRuntimeOutputLayout
    files: tuple[str, ...]


class OnlyRuntimeResultExporter:
    def export(self, config: OnlyRunConfig, result: OnlyRuntimeResult) -> OnlyRuntimeOutputManifest:
        projection = result.to_dict()
        normalized = dict(config.normalized_payload)
        config_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        config_fingerprint = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        fingerprint = result.determinism_fingerprint or config_fingerprint
        layout = OnlyRuntimeOutputLayout(
            Path(config.output.root_directory),
            str(config.engine_id),
            str(config.runtime_id),
            f"run-{fingerprint[:16]}",
        )
        root = layout.run_directory
        if root.exists() and not config.output.overwrite:
            raise FileExistsError(f"output already exists: {root}")
        directories = (
            "config",
            "runtime",
            "market_data",
            "execution",
            "portfolio",
            "strategies",
            "reports",
            "logs",
        )
        for name in directories:
            (root / name).mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        files.append(self._json(root / "config/normalized.json", normalized))
        if config.source_path.is_file():
            source = root / f"config/source{config.source_path.suffix.lower()}"
            copyfile(config.source_path, source)
            files.append(source)
        fingerprint_file = root / "config/fingerprint.txt"
        fingerprint_file.write_text(config_fingerprint + "\n", encoding="utf-8")
        files.append(fingerprint_file)
        files.append(self._json(root / "runtime/summary.json", projection.get("run", projection)))
        files.append(self._json(root / "runtime/snapshot.json", self._snapshot_projection(projection)))
        files.append(self._json(root / "runtime/health.json", {"status": str(result.status)}))
        files.append(self._json(root / "market_data/summary.json", projection.get("data", {})))
        files.append(
            self._json(
                root / "market_data/quality.json",
                {"quality_flags": self._mapping(projection.get("data", {})).get("quality_flags", [])},
            )
        )
        files.append(self._json(root / "execution/orders.json", projection.get("orders", [])))
        files.append(self._json(root / "execution/trades.json", projection.get("trades", [])))
        files.append(self._json(root / "execution/audit.json", projection.get("execution", {})))
        for name, key in (
            ("positions", "final_positions"),
            ("allocations", "final_allocations"),
            ("ledgers", "final_ledgers"),
            ("accounts", "final_accounts"),
        ):
            files.append(self._json(root / f"portfolio/{name}.json", projection.get(key, [])))
        run = self._mapping(projection.get("run", {}))
        cluster_ids = run.get("cluster_ids", [])
        for cluster_id in cluster_ids if isinstance(cluster_ids, list) else []:
            strategy_root = root / "strategies" / str(cluster_id)
            strategy_root.mkdir(parents=True, exist_ok=True)
            files.append(self._json(strategy_root / "summary.json", {"cluster_id": cluster_id}))
            files.append(self._json(strategy_root / "extensions.json", {"signals": projection.get("signals", [])}))
        report = root / "reports/run_report.md"
        report.write_text(self._report(result, projection), encoding="utf-8")
        files.append(report)
        return OnlyRuntimeOutputManifest(layout, tuple(str(path.relative_to(root)) for path in files))

    @staticmethod
    def _json(path: Path, payload: object) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _snapshot_projection(projection: dict[str, object]) -> dict[str, object]:
        return {
            key: projection.get(key, [])
            for key in ("final_positions", "final_allocations", "final_ledgers", "final_accounts")
        }

    @staticmethod
    def _report(result: OnlyRuntimeResult, projection: dict[str, object]) -> str:
        return "\n".join(
            (
                "# OnlyAlpha Runtime Run",
                "",
                f"- Runtime: {result.runtime_id}",
                f"- Type: {result.runtime_type}",
                f"- Status: {result.status}",
                f"- Fingerprint: `{result.determinism_fingerprint}`",
                f"- Invariants: {projection.get('invariant_results', [])}",
                "",
            )
        )
