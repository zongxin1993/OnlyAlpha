"""Verified atomic immutable JSON Research Result authority."""

from __future__ import annotations

import errno
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing, contextmanager
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from onlyalpha.research._durability import _OnlyBoundPublicationTree
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.source_cut import (
    OnlySourceClosedCutV1,
    OnlySourceObservationV1,
    _OnlyFileSourceCutAuthority,
    only_sha256_source_inventory,
    only_source_publication,
)

from .errors import OnlyResearchResultStoreError
from .identity import (
    RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION,
    RESEARCH_RESULT_CALCULATION_SCHEMA_VERSION,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)

if TYPE_CHECKING:
    from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
    from onlyalpha.research.calculation.result_v2_ports import OnlyResearchCalculationResultStoreV2
from .result import (
    OnlyResearchResult,
    OnlyResearchResultDisposition,
    OnlyResearchResultManifest,
    OnlyResearchResultOutcome,
)
from .statistics_verification import (
    OnlyResearchComposableStatisticsResult,
    verify_rich_statistics_composition,
)


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchComposableStatisticsResult: ...


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


def _require_readiness_anchor(
    method: Callable[[OnlyJsonResearchResultStore, OnlyResearchResult], OnlyResearchResultOutcome],
) -> Callable[[OnlyJsonResearchResultStore, OnlyResearchResult], OnlyResearchResultOutcome]:
    """Check the V4 anchor before the shared publication barrier can create its root."""

    @wraps(method)
    def guarded(store: OnlyJsonResearchResultStore, result: OnlyResearchResult) -> OnlyResearchResultOutcome:
        if (
            isinstance(result, OnlyResearchResult)
            and getattr(result.manifest, "schema_version", 1) == RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION
        ):
            anchor = store._root.parent
            if anchor.is_symlink() or not anchor.is_dir():
                raise OnlyResearchResultStoreError(
                    "RESEARCH_RESULT_COMMIT_FAILED", "V4 Result anchor must be preprovisioned"
                )
        return method(store, result)

    return guarded


class OnlyJsonResearchResultStore:
    def __init__(
        self,
        root: Path,
        statistics_result_store: _StatisticsResultStore | None,
        calculation_result_store: _CalculationResultStore | None = None,
        *,
        readiness_result_store: OnlyResearchCalculationResultStoreV2 | None = None,
        readiness_evidence_store: OnlyResearchCalculationExecutionEvidenceStoreV2 | None = None,
    ) -> None:
        self._root = root
        self._statistics_result_store = statistics_result_store
        self._calculation_result_store = calculation_result_store
        self._readiness_result_store = readiness_result_store
        self._readiness_evidence_store = readiness_evidence_store
        self._source_cuts = _OnlyFileSourceCutAuthority(
            root, "RESEARCH_RESULT", 2, lambda: only_sha256_source_inventory(root), self._cut_read
        )

    def capture_closed_cut(self) -> OnlySourceClosedCutV1:
        return self._source_cuts.capture_closed_cut()

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        return self._source_cuts.load_closed_cut_verified(fingerprint)

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]:
        return self._source_cuts.iter_closed_cut_observations_verified(fingerprint)

    def _cut_read(self, locator: str) -> tuple[str, dict[str, object]]:
        result = self.load_verified(locator)
        return result.manifest.research_result_fingerprint, result.manifest.to_dict()

    def exists(self, research_result_plan_fingerprint: str) -> bool:
        return self._target(research_result_plan_fingerprint).exists()

    @_require_readiness_anchor
    @only_source_publication
    def commit(self, result: OnlyResearchResult) -> OnlyResearchResultOutcome:
        candidate = self._admit(result)
        plan_fingerprint = candidate.manifest.research_result_plan_fingerprint
        target = self._target(plan_fingerprint)
        if candidate.manifest.schema_version == RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION:
            return self._commit_readiness(candidate)
        if target.exists() or target.is_symlink():
            existing = self._resolve_existing(candidate)
            return self._outcome(OnlyResearchResultDisposition.REUSED, existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            (stage / "manifest.json").write_text(
                json.dumps(candidate.manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                self._read_verified(stage, plan_fingerprint)
            except OnlyResearchResultStoreError as exc:
                raise OnlyResearchResultStoreError(
                    "RESEARCH_RESULT_COMMIT_FAILED", "staged Research Result verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                existing = self._resolve_existing(candidate)
                return self._outcome(OnlyResearchResultDisposition.REUSED, existing)
            committed = self.load_verified(plan_fingerprint)
            return self._outcome(OnlyResearchResultDisposition.EXECUTED, committed)
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_COMMIT_FAILED", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, research_result_plan_fingerprint: str) -> OnlyResearchResult:
        return self._read_verified(self._target(research_result_plan_fingerprint), research_result_plan_fingerprint)

    @contextmanager
    def inspect_readiness_verified(self, plan_fingerprint: str) -> Iterator[OnlyResearchResult]:
        """Retain Result4 and every owning predecessor through relation inspection."""
        from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
        from onlyalpha.research.calculation.result_v2_store import (
            OnlyParquetResearchCalculationResultStoreV2,
            _unique_object,
        )

        from .readiness_verification import only_verify_readiness_composition

        calculations = self._readiness_result_store
        evidence = self._readiness_evidence_store
        if not isinstance(calculations, OnlyParquetResearchCalculationResultStoreV2) or not isinstance(
            evidence, OnlyResearchCalculationExecutionEvidenceStoreV2
        ):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_CORRUPT", "scoped readiness owners required")
        target = self._target(plan_fingerprint)
        consumer_error: BaseException | None = None
        try:
            with closing(_OnlyBoundPublicationTree(target, self._root)) as tree, ExitStack() as opened:
                try:
                    tree.bind_directory(self._root)
                except FileNotFoundError as exc:
                    raise OnlyResearchResultStoreError(
                        "RESEARCH_RESULT_STORE_UNAVAILABLE", "owning root missing"
                    ) from exc
                if not tree.bind_existing_target():
                    raise OnlyResearchResultStoreError("RESEARCH_RESULT_NOT_FOUND", plan_fingerprint)
                tree.require_exact({"manifest.json"})
                original_manifest = tree.read_bytes("manifest.json")
                payload = json.loads(original_manifest, object_pairs_hook=_unique_object)
                if not isinstance(payload, dict):
                    raise ValueError("Result manifest must be an object")
                result = OnlyResearchResult(OnlyResearchResultManifest.from_dict(payload))
                if result.manifest.research_result_plan_fingerprint != plan_fingerprint:
                    raise ValueError("Research Result path identity differs")
                if result.manifest.schema_version != RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION:
                    raise ValueError("Result4 required for readiness inspection")
                retained = {}
                published_producers = opened.enter_context(evidence._inspect_retained())
                for reference in result.manifest.calculation_results:
                    calculation = opened.enter_context(calculations.inspect_verified(reference.calculation_fingerprint))
                    if calculation.manifest.calculation_result_fingerprint != reference.calculation_result_fingerprint:
                        raise ValueError("Result4 exact Calculation relation differs")
                    retained[reference.calculation_fingerprint] = calculation
                    matched = False
                    for producer in published_producers:
                        verified = opened.enter_context(evidence.inspect_verified(producer.evidence_fingerprint))
                        if verified != producer:
                            raise ValueError("Result4 producer changed during inspection")
                        if verified.calculation_fingerprint == reference.calculation_fingerprint:
                            evidence._require_linkage(verified, calculation)
                            matched = True
                    if not matched:
                        raise ValueError("Result4 has no owning producer Evidence")
                only_verify_readiness_composition(result.manifest.plan, retained)
                tree.require_namespace()
                try:
                    yield result
                except BaseException as exc:
                    consumer_error = exc
                    raise
                if tree.read_bytes("manifest.json") != original_manifest:
                    raise ValueError("Research Result manifest changed in place during inspection")
                tree.require_namespace()
        except (OSError, ValueError) as exc:
            if exc is consumer_error:
                raise
            code = (
                "RESEARCH_RESULT_STORE_UNAVAILABLE"
                if isinstance(exc, OSError)
                and exc.errno not in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR}
                else "RESEARCH_RESULT_CORRUPT"
            )
            raise OnlyResearchResultStoreError(code, "scoped Result binding failed") from exc

    def _admit(self, result: OnlyResearchResult) -> OnlyResearchResult:
        if not isinstance(result, OnlyResearchResult):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_INVALID", "Result contract is invalid")
        try:
            if getattr(result.manifest, "schema_version", 1) == RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION:
                if (
                    type(result) is not OnlyResearchResult
                    or OnlyResearchResultManifest.from_dict(result.manifest.to_dict()) != result.manifest
                ):
                    raise ValueError("Result V4 canonical contract differs")
            self._verify_upstream(result.manifest)
            return result
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_INVALID", str(exc)) from exc

    def _resolve_existing(self, candidate: OnlyResearchResult) -> OnlyResearchResult:
        existing = self.load_verified(candidate.manifest.research_result_plan_fingerprint)
        if (
            existing.manifest.research_result_content_fingerprint
            != candidate.manifest.research_result_content_fingerprint
            or existing.manifest.research_result_fingerprint != candidate.manifest.research_result_fingerprint
        ):
            raise OnlyResearchResultStoreError(
                "DETERMINISTIC_RESULT_CONFLICT", candidate.manifest.research_result_plan_fingerprint
            )
        return existing

    def _read_verified(
        self, root: Path, expected_plan_fingerprint: str, retained_manifest: bytes | None = None
    ) -> OnlyResearchResult:
        if retained_manifest is None and (root.is_symlink() or (root.exists() and not root.is_dir())):
            raise OnlyResearchResultStoreError(
                "RESEARCH_RESULT_CORRUPT", "Research Result root is not a regular directory"
            )
        if retained_manifest is None and not root.is_dir():
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_NOT_FOUND", expected_plan_fingerprint)
        try:
            manifest_path = root / "manifest.json"
            if retained_manifest is None and (root.is_symlink() or manifest_path.is_symlink()):
                raise ValueError("Research Result authority may not contain symlinks")
            if retained_manifest is None and {item.name for item in root.iterdir()} != {"manifest.json"}:
                raise ValueError("unexpected Research Result files")
            from onlyalpha.research.calculation.result_v2_store import _unique_object

            payload = json.loads(
                manifest_path.read_bytes() if retained_manifest is None else retained_manifest,
                object_pairs_hook=_unique_object,
            )
            if not isinstance(payload, dict):
                raise ValueError("Research Result manifest must be an object")
            manifest = OnlyResearchResultManifest.from_dict(payload)
            if manifest.research_result_plan_fingerprint != expected_plan_fingerprint:
                raise ValueError("Research Result path identity mismatch")
            self._verify_upstream(manifest)
            return OnlyResearchResult(manifest)
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_CORRUPT", str(exc)) from exc

    def _verify_upstream(self, manifest: OnlyResearchResultManifest) -> None:
        schema_version = getattr(manifest, "schema_version", 1)
        if schema_version == RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION:
            self._verify_readiness_upstream(manifest)
            return
        dataset: str | None = (
            manifest.plan.dataset_snapshot_fingerprint
            if schema_version == RESEARCH_RESULT_CALCULATION_SCHEMA_VERSION
            else None
        )
        actual_references = []
        verified_statistics: dict[str, OnlyResearchComposableStatisticsResult] = {}
        for reference in manifest.statistics_results:
            if self._statistics_result_store is None:
                raise ValueError("Statistics Result authority required")
            upstream = self._statistics_result_store.load_verified(reference.statistics_fingerprint)
            verified_statistics[reference.statistics_fingerprint] = upstream
            upstream_manifest = upstream.manifest
            if upstream_manifest.statistics_fingerprint != reference.statistics_fingerprint:
                raise ValueError("Research Result Statistics logical identity mismatch")
            if upstream_manifest.statistics_result_fingerprint != reference.statistics_result_fingerprint:
                raise ValueError("Research Result Statistics Result identity mismatch")
            if dataset is None:
                dataset = upstream_manifest.dataset_snapshot_fingerprint
            elif dataset != upstream_manifest.dataset_snapshot_fingerprint:
                raise ValueError("Research Result Statistics Results use different Dataset Snapshots")
            actual_references.append(reference.to_dict())
        if dataset != manifest.dataset_snapshot_fingerprint:
            raise ValueError("Research Result Dataset Snapshot linkage mismatch")
        actual_calculations = []
        if schema_version in {2, RESEARCH_RESULT_CALCULATION_SCHEMA_VERSION}:
            if self._calculation_result_store is None:
                raise ValueError("Scientific Research Result requires Calculation Result Store")
            verified_calculations: dict[str, OnlyResearchCalculationResult] = {}
            for calculation_member, calculation_reference in zip(
                manifest.plan.calculations, manifest.calculation_results, strict=True
            ):
                calculation_upstream = self._calculation_result_store.load_verified(
                    calculation_reference.calculation_fingerprint
                )
                calculation_manifest = calculation_upstream.manifest
                if calculation_manifest.calculation_fingerprint != calculation_member.calculation_fingerprint:
                    raise ValueError("Research Result Calculation logical identity mismatch")
                if (
                    calculation_manifest.calculation_result_fingerprint
                    != calculation_reference.calculation_result_fingerprint
                ):
                    raise ValueError("Research Result Calculation Result identity mismatch")
                if calculation_manifest.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint:
                    raise ValueError("Research Result Calculation Dataset linkage mismatch")
                if calculation_manifest.calculation_graph_fingerprint != calculation_member.graph_fingerprint:
                    raise ValueError("Research Result Calculation Graph linkage mismatch")
                actual_calculations.append(calculation_reference.to_dict())
                verified_calculations[calculation_reference.calculation_fingerprint] = calculation_upstream
            for member in manifest.plan.published_series:
                graph = verified_calculations[member.calculation_fingerprint].manifest.calculation_graph
                node = next((item for item in graph.nodes if item.fingerprint == member.node_fingerprint), None)
                if node is None:
                    raise ValueError("Research Result scientific node linkage mismatch")
                output = next((item for item in node.definition.outputs if item.name == member.output_name), None)
                if output is None:
                    raise ValueError("Research Result scientific output linkage mismatch")
            for signal_member in manifest.plan.signals:
                graph = verified_calculations[signal_member.calculation_fingerprint].manifest.calculation_graph
                node = next((item for item in graph.nodes if item.fingerprint == signal_member.node_fingerprint), None)
                if node is None:
                    raise ValueError("Research Result scientific node linkage mismatch")
                output = next(
                    (item for item in node.definition.outputs if item.name == signal_member.output_name), None
                )
                if output is None or output.semantic_type != signal_member.role:
                    raise ValueError("Research Result scientific output linkage mismatch")
            verify_rich_statistics_composition(manifest.plan, verified_statistics, verified_calculations)
        content = only_research_result_content_fingerprint(
            tuple(actual_references), tuple(actual_calculations), schema_version=schema_version
        )
        if content != manifest.research_result_content_fingerprint:
            raise ValueError("Research Result content fingerprint mismatch")
        result = only_research_result_fingerprint(
            manifest.research_result_plan_fingerprint, content, schema_version=schema_version
        )
        if result != manifest.research_result_fingerprint:
            raise ValueError("Research Result fingerprint mismatch")

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_NOT_FOUND", "invalid Research Result Plan fingerprint")
        target = self._root / "sha256" / fingerprint[:2] / fingerprint
        for path in (self._root.parent, self._root, self._root / "sha256", target.parent):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise OnlyResearchResultStoreError("RESEARCH_RESULT_CORRUPT", "malformed Result authority namespace")
        return target

    def _verify_readiness_upstream(self, manifest: OnlyResearchResultManifest) -> None:
        from .readiness_verification import only_verify_readiness_composition

        if self._readiness_result_store is None:
            raise ValueError("Result V4 requires Calculation Result V2 authority")
        calculations = {
            item.calculation_fingerprint: self._readiness_result_store.load_verified(item.calculation_fingerprint)
            for item in manifest.calculation_results
        }
        only_verify_readiness_composition(manifest.plan, calculations)
        if self._readiness_evidence_store is None:
            raise ValueError("Result V4 requires Execution Evidence V2 authority")
        for calculation in calculations.values():
            self._readiness_evidence_store.require_all_for_result(calculation)
        for reference in manifest.calculation_results:
            if (
                calculations[reference.calculation_fingerprint].manifest.calculation_result_fingerprint
                != reference.calculation_result_fingerprint
            ):
                raise ValueError("Result V4 exact Calculation Result identity differs")

    def _commit_readiness(self, candidate: OnlyResearchResult) -> OnlyResearchResultOutcome:
        from onlyalpha.research.calculation.result_v2_store import _rename_exclusive, _sync_directory

        fingerprint = candidate.manifest.research_result_plan_fingerprint
        target = self._target(fingerprint)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            if self._root.parent.is_symlink() or not self._root.parent.is_dir():
                raise ValueError("Result parent must be a preprovisioned real durability anchor")
            if target.exists() or target.is_symlink():
                self._resolve_existing(candidate)
                return self._outcome(
                    OnlyResearchResultDisposition.REUSED,
                    self.acknowledge_exact(fingerprint, candidate.manifest.research_result_fingerprint),
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            self._target(fingerprint)
            stage.mkdir()
            with (stage / "manifest.json").open("x", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(candidate.manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                )
                stream.flush()
                os.fsync(stream.fileno())
            self._read_verified(stage, fingerprint)
            _sync_directory(stage)
            disposition = OnlyResearchResultDisposition.EXECUTED
            try:
                _rename_exclusive(stage, target)
            except OSError:
                if not target.exists() and not target.is_symlink():
                    raise
                disposition = OnlyResearchResultDisposition.REUSED
            self._resolve_existing(candidate)
            acknowledged = self.acknowledge_exact(fingerprint, candidate.manifest.research_result_fingerprint)
            return self._outcome(disposition, acknowledged)
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError(
                "RESEARCH_RESULT_COMMIT_FAILED", "V4 publication acknowledgement failed"
            ) from exc
        finally:
            if stage.is_dir() and not stage.is_symlink():
                shutil.rmtree(stage)

    def acknowledge_exact(self, plan_fingerprint: str, result_fingerprint: str) -> OnlyResearchResult:
        # Re-entry may acknowledge an existing owner, never recreate a lost root.
        with self._source_cuts._publication_barrier.publication_existing():
            return self._acknowledge_existing(plan_fingerprint, result_fingerprint)

    def _acknowledge_existing(self, plan_fingerprint: str, result_fingerprint: str) -> OnlyResearchResult:
        """Resync an exact V4 publication and all Calculation predecessors; ordinary reads do not write."""
        from onlyalpha.research.calculation.result_v2_store import _sync_directory

        result = self.load_verified(plan_fingerprint)
        if result.manifest.research_result_fingerprint != result_fingerprint:
            raise OnlyResearchResultStoreError("DETERMINISTIC_RESULT_CONFLICT", plan_fingerprint)
        if result.manifest.schema_version != RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_INVALID", "explicit V4 acknowledgement required")
        assert self._readiness_result_store is not None
        assert self._readiness_evidence_store is not None
        try:
            locked_descriptor = self._source_cuts._publication_lock_descriptor()
            for reference in result.manifest.calculation_results:
                calculation = self._readiness_result_store.acknowledge_exact(
                    reference.calculation_fingerprint, reference.calculation_result_fingerprint
                )
                for evidence in self._readiness_evidence_store.require_all_for_result(calculation):
                    self._readiness_evidence_store.acknowledge_exact(evidence.evidence_fingerprint)
            target = self._target(plan_fingerprint)
            from onlyalpha.research._durability import _only_bind_publication_tree

            with _only_bind_publication_tree(target, self._root.parent) as tree:
                tree.require_exact({"manifest.json"})
                tree.bind_file(self._root / ".source-cut.lock", descriptor=locked_descriptor)
                bound = self._read_verified(target, plan_fingerprint, tree.read_bytes("manifest.json"))
                if bound != result:
                    raise ValueError("Research Result changed before acknowledgement")
                tree.synchronize(_sync_directory)
                reloaded = self._read_verified(target, plan_fingerprint, tree.read_bytes("manifest.json"))
                tree.require_namespace()
                self._source_cuts._publication_lock_descriptor()
                if reloaded != bound:
                    raise ValueError("Research Result changed during acknowledgement")
                return reloaded
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_COMMIT_FAILED", "V4 publication sync failed") from exc

    @staticmethod
    def _outcome(disposition: OnlyResearchResultDisposition, result: OnlyResearchResult) -> OnlyResearchResultOutcome:
        return OnlyResearchResultOutcome(
            disposition,
            result.manifest.research_result_plan_fingerprint,
            result.manifest.research_result_fingerprint,
        )


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)
