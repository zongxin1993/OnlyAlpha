"""Exact sealed-producer provenance for immutable readiness-bearing Result V2."""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research._durability import _OnlyBoundPublicationTree
from onlyalpha.research.source_cut import OnlySourcePublicationBarrier, _only_barrier_publication

from .errors import OnlyResearchCalculationError
from .execution import (
    OnlyResearchCalculationImplementationBinding,
    _only_require_verified_research_calculation_execution_v2,
    _OnlyVerifiedResearchCalculationExecutionV2,
)
from .execution_evidence import _fingerprint, _integer, _sha, _string
from .execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from .publication import OnlyResearchCalculationPublicationContract
from .result_store import _canonical_outputs
from .result_v2 import OnlyResearchCalculationResultV2
from .result_v2_identity import _descriptor, only_research_calculation_result_content_fingerprint_v2
from .result_v2_ports import OnlyResearchCalculationResultStoreV2
from .result_v2_store import _canonical_readiness, _rename_exclusive, _sync_directory, _unique_object


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecutionEvidenceV2:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    calculation_result_fingerprint: str
    result_content_fingerprint: str
    research_implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...]
    authoring_generation_fingerprint: str | None = None
    execution_contract_version: str = "RESEARCH_CALCULATION_EXECUTION_V2"
    calculation_result_schema_version: int = 2
    readiness_contract_version: int = 1
    schema_version: int = 2
    runtime_execution_provenance: OnlyResearchRuntimeExecutionProvenanceV1 | None = None

    def __post_init__(self) -> None:
        for name, expected in (
            ("schema_version", 2),
            ("calculation_result_schema_version", 2),
            ("readiness_contract_version", 1),
        ):
            if _integer({name: getattr(self, name)}, name) != expected:
                raise ValueError("unsupported Research Execution Evidence V2 version")
        if self.execution_contract_version != "RESEARCH_CALCULATION_EXECUTION_V2":
            raise ValueError("unsupported Research Execution Evidence V2 execution contract")
        for name in (
            "calculation_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "calculation_result_fingerprint",
            "result_content_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.authoring_generation_fingerprint is not None:
            _sha(self.authoring_generation_fingerprint, "authoring_generation_fingerprint")
        if self.runtime_execution_provenance is not None:
            if type(self.runtime_execution_provenance) is not OnlyResearchRuntimeExecutionProvenanceV1:
                raise ValueError("exact Runtime execution provenance required")
            OnlyResearchRuntimeExecutionProvenanceV1.from_dict(self.runtime_execution_provenance.to_dict())
        bindings = self.research_implementation_bindings
        if (
            type(bindings) is not tuple
            or not bindings
            or any(type(item) is not OnlyResearchCalculationImplementationBinding for item in bindings)
        ):
            raise ValueError("non-empty typed Research implementation bindings required")
        for item in bindings:
            _sha(item.node_fingerprint, "node_fingerprint")
            _sha(item.research_implementation_fingerprint, "research_implementation_fingerprint")
        if bindings != tuple(sorted(bindings)) or len({item.node_fingerprint for item in bindings}) != len(bindings):
            raise ValueError("Research implementation bindings must be canonical and unique")

    @property
    def evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.calculation-execution-evidence", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "calculation_result_schema_version": self.calculation_result_schema_version,
            "readiness_contract_version": self.readiness_contract_version,
            "calculation_fingerprint": self.calculation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint": self.calculation_graph_fingerprint,
            "calculation_result_fingerprint": self.calculation_result_fingerprint,
            "result_content_fingerprint": self.result_content_fingerprint,
            "research_implementation_bindings": [
                {
                    "node_fingerprint": item.node_fingerprint,
                    "research_implementation_fingerprint": item.research_implementation_fingerprint,
                }
                for item in self.research_implementation_bindings
            ],
        }
        if self.authoring_generation_fingerprint is not None:
            payload["authoring_generation_fingerprint"] = self.authoring_generation_fingerprint
        if self.runtime_execution_provenance is not None:
            payload["runtime_execution_provenance"] = self.runtime_execution_provenance.to_dict()
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationExecutionEvidenceV2:
        expected = {
            "schema_version",
            "execution_contract_version",
            "calculation_result_schema_version",
            "readiness_contract_version",
            "calculation_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "calculation_result_fingerprint",
            "result_content_fingerprint",
            "research_implementation_bindings",
            "evidence_fingerprint",
        }
        if not isinstance(payload, Mapping) or set(payload) not in (
            expected,
            expected | {"authoring_generation_fingerprint"},
            expected | {"runtime_execution_provenance"},
            expected | {"authoring_generation_fingerprint", "runtime_execution_provenance"},
        ):
            raise ValueError("Research Execution Evidence V2 fields are invalid")
        raw = payload["research_implementation_bindings"]
        if not isinstance(raw, list):
            raise ValueError("Research implementation bindings must be an array")
        bindings = []
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != {
                "node_fingerprint",
                "research_implementation_fingerprint",
            }:
                raise ValueError("Research implementation binding fields are invalid")
            bindings.append(
                OnlyResearchCalculationImplementationBinding(
                    _string(item, "node_fingerprint"), _string(item, "research_implementation_fingerprint")
                )
            )
        evidence = cls(
            _string(payload, "calculation_fingerprint"),
            _string(payload, "dataset_snapshot_fingerprint"),
            _string(payload, "calculation_graph_fingerprint"),
            _string(payload, "calculation_result_fingerprint"),
            _string(payload, "result_content_fingerprint"),
            tuple(bindings),
            _string(payload, "authoring_generation_fingerprint")
            if "authoring_generation_fingerprint" in payload
            else None,
            _string(payload, "execution_contract_version"),
            _integer(payload, "calculation_result_schema_version"),
            _integer(payload, "readiness_contract_version"),
            _integer(payload, "schema_version"),
            _runtime_provenance(payload),
        )
        if _string(payload, "evidence_fingerprint") != evidence.evidence_fingerprint:
            raise ValueError("Research Execution Evidence V2 identity differs")
        return evidence


class OnlyResearchCalculationExecutionEvidenceStoreV2:
    """Read authority with one live-capability-checked internal minting path."""

    def __init__(self, semantic_root: Path, result_store: OnlyResearchCalculationResultStoreV2) -> None:
        self._semantic_root = semantic_root
        self._authority_root = semantic_root / "calculation-execution-evidence"
        self._v2_root = self._authority_root / "v2"
        self._staging_root = self._v2_root / ".staging"
        self._root = self._v2_root / "sha256"
        self._result_store = result_store
        self._publication_barrier = OnlySourcePublicationBarrier(semantic_root)

    def exists(self, evidence_fingerprint: str) -> bool:
        fingerprint = _fingerprint(evidence_fingerprint)
        target = self._target(fingerprint)
        if not _present(target):
            return False
        self.load_verified(fingerprint)
        return True

    def _publish_verified(
        self,
        verified_execution: _OnlyVerifiedResearchCalculationExecutionV2,
        result: OnlyResearchCalculationResultV2,
        authoring_generation_fingerprint: str | None = None,
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        execution = _only_require_verified_research_calculation_execution_v2(verified_execution)
        loaded = self._reload_result(result)
        manifest = loaded.manifest
        try:
            if type(execution.publication) is not OnlyResearchCalculationPublicationContract:
                raise ValueError("exact publication contract required")
            OnlyResearchCalculationPublicationContract.from_dict(execution.publication.to_dict())
            if (
                execution.calculation_fingerprint != manifest.calculation_fingerprint
                or execution.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint
                or execution.calculation_graph_fingerprint != manifest.calculation_graph_fingerprint
                or tuple(item.node_fingerprint for item in execution.research_implementation_bindings)
                != tuple(sorted(node.fingerprint for node in manifest.calculation_graph.nodes))
            ):
                raise ValueError("Execution/Result/Graph/Dataset/implementation linkage differs")
            # Result verification already proves its exact Dataset axes. Use the same
            # canonical projections and logical hashes as its sole publication authority.
            axes = {item.instrument_id: tuple(item.table["ts_event_ns"].to_pylist()) for item in loaded.outputs}
            outputs = _canonical_outputs(execution.outputs, manifest.calculation_graph, axes)
            readiness = _canonical_readiness(execution.readiness, outputs, manifest.calculation_graph, axes)
            if tuple((item.node_fingerprint, item.instrument_id) for item in execution.outputs) != tuple(
                (item.node_fingerprint, item.instrument_id) for item in loaded.outputs
            ) or tuple((item.node_fingerprint, item.instrument_id) for item in execution.readiness) != tuple(
                (item.node_fingerprint, item.instrument_id) for item in loaded.readiness
            ):
                raise ValueError("producer partition ordering/membership differs")
            content = only_research_calculation_result_content_fingerprint_v2(
                tuple(_descriptor(item.node_fingerprint, item.instrument_id, item.table) for item in outputs),
                tuple(
                    _descriptor(item.node_fingerprint, item.instrument_id, item.table, readiness=True)
                    for item in readiness
                ),
            )
            if content != manifest.result_content_fingerprint:
                raise ValueError("sealed producer values/readiness differ from authoritative Result")
        except (TypeError, ValueError, OnlyResearchCalculationError) as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_IDENTITY_MISMATCH", str(exc)) from exc
        evidence = OnlyResearchCalculationExecutionEvidenceV2(
            manifest.calculation_fingerprint,
            manifest.dataset_snapshot_fingerprint,
            manifest.calculation_graph_fingerprint,
            manifest.calculation_result_fingerprint,
            manifest.result_content_fingerprint,
            execution.research_implementation_bindings,
            authoring_generation_fingerprint,
            runtime_execution_provenance=(
                None if verified_execution.runtime_context is None else verified_execution.runtime_context.provenance
            ),
        )
        return self._publish(evidence)

    def load_verified(self, evidence_fingerprint: str) -> OnlyResearchCalculationExecutionEvidenceV2:
        fingerprint = _fingerprint(evidence_fingerprint)
        target = self._target(fingerprint)
        try:
            with closing(_OnlyBoundPublicationTree(target, self._semantic_root)) as tree:
                try:
                    tree.bind_directory(self._semantic_root)
                except FileNotFoundError as exc:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE", "owning anchor unavailable"
                    ) from exc
                if not tree.bind_existing_target():
                    raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", fingerprint)
                tree.require_exact({"manifest.json"})
                evidence = self._read_verified(target, fingerprint, tree.read_bytes("manifest.json"))
                result = self._result_store.load_verified(evidence.calculation_fingerprint)
                self._require_linkage(evidence, result)
                tree.require_namespace()
                return evidence
        except OSError as exc:
            code = (
                "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
                else "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"
            )
            raise OnlyResearchCalculationError(code, "Evidence read failed") from exc
        except ValueError as exc:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "Evidence namespace changed"
            ) from exc

    def acknowledge_exact(self, evidence_fingerprint: str) -> OnlyResearchCalculationExecutionEvidenceV2:
        """Verified publication re-entry, not a read-only lookup or a minting path."""
        return self._acknowledge(self.load_verified(evidence_fingerprint))

    def require_exact_for_result(
        self,
        result: OnlyResearchCalculationResultV2,
        implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...],
        runtime_provenance: OnlyResearchRuntimeExecutionProvenanceV1,
        authoring_generation_fingerprint: str | None = None,
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        """Exact producer re-entry, including the existing durability acknowledgement."""
        return self._acknowledge(
            self.load_exact_for_result(
                result, implementation_bindings, runtime_provenance, authoring_generation_fingerprint
            )
        )

    def load_exact_for_result(
        self,
        result: OnlyResearchCalculationResultV2,
        implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...],
        runtime_provenance: OnlyResearchRuntimeExecutionProvenanceV1,
        authoring_generation_fingerprint: str | None = None,
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        """Read the exact producer without minting, fsync or publication repair.

        NOT_FOUND is a lookup outcome, not a certified scientific absence. Relevant
        retained Evidence with incomplete mandatory provenance remains a conflict;
        a complete different producer never substitutes for the exact expectation.
        """
        if type(runtime_provenance) is not OnlyResearchRuntimeExecutionProvenanceV1:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "complete exact Runtime expectation required"
            )
        loaded = self._reload_result(result)
        manifest = loaded.manifest
        expected = OnlyResearchCalculationExecutionEvidenceV2(
            manifest.calculation_fingerprint,
            manifest.dataset_snapshot_fingerprint,
            manifest.calculation_graph_fingerprint,
            manifest.calculation_result_fingerprint,
            manifest.result_content_fingerprint,
            implementation_bindings,
            authoring_generation_fingerprint,
            runtime_execution_provenance=runtime_provenance,
        )
        try:
            selected = self.load_verified(expected.evidence_fingerprint)
        except OnlyResearchCalculationError as exc:
            if exc.code != "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND":
                raise
            for retained in self._iter_retained():
                verified = self.load_verified(retained.evidence_fingerprint)
                if verified.calculation_fingerprint == manifest.calculation_fingerprint and (
                    verified.runtime_execution_provenance is None
                    or (
                        authoring_generation_fingerprint is not None
                        and verified.authoring_generation_fingerprint is None
                    )
                ):
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "relevant producer mandatory provenance is incomplete"
                    ) from exc
            raise
        if selected != expected:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_IDENTITY_MISMATCH", "exact producer differs")
        return selected

    def require_no_retained_evidence_for_calculation(self, calculation_fingerprint: str) -> None:
        """Reject dangling local attestations before interpreting a missing Result as fresh work."""
        _sha(calculation_fingerprint, "calculation_fingerprint")
        for retained in self._iter_retained():
            if retained.calculation_fingerprint == calculation_fingerprint:
                raise OnlyResearchCalculationError(
                    "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "retained Evidence references missing Result"
                )
            self.load_verified(retained.evidence_fingerprint)

    def _iter_retained(self) -> tuple[OnlyResearchCalculationExecutionEvidenceV2, ...]:
        """A bound local read snapshot, never a historical absence witness.

        Read retained attestations without a Result lookup so dangling predecessor
        checks keep their existing semantics. Consumers independently load owning
        Results. Enumerated membership and every opened inode are rechecked before
        returning; unavailable anchors and mid-read loss never produce an empty scan.
        """
        self._target("0" * 64)
        try:
            with closing(_OnlyBoundPublicationTree(self._root, self._semantic_root)) as tree:
                try:
                    tree.bind_directory(self._semantic_root)
                except FileNotFoundError as exc:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE", "owning anchor unavailable"
                    ) from exc
                if not tree.bind_existing_target():
                    return ()
                retained = []
                entries = {self._root: tree.directory_entries(self._root)}
                for name in entries[self._root]:
                    if len(name) != 2 or any(char not in "0123456789abcdef" for char in name):
                        raise ValueError("malformed Evidence prefix")
                    prefix = self._root / name
                    entries[prefix] = tree.directory_entries(prefix)
                    for identity in entries[prefix]:
                        _sha(identity, "Evidence target")
                        if identity[:2] != name:
                            raise ValueError("Evidence prefix/path identity differs")
                        target = prefix / identity
                        tree.bind_file(target / "manifest.json")
                        entries[target] = tree.directory_entries(target)
                        if entries[target] != ("manifest.json",):
                            raise ValueError("malformed Evidence directory/manifest")
                        relative = f"{name}/{identity}/manifest.json"
                        retained.append(self._read_verified(target, identity, tree.read_bytes(relative)))
                for path, expected in entries.items():
                    if tree.directory_entries(path) != expected:
                        raise ValueError("Evidence namespace membership changed during scan")
                tree.require_namespace()
                return tuple(retained)
        except OnlyResearchCalculationError:
            raise
        except OSError as exc:
            code = (
                "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
                else "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"
            )
            raise OnlyResearchCalculationError(code, "authority scan") from exc
        except ValueError as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "authority scan") from exc

    def require_for_result(
        self, result: OnlyResearchCalculationResultV2, authoring_generation_fingerprint: str | None = None
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        matches = self.require_all_for_result(result, authoring_generation_fingerprint)
        if len(matches) != 1:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "multiple exact producers; explicit provenance required"
            )
        return matches[0]

    def require_all_for_result(
        self, result: OnlyResearchCalculationResultV2, authoring_generation_fingerprint: str | None = None
    ) -> tuple[OnlyResearchCalculationExecutionEvidenceV2, ...]:
        """Read complete attestations of scientific content, without selecting a producer.

        Result composition only proves publication evidence exists. Artifact and
        generation-bound reuse still require their own exact producer selection.
        """
        loaded = self._reload_result(result)
        if authoring_generation_fingerprint is not None:
            _sha(authoring_generation_fingerprint, "authoring_generation_fingerprint")
        # Validate every namespace link before interpreting a missing leaf as absence.
        self._target("0" * 64)
        if not _present(self._root):
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", loaded.manifest.calculation_result_fingerprint
            )
        matches = []
        try:
            for retained in self._iter_retained():
                evidence = self.load_verified(retained.evidence_fingerprint)
                if _result_identity(loaded) == _evidence_result_identity(evidence) and (
                    authoring_generation_fingerprint is None
                    or evidence.authoring_generation_fingerprint == authoring_generation_fingerprint
                ):
                    matches.append(evidence)
        except OnlyResearchCalculationError:
            raise
        except (OSError, ValueError) as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "authority scan") from exc
        if not matches:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", loaded.manifest.calculation_result_fingerprint
            )
        return tuple(matches)

    def _reload_result(self, result: OnlyResearchCalculationResultV2) -> OnlyResearchCalculationResultV2:
        if type(result) is not OnlyResearchCalculationResultV2:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_IDENTITY_MISMATCH", "exact Result V2 required")
        loaded = self._result_store.load_verified(result.manifest.calculation_fingerprint)
        if _result_identity(result) != _result_identity(loaded):
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "supplied/authoritative Result differs"
            )
        return loaded

    @staticmethod
    def _require_linkage(
        evidence: OnlyResearchCalculationExecutionEvidenceV2, result: OnlyResearchCalculationResultV2
    ) -> None:
        if _evidence_result_identity(evidence) != _result_identity(result) or tuple(
            item.node_fingerprint for item in evidence.research_implementation_bindings
        ) != tuple(sorted(node.fingerprint for node in result.manifest.calculation_graph.nodes)):
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "Evidence/Result/Graph linkage differs"
            )

    def _publish(
        self, evidence: OnlyResearchCalculationExecutionEvidenceV2
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        if self._semantic_root.is_symlink() or not self._semantic_root.is_dir():
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", "semantic root must be preprovisioned real directory"
            )
        return self._publish_under_barrier(evidence)

    @_only_barrier_publication
    def _publish_under_barrier(
        self, evidence: OnlyResearchCalculationExecutionEvidenceV2
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        fingerprint = evidence.evidence_fingerprint
        target = self._target(fingerprint)
        if _present(self._staging_root) and (self._staging_root.is_symlink() or not self._staging_root.is_dir()):
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "malformed staging directory")
        stage = self._staging_root / f".stage-{uuid.uuid4().hex}"
        try:
            self._staging_root.mkdir(parents=True, exist_ok=True)
            if _present(target):
                return self._acknowledge(evidence)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._target(fingerprint)
            if self._staging_root.stat().st_dev != target.parent.stat().st_dev:
                raise OSError("staging and Evidence target must share a filesystem")
            stage.mkdir()
            with (stage / "manifest.json").open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(evidence.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            self._read_verified(stage, fingerprint)
            _sync_directory(stage)
            try:
                _rename_exclusive(stage, target)
            except OSError:
                if not _present(target):
                    raise
            return self._acknowledge(evidence)
        except OnlyResearchCalculationError:
            raise
        except OSError as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", fingerprint) from exc
        finally:
            if stage.is_dir() and not stage.is_symlink():
                shutil.rmtree(stage)

    @_only_barrier_publication
    def _acknowledge(
        self, evidence: OnlyResearchCalculationExecutionEvidenceV2
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        loaded = self.load_verified(evidence.evidence_fingerprint)
        if loaded != evidence:
            raise OnlyResearchCalculationError(
                "DETERMINISTIC_EXECUTION_EVIDENCE_CONFLICT", evidence.evidence_fingerprint
            )
        self._result_store.acknowledge_exact(evidence.calculation_fingerprint, evidence.calculation_result_fingerprint)
        target = self._target(evidence.evidence_fingerprint)
        try:
            from onlyalpha.research._durability import _only_bind_publication_tree

            with _only_bind_publication_tree(target, self._semantic_root) as tree:
                tree.require_exact({"manifest.json"})
                tree.bind_directory(self._staging_root)
                bound = self._read_verified(target, evidence.evidence_fingerprint, tree.read_bytes("manifest.json"))
                if bound != loaded:
                    raise ValueError("Execution Evidence changed before acknowledgement")
                _sync_manifest(target / "manifest.json", descriptor=tree.bind_file(target / "manifest.json"))
                tree.synchronize(_sync_directory)
                reloaded = self._read_verified(target, evidence.evidence_fingerprint, tree.read_bytes("manifest.json"))
                tree.require_namespace()
                if reloaded != bound:
                    raise ValueError("Execution Evidence changed during acknowledgement")
                return reloaded
        except (OSError, ValueError) as exc:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", "publication sync failed"
            ) from exc

    def _read_verified(
        self, root: Path, expected: str, retained_manifest: bytes | None = None
    ) -> OnlyResearchCalculationExecutionEvidenceV2:
        if retained_manifest is None and not _present(root):
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", expected)
        try:
            manifest = root / "manifest.json"
            if retained_manifest is None and (
                not stat.S_ISDIR(root.lstat().st_mode)
                or not stat.S_ISREG(manifest.lstat().st_mode)
                or {item.name for item in root.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("malformed Evidence directory/manifest")
            raw = (
                manifest.read_text(encoding="utf-8") if retained_manifest is None else retained_manifest.decode("utf-8")
            )
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(payload, Mapping):
                raise ValueError("Evidence manifest must be an object")
            evidence = OnlyResearchCalculationExecutionEvidenceV2.from_dict(payload)
            if evidence.evidence_fingerprint != expected or raw != only_canonical_json(evidence.to_dict()):
                raise ValueError("Evidence path/content identity differs")
            return evidence
        except OSError as exc:
            code = (
                "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
                else "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"
            )
            raise OnlyResearchCalculationError(code, "Evidence read failed") from exc
        except (ValueError, TypeError) as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", expected) from exc

    def _target(self, fingerprint: str) -> Path:
        path = self._semantic_root
        mode: int | None
        for part in ("calculation-execution-evidence", "v2", "sha256", fingerprint[:2], fingerprint):
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError as exc:
                if path == self._semantic_root:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE", "owning anchor unavailable"
                    ) from exc
                mode = None
            except OSError as exc:
                code = (
                    "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
                    if exc.errno in {errno.ENOTDIR, errno.ELOOP}
                    else "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"
                )
                raise OnlyResearchCalculationError(code, "Evidence namespace unavailable") from exc
            if mode is not None and not stat.S_ISDIR(mode):
                raise OnlyResearchCalculationError(
                    "RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "malformed authority directory"
                )
            path = path / part
        return path


def _result_identity(result: OnlyResearchCalculationResultV2) -> tuple[object, ...]:
    manifest = result.manifest
    if (
        type(manifest.schema_version) is not int
        or manifest.schema_version != 2
        or type(manifest.readiness_contract_version) is not int
        or manifest.readiness_contract_version != 1
    ):
        raise OnlyResearchCalculationError("RESEARCH_EXECUTION_IDENTITY_MISMATCH", "Result version differs")
    return (
        manifest.schema_version,
        manifest.readiness_contract_version,
        manifest.calculation_fingerprint,
        manifest.dataset_snapshot_fingerprint,
        manifest.calculation_graph_fingerprint,
        manifest.result_content_fingerprint,
        manifest.calculation_result_fingerprint,
    )


def _evidence_result_identity(evidence: OnlyResearchCalculationExecutionEvidenceV2) -> tuple[object, ...]:
    return (
        evidence.calculation_result_schema_version,
        evidence.readiness_contract_version,
        evidence.calculation_fingerprint,
        evidence.dataset_snapshot_fingerprint,
        evidence.calculation_graph_fingerprint,
        evidence.result_content_fingerprint,
        evidence.calculation_result_fingerprint,
    )


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        code = (
            "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
            if exc.errno in {errno.ENOTDIR, errno.ELOOP}
            else "RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"
        )
        raise OnlyResearchCalculationError(code, "authority entry unavailable") from exc
    return True


def _sync_manifest(path: Path, *, descriptor: int | None = None) -> None:
    if descriptor is not None:
        os.fsync(descriptor)
        return
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


__all__ = ["OnlyResearchCalculationExecutionEvidenceV2", "OnlyResearchCalculationExecutionEvidenceStoreV2"]


def _runtime_provenance(payload: Mapping[str, object]) -> OnlyResearchRuntimeExecutionProvenanceV1 | None:
    if "runtime_execution_provenance" not in payload:
        return None
    raw = payload["runtime_execution_provenance"]
    if not isinstance(raw, Mapping):
        raise ValueError("Runtime execution provenance must be an object")
    return OnlyResearchRuntimeExecutionProvenanceV1.from_dict(raw)
