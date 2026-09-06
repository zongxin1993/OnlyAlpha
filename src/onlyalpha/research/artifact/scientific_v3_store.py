"""Atomic immutable self-contained Scientific Research Artifact V3 store."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.evaluation.summary.result import only_research_summary_from_dict

from .errors import OnlyResearchArtifactStoreError
from .model import OnlyResearchArtifactDisposition, OnlyResearchArtifactOutcome
from .scientific_model import (
    OnlyResearchScientificGraph,
    OnlyResearchScientificMarketRow,
    OnlyResearchScientificSection,
    OnlyResearchScientificSignalRow,
)
from .scientific_store import (
    _MARKET,
    _SIGNALS,
    _STATISTICS,
    _VARIABLES,
    _schema_payload,
    _sha,
    _variable,
    _variable_key,
    _verify_logical_keys,
    _verify_series_axes,
    _verify_variable_scalars,
    _verify_variable_types,
)
from .scientific_v3_materializer import OnlyResearchScientificArtifactCandidateV3
from .scientific_v3_model import (
    RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS,
    OnlyResearchScientificArtifactManifestV3,
    OnlyResearchScientificArtifactV3,
    OnlyResearchScientificStatisticsSeriesRowV3,
    OnlyResearchScientificStatisticsSummaryV3,
    only_research_scientific_artifact_v3_content_fingerprint,
    only_research_scientific_catalog_entry_v3_from_dict,
    only_research_scientific_v3_section_fingerprint,
)
from .scientific_v3_verification import verify_scientific_artifact_v3_statistics

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlyParquetResearchScientificArtifactStoreV3:
    def __init__(
        self,
        root: Path,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._compression = compression
        self._row_group_size = row_group_size
        self._audit_time = audit_time

    def exists(self, fingerprint: str) -> bool:
        return self._target(fingerprint).exists()

    def commit(self, candidate: OnlyResearchScientificArtifactCandidateV3) -> OnlyResearchArtifactOutcome:
        admitted, tables = self._admit(candidate)
        identity = admitted.result.manifest.research_result_fingerprint
        target = self._target(identity)
        if target.exists():
            return self._reuse_existing(admitted, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            for path in ("market.parquet", "signals.parquet", "statistics_series.parquet", "variables.parquet"):
                pq.write_table(
                    tables[path],
                    stage / path,
                    compression=self._compression,
                    row_group_size=self._row_group_size,
                )
            (stage / "graphs.json").write_text(
                only_canonical_json([x.to_dict() for x in admitted.graphs]), encoding="utf-8"
            )
            (stage / "statistics_catalog.json").write_text(
                only_canonical_json([x.to_dict() for x in admitted.statistics_catalog]), encoding="utf-8"
            )
            (stage / "statistics_summaries.json").write_text(
                only_canonical_json([x.to_dict() for x in admitted.statistics_summaries]), encoding="utf-8"
            )
            logical = {x.relative_path: x for x in admitted.sections}
            sections = tuple(
                OnlyResearchScientificSection(
                    path,
                    logical[path].row_count,
                    logical[path].logical_fingerprint,
                    _sha(stage / path),
                    _schema_payload(tables[path].schema) if path.endswith(".parquet") else None,
                )
                for path in RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS
            )
            source = admitted.result.manifest
            manifest = OnlyResearchScientificArtifactManifestV3(
                source.plan,
                source.research_result_plan_fingerprint,
                source.research_result_content_fingerprint,
                source.research_result_fingerprint,
                source.dataset_snapshot_fingerprint,
                source.calculation_results,
                source.statistics_results,
                sections,
                admitted.artifact_content_fingerprint,
                self._audit_timestamp(),
            )
            (stage / "artifact_manifest.json").write_text(only_canonical_json(manifest.to_dict()), encoding="utf-8")
            try:
                self._read_verified(stage, identity)
            except OnlyResearchArtifactStoreError as exc:
                raise OnlyResearchArtifactStoreError(
                    "ARTIFACT_COMMIT_FAILED", "staged Scientific Artifact V3 verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                return self._reuse_existing(admitted, target)
            loaded = self.load_verified(identity)
            return OnlyResearchArtifactOutcome(
                OnlyResearchArtifactDisposition.EXECUTED,
                identity,
                loaded.manifest.artifact_content_fingerprint,
            )
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", str(exc)) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchScientificArtifactV3:
        return self._read_verified(self._target(research_result_fingerprint), research_result_fingerprint)

    def _admit(
        self, candidate: OnlyResearchScientificArtifactCandidateV3
    ) -> tuple[OnlyResearchScientificArtifactCandidateV3, dict[str, pa.Table]]:
        if not isinstance(candidate, OnlyResearchScientificArtifactCandidateV3):
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", "Scientific V3 candidate is invalid")
        try:
            source = candidate.result.manifest
            if source.schema_version != 2 or source.plan.schema_version != 2:
                raise ValueError("Scientific Artifact V3 requires Research Result V2")
            if candidate.market_rows != tuple(sorted(candidate.market_rows)):
                raise ValueError("Scientific V3 market rows are not canonical")
            if candidate.variable_rows != tuple(sorted(candidate.variable_rows, key=_variable_key)):
                raise ValueError("Scientific V3 variable rows are not canonical")
            for values in (
                candidate.signal_rows,
                candidate.graphs,
                candidate.statistics_series_rows,
                candidate.statistics_summaries,
            ):
                if values != tuple(sorted(values)):
                    raise ValueError("Scientific V3 rows are not canonical")
            _verify_logical_keys(candidate.market_rows, candidate.variable_rows, candidate.signal_rows)
            _verify_variable_scalars(candidate.variable_rows)
            _verify_variable_types(candidate.graphs, candidate.variable_rows)
            _verify_series_axes(source.plan, candidate.market_rows, candidate.variable_rows, candidate.signal_rows)
            semantic = _semantic(candidate)
            expected_sections = tuple(
                (
                    path,
                    len(rows),
                    only_research_scientific_v3_section_fingerprint(path.rsplit(".", 1)[0], rows),
                )
                for path, rows in semantic.items()
            )
            actual_sections = tuple((x.relative_path, x.row_count, x.logical_fingerprint) for x in candidate.sections)
            if actual_sections != expected_sections:
                raise ValueError("Scientific V3 logical sections mismatch")
            if (
                only_research_scientific_artifact_v3_content_fingerprint(
                    source.research_result_fingerprint, candidate.sections
                )
                != candidate.artifact_content_fingerprint
            ):
                raise ValueError("Scientific V3 Artifact identity mismatch")
            provisional = OnlyResearchScientificArtifactManifestV3(
                source.plan,
                source.research_result_plan_fingerprint,
                source.research_result_content_fingerprint,
                source.research_result_fingerprint,
                source.dataset_snapshot_fingerprint,
                source.calculation_results,
                source.statistics_results,
                candidate.sections,
                candidate.artifact_content_fingerprint,
                datetime(2000, 1, 1, tzinfo=UTC),
            )
            verify_scientific_artifact_v3_statistics(
                provisional,
                candidate.statistics_catalog,
                candidate.statistics_series_rows,
                candidate.statistics_summaries,
                candidate.graphs,
            )
            return candidate, _tables(candidate)
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", str(exc)) from exc

    def _reuse_existing(
        self, candidate: OnlyResearchScientificArtifactCandidateV3, target: Path
    ) -> OnlyResearchArtifactOutcome:
        existing = self.load_verified(candidate.result.manifest.research_result_fingerprint)
        if existing.manifest.artifact_content_fingerprint != candidate.artifact_content_fingerprint:
            raise OnlyResearchArtifactStoreError("DETERMINISTIC_ARTIFACT_CONFLICT", target.name)
        return OnlyResearchArtifactOutcome(
            OnlyResearchArtifactDisposition.REUSED,
            candidate.result.manifest.research_result_fingerprint,
            existing.manifest.artifact_content_fingerprint,
        )

    def _read_verified(self, root: Path, expected: str) -> OnlyResearchScientificArtifactV3:
        if not root.is_dir():
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", expected)
        try:
            required = {"artifact_manifest.json", *RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS}
            entries = tuple(root.iterdir())
            if (
                root.is_symlink()
                or {x.name for x in entries} != required
                or any(x.is_symlink() or not x.is_file() for x in entries)
            ):
                raise ValueError("Scientific Artifact V3 file set is invalid")
            manifest_payload = _json(root / "artifact_manifest.json")
            if not isinstance(manifest_payload, dict):
                raise ValueError("Scientific Artifact V3 manifest must be an object")
            manifest = OnlyResearchScientificArtifactManifestV3.from_dict(manifest_payload)
            if manifest.research_result_fingerprint != expected:
                raise ValueError("Scientific Artifact V3 path identity mismatch")
            descriptors = {x.relative_path: x for x in manifest.sections}
            tables = {
                path: pq.read_table(root / path)
                for path in ("market.parquet", "signals.parquet", "statistics_series.parquet", "variables.parquet")
            }
            expected_schemas = {
                "market.parquet": _MARKET,
                "signals.parquet": _SIGNALS,
                "statistics_series.parquet": _STATISTICS,
                "variables.parquet": _VARIABLES,
            }
            for path, descriptor in descriptors.items():
                if _sha(root / path) != descriptor.byte_sha256:
                    raise ValueError("Scientific Artifact V3 byte hash mismatch")
                if path.endswith(".parquet") and (
                    tables[path].schema != expected_schemas[path]
                    or descriptor.arrow_schema != _schema_payload(tables[path].schema)
                ):
                    raise ValueError("Scientific Artifact V3 Arrow schema mismatch")
                if not path.endswith(".parquet") and descriptor.arrow_schema is not None:
                    raise ValueError("Scientific Artifact V3 JSON section has Arrow schema")

            market = tuple(OnlyResearchScientificMarketRow(**x) for x in tables["market.parquet"].to_pylist())
            variables = tuple(_variable(x) for x in tables["variables.parquet"].to_pylist())
            signals = tuple(OnlyResearchScientificSignalRow(**x) for x in tables["signals.parquet"].to_pylist())
            series = tuple(
                OnlyResearchScientificStatisticsSeriesRowV3(
                    x["statistics_fingerprint"],
                    x["ts_event_ns"],
                    x["statistic_value"],
                    x["sample_count"],
                    x["status"],
                )
                for x in tables["statistics_series.parquet"].to_pylist()
            )
            raw_graphs = _array(_json(root / "graphs.json"))
            raw_catalog = _array(_json(root / "statistics_catalog.json"))
            raw_summaries = _array(_json(root / "statistics_summaries.json"))
            graphs = tuple(
                OnlyResearchScientificGraph(
                    _required_string(_object(x), "calculation_fingerprint"),
                    OnlyCalculationGraphDefinition.from_dict(_required_mapping(_object(x), "graph")),
                )
                for x in raw_graphs
            )
            catalog = tuple(only_research_scientific_catalog_entry_v3_from_dict(_object(x)) for x in raw_catalog)
            summaries = tuple(
                OnlyResearchScientificStatisticsSummaryV3(
                    _required_string(_summary_object(x), "statistics_fingerprint"),
                    only_research_summary_from_dict(_required_mapping(_summary_object(x), "summary")),
                )
                for x in raw_summaries
            )
            if market != tuple(sorted(market)) or signals != tuple(sorted(signals)) or graphs != tuple(sorted(graphs)):
                raise ValueError("Scientific Artifact V3 rows are not canonical")
            if (
                variables != tuple(sorted(variables, key=_variable_key))
                or series != tuple(sorted(series))
                or summaries != tuple(sorted(summaries))
            ):
                raise ValueError("Scientific Artifact V3 rows are not canonical")
            semantic = _semantic_values(market, variables, signals, graphs, catalog, series, summaries)
            for path, rows in semantic.items():
                descriptor = descriptors[path]
                if descriptor.row_count != len(
                    rows
                ) or descriptor.logical_fingerprint != only_research_scientific_v3_section_fingerprint(
                    path.rsplit(".", 1)[0], rows
                ):
                    raise ValueError("Scientific Artifact V3 logical section mismatch")
            _verify_logical_keys(market, variables, signals)
            _verify_variable_scalars(variables)
            _verify_variable_types(graphs, variables)
            _verify_series_axes(manifest.plan, market, variables, signals)
            verify_scientific_artifact_v3_statistics(manifest, catalog, series, summaries, graphs)
            return OnlyResearchScientificArtifactV3(
                manifest, market, variables, signals, graphs, catalog, series, summaries, tables
            )
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", "invalid fingerprint")
        return self._root / "research-scientific-v3" / "sha256" / fingerprint[:2] / fingerprint

    def _audit_timestamp(self) -> datetime:
        value = self._audit_time() if self._audit_time is not None else datetime.now(UTC)
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Scientific Artifact V3 audit timestamp must be timezone-aware UTC")
        return value


def _tables(candidate: OnlyResearchScientificArtifactCandidateV3) -> dict[str, pa.Table]:
    return {
        "market.parquet": pa.Table.from_pylist([x.to_dict() for x in candidate.market_rows], schema=_MARKET),
        "signals.parquet": pa.Table.from_pylist([x.to_dict() for x in candidate.signal_rows], schema=_SIGNALS),
        "statistics_series.parquet": pa.Table.from_pylist(
            [x.semantic_payload() for x in candidate.statistics_series_rows], schema=_STATISTICS
        ),
        "variables.parquet": pa.Table.from_pylist([x.to_dict() for x in candidate.variable_rows], schema=_VARIABLES),
    }


def _semantic(candidate: OnlyResearchScientificArtifactCandidateV3) -> dict[str, list[object]]:
    return _semantic_values(
        candidate.market_rows,
        candidate.variable_rows,
        candidate.signal_rows,
        candidate.graphs,
        candidate.statistics_catalog,
        candidate.statistics_series_rows,
        candidate.statistics_summaries,
    )


def _semantic_values(
    market: Iterable[Any],
    variables: Iterable[Any],
    signals: Iterable[Any],
    graphs: Iterable[Any],
    catalog: Iterable[Any],
    series: Iterable[Any],
    summaries: Iterable[Any],
) -> dict[str, list[object]]:
    return {
        "graphs.json": [x.to_dict() for x in graphs],
        "market.parquet": [x.to_dict() for x in market],
        "signals.parquet": [x.to_dict() for x in signals],
        "statistics_catalog.json": [x.to_dict() for x in catalog],
        "statistics_series.parquet": [x.semantic_payload() for x in series],
        "statistics_summaries.json": [x.to_dict() for x in summaries],
        "variables.parquet": [x.to_dict() for x in variables],
    }


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Scientific Artifact V3 JSON section must be an array")
    return value


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("Scientific Artifact V3 JSON member must be an object")
    return value


def _required_string(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ValueError(f"Scientific Artifact V3 {name} must be a string")
    return value


def _required_mapping(payload: dict[str, object], name: str) -> dict[str, object]:
    return _object(payload.get(name))


def _summary_object(value: object) -> dict[str, object]:
    payload = _object(value)
    if set(payload) != {"statistics_fingerprint", "summary"}:
        raise ValueError("Scientific Artifact V3 Summary entry fields are invalid")
    return payload


__all__ = ["OnlyParquetResearchScientificArtifactStoreV3"]
