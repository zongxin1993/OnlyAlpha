"""Content-addressed Calculation V2 Artifact publication and strict offline reading."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.research._durability import _only_bind_publication_tree, _OnlyBoundPublicationTree
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceV2
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.calculation.result_identity import only_research_calculation_arrow_schema_payload
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultManifestV2
from onlyalpha.research.calculation.result_v2_store import _rename_exclusive, _sync_directory, _unique_object
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1
from onlyalpha.research.result.result import OnlyResearchResultManifest
from onlyalpha.research.source_cut import OnlySourceCutError, OnlySourcePublicationBarrier, _only_barrier_publication

from .calculation_v2_model import (
    OnlyResearchCalculationArtifactFileV2,
    OnlyResearchCalculationArtifactManifestV2,
    _only_calculation_artifact_reference_manifest,
)
from .calculation_v2_sections import _section_json, _section_schemas
from .calculation_v2_verification import OnlyResearchCalculationArtifactV2, only_verify_calculation_artifact_tables_v2
from .errors import OnlyResearchArtifactStoreError

# Explicit profile-local read bounds, not E1 execution limits. Encoded and logical
# decoded totals are independently bounded across the complete package.
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_CONTENT_BYTES = 512 * 1024 * 1024
_MAX_PARTITION_ROWS = 2_000_000


class OnlyParquetResearchCalculationArtifactStoreV2:
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
        self._publication_barrier = OnlySourcePublicationBarrier(root)

    def load_verified(
        self,
        artifact_content_fingerprint: str,
        *,
        research_result_fingerprint: str,
        expected_runtime_provenance: OnlyResearchRuntimeExecutionProvenanceV1 | None = None,
    ) -> OnlyResearchCalculationArtifactV2:
        """Exact Result/Artifact pair; no Result-address lookup or upstream access."""
        if (
            type(research_result_fingerprint) is not str
            or len(research_result_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in research_result_fingerprint)
        ):
            raise OnlyResearchArtifactStoreError("ARTIFACT_IDENTITY_MISMATCH", "invalid Research Result fingerprint")
        loaded = self._read_verified(self._target(artifact_content_fingerprint), artifact_content_fingerprint)
        if loaded.manifest.result.research_result_fingerprint != research_result_fingerprint:
            raise OnlyResearchArtifactStoreError("ARTIFACT_IDENTITY_MISMATCH", "explicit Research Result differs")
        if (
            expected_runtime_provenance is not None
            and loaded.manifest.expected_runtime_provenance != expected_runtime_provenance
        ):
            raise OnlyResearchArtifactStoreError("ARTIFACT_PROVENANCE_MISMATCH", "explicit Runtime expectation differs")
        return loaded

    def load_exact_for_publication(
        self,
        *,
        result: OnlyResearchResultManifest,
        dataset: OnlyResearchDatasetSnapshot,
        calculations: tuple[OnlyResearchCalculationResultManifestV2, ...],
        selected_evidence: tuple[OnlyResearchCalculationExecutionEvidenceV2, ...],
        retained_generation: OnlyRetainedRuntimeGenerationProofV1,
        sealed_input: OnlyRetainedSealedChartInputEvidenceV1,
    ) -> OnlyResearchCalculationArtifactV2:
        """Derive the exact pair from complete references and read its bound package.

        Callers obtain the expectations from owning verified readers. Parsed copies
        are not Source/producer/Attempt authority. No scan, latest selection, new
        index, acknowledgement or publication occurs. A local NOT_FOUND cannot
        certify historical or scientific absence, nor authorize cancellation.
        """
        try:
            reference = _only_calculation_artifact_reference_manifest(
                result=result,
                dataset=dataset,
                calculations=calculations,
                selected_evidence=selected_evidence,
                retained_generation=retained_generation,
                sealed_input=sealed_input,
            )
            identity = reference.artifact_content_fingerprint
            target = self._target(identity)
            with closing(_OnlyBoundPublicationTree(target, self._root)) as tree:
                try:
                    tree.bind_directory(self._root)
                except FileNotFoundError as exc:
                    raise OnlyResearchArtifactStoreError(
                        "ARTIFACT_STORE_UNAVAILABLE", "owning root unavailable"
                    ) from exc
                if not tree.bind_existing_target():
                    raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", identity)
                loaded = self._read_verified(target, identity, tree)
                if (
                    loaded.manifest.result.research_result_fingerprint != result.research_result_fingerprint
                    or loaded.manifest.expected_runtime_provenance != reference.expected_runtime_provenance
                ):
                    raise ValueError("exact publication references differ")
                tree.require_namespace()
                return loaded
        except OnlyResearchArtifactStoreError:
            raise
        except OSError as exc:
            code = (
                "ARTIFACT_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
                else "ARTIFACT_STORE_UNAVAILABLE"
            )
            raise OnlyResearchArtifactStoreError(code, "exact publication inspection failed") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", "exact publication inspection failed") from exc

    @contextmanager
    def inspect_retained_for_calculation(
        self, calculation_fingerprint: str
    ) -> Iterator[tuple[OnlyResearchCalculationArtifactV2, ...]]:
        """Hold zero-write owning exclusion over a complete current V2 inventory.

        Verify every published candidate before selecting Calculation membership,
        including other Plans/producers. No live predecessor or Source is read or
        restored. An empty tuple is not a historical/Run absence witness. Consumers
        must exit successfully before using this snapshot and cannot publish or
        acknowledge under its exclusive lock.
        """
        if (
            type(calculation_fingerprint) is not str
            or len(calculation_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in calculation_fingerprint)
        ):
            raise OnlyResearchArtifactStoreError("ARTIFACT_IDENTITY_MISMATCH", "invalid Calculation fingerprint")
        root = self._root.absolute()
        consumer_error: BaseException | None = None
        try:
            with (
                closing(_OnlyBoundPublicationTree(root, root)) as owner,
                self._publication_barrier.inspect_bound_readonly(owner),
                ExitStack() as opened,
            ):
                memberships: dict[Path, tuple[str, ...]] = {}
                packages: list[_OnlyBoundPublicationTree] = []

                def entries(path: Path) -> tuple[str, ...]:
                    names = owner.directory_entries(path)
                    memberships[path] = names
                    return names

                def require_inventory() -> None:
                    owner.require_namespace()
                    for package in packages:
                        package.require_namespace()
                    for path, names in memberships.items():
                        if owner.directory_entries(path) != names:
                            raise ValueError("Artifact inventory membership changed")

                matches = []
                family = root / "research-calculation-v2"
                if family.name in entries(root):
                    names = entries(family)
                    if set(names) - {"sha256"}:
                        raise ValueError("unknown Artifact V2 namespace entry")
                    if "sha256" in names:
                        addressed = family / "sha256"
                        for prefix in entries(addressed):
                            if len(prefix) != 2 or any(char not in "0123456789abcdef" for char in prefix):
                                raise ValueError("noncanonical Artifact prefix")
                            directory = addressed / prefix
                            for identity in entries(directory):
                                target = directory / identity
                                owner.bind_directory(target)
                                if identity.startswith(".stage-"):
                                    token = identity.removeprefix(".stage-")
                                    stage = uuid.UUID(hex=token)
                                    if stage.hex != token or stage.version != 4:
                                        raise ValueError("noncanonical Artifact staging directory")
                                    continue
                                if (
                                    len(identity) != 64
                                    or any(char not in "0123456789abcdef" for char in identity)
                                    or not identity.startswith(prefix)
                                ):
                                    raise ValueError("noncanonical Artifact content address")
                                package = opened.enter_context(closing(_OnlyBoundPublicationTree(target, root)))
                                packages.append(package)
                                artifact = self._read_verified(target, identity, package)
                                package.require_namespace()
                                if any(
                                    item.calculation_fingerprint == calculation_fingerprint
                                    for item in artifact.manifest.calculations
                                ):
                                    matches.append(artifact)
                require_inventory()
                try:
                    yield tuple(matches)
                except BaseException as exc:
                    consumer_error = exc
                    raise
                require_inventory()
        except OnlyResearchArtifactStoreError:
            raise
        except OnlySourceCutError as exc:
            if exc is consumer_error:
                raise
            code = "ARTIFACT_STORE_UNAVAILABLE" if str(exc) == "SOURCE_PUBLICATION_UNAVAILABLE" else "ARTIFACT_CORRUPT"
            raise OnlyResearchArtifactStoreError(code, "owning inventory exclusion failed") from exc
        except OSError as exc:
            if exc is consumer_error:
                raise
            code = (
                "ARTIFACT_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR}
                else "ARTIFACT_STORE_UNAVAILABLE"
            )
            raise OnlyResearchArtifactStoreError(code, "owning inventory read failed") from exc
        except ValueError as exc:
            if exc is consumer_error:
                raise
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", "owning inventory verification failed") from exc

    def _publish_materialized(
        self,
        manifest: OnlyResearchCalculationArtifactManifestV2,
        tables: Mapping[str, pa.Table],
        *,
        acknowledge_predecessors: Callable[[], None],
    ) -> OnlyResearchCalculationArtifactV2:
        """Internal materializer hook; no public caller-authored candidate commit."""
        if self._root.is_symlink() or not self._root.is_dir():
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", "Artifact anchor must be preprovisioned")
        try:
            with closing(_OnlyBoundPublicationTree(self._root, self._root)) as tree:
                tree.bind_directory(self._root)
                only_verify_calculation_artifact_tables_v2(manifest, tables)
                # Predecessor failure must not initialize Artifact coordination.
                # Repeat the owning checks inside exclusion and before rename.
                acknowledge_predecessors()
                with self._publication_barrier.publication_bound(tree):
                    return self._publish_under_barrier(
                        manifest, tables, acknowledge_predecessors=acknowledge_predecessors
                    )
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", str(exc)) from exc

    def _publish_under_barrier(
        self,
        manifest: OnlyResearchCalculationArtifactManifestV2,
        tables: Mapping[str, pa.Table],
        *,
        acknowledge_predecessors: Callable[[], None],
    ) -> OnlyResearchCalculationArtifactV2:
        try:
            identity = manifest.artifact_content_fingerprint
            target = self._target(identity)
            if self._root.is_symlink() or not self._root.is_dir():
                raise ValueError("Artifact durability anchor must be preprovisioned")
            acknowledge_predecessors()
            if os.path.lexists(target):
                return self._acknowledge_under_barrier(identity, manifest.result.research_result_fingerprint)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._target(identity)
            stage = target.parent / f".stage-{uuid.uuid4().hex}"
            stage.mkdir()
            try:
                physical = {}
                for path, table in tables.items():
                    output = stage / path
                    output.parent.mkdir(parents=True, exist_ok=True)
                    pq.write_table(table, output, compression=self._compression, row_group_size=self._row_group_size)
                    raw = output.read_bytes()
                    physical[path] = OnlyResearchCalculationArtifactFileV2(
                        path, hashlib.sha256(raw).hexdigest(), len(raw)
                    )
                for path, raw in _section_json(manifest).items():
                    (stage / path).write_bytes(raw)
                    physical[path] = OnlyResearchCalculationArtifactFileV2(
                        path, hashlib.sha256(raw).hexdigest(), len(raw)
                    )
                dataset = replace(
                    manifest.dataset,
                    partitions=tuple(
                        replace(item, byte_sha256=physical[f"dataset/{item.relative_path}"].byte_sha256)
                        for item in manifest.dataset.partitions
                    ),
                )
                calculations = tuple(
                    replace(
                        item,
                        value_partitions=tuple(
                            replace(
                                part,
                                byte_sha256=physical[
                                    f"calculations/{item.calculation_fingerprint}/{part.relative_path}"
                                ].byte_sha256,
                            )
                            for part in item.value_partitions
                        ),
                        readiness_partitions=tuple(
                            replace(
                                part,
                                byte_sha256=physical[
                                    f"calculations/{item.calculation_fingerprint}/{part.relative_path}"
                                ].byte_sha256,
                            )
                            for part in item.readiness_partitions
                        ),
                    )
                    for item in manifest.calculations
                )
                if self._audit_time is None:
                    raise ValueError("explicit Artifact audit-time Authority is required")
                committed = replace(
                    manifest,
                    dataset=dataset,
                    calculations=calculations,
                    files=tuple(physical[path] for path in sorted(physical)),
                    created_at=self._audit_time(),
                )
                if committed.artifact_content_fingerprint != identity:
                    raise ValueError("Artifact physical encoding changed logical identity")
                (stage / "artifact_manifest.json").write_text(
                    only_canonical_json(committed.to_dict()), encoding="utf-8"
                )
                self._read_verified(stage, identity)
                _sync_package(stage)
                # Recheck exact live predecessors immediately before publication.
                acknowledge_predecessors()
                try:
                    _rename_exclusive(stage, target)
                except OSError:
                    if not os.path.lexists(target):
                        raise
                return self._acknowledge_under_barrier(identity, manifest.result.research_result_fingerprint)
            finally:
                if stage.is_dir() and not stage.is_symlink():
                    shutil.rmtree(stage)
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", str(exc)) from exc

    @_only_barrier_publication
    def _acknowledge(self, identity: str, result_fingerprint: str) -> OnlyResearchCalculationArtifactV2:
        return self._acknowledge_under_barrier(identity, result_fingerprint)

    def _acknowledge_under_barrier(self, identity: str, result_fingerprint: str) -> OnlyResearchCalculationArtifactV2:
        target = self._target(identity)
        try:
            result = self.load_verified(identity, research_result_fingerprint=result_fingerprint)
            with _only_bind_publication_tree(target, self._root) as tree:
                tree.require_exact({"artifact_manifest.json", *(item.relative_path for item in result.manifest.files)})
                bound = self._read_verified(target, identity, tree)
                if bound.manifest != result.manifest:
                    raise ValueError("Artifact changed before acknowledgement")
                _sync_package(target, tree=tree)
                reloaded = self._read_verified(target, identity, tree)
                tree.require_namespace()
                if reloaded.manifest != bound.manifest:
                    raise ValueError("Artifact changed during acknowledgement")
                return reloaded
        except OnlyResearchArtifactStoreError:
            raise
        except (OSError, ValueError) as exc:
            raise OnlyResearchArtifactStoreError(
                "ARTIFACT_COMMIT_FAILED", "Artifact durability acknowledgement failed"
            ) from exc

    def _read_verified(
        self, root: Path, expected: str, tree: _OnlyBoundPublicationTree | None = None
    ) -> OnlyResearchCalculationArtifactV2:
        if tree is None and not os.path.lexists(root):
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", expected)
        try:
            raw = (
                _read_retained_file(root, "artifact_manifest.json", _MAX_MANIFEST_BYTES)
                if tree is None
                else tree.read_bytes("artifact_manifest.json", _MAX_MANIFEST_BYTES)
            )
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise ValueError("Artifact manifest must be an object")
            manifest = OnlyResearchCalculationArtifactManifestV2.from_dict(payload)
            if manifest.artifact_content_fingerprint != expected:
                raise ValueError("Artifact content-address relation differs")
            files = {item.relative_path: item for item in manifest.files}
            expected_files = {"artifact_manifest.json", *files}
            expected_dirs = {str(parent) for path in files for parent in Path(path).parents if str(parent) != "."}
            if tree is None:
                entries = tuple(root.rglob("*"))
                if root.is_symlink() or not root.is_dir() or any(item.is_symlink() for item in entries):
                    raise ValueError("Artifact root/file set contains symlinks")
                if (
                    {str(item.relative_to(root)) for item in entries if item.is_file()} != expected_files
                    or {str(item.relative_to(root)) for item in entries if item.is_dir()} != expected_dirs
                    or any(not item.is_file() and not item.is_dir() for item in entries)
                ):
                    raise ValueError("Artifact exact file/directory set differs")
            else:
                tree.require_exact(expected_files)
            if sum(item.byte_size for item in manifest.files) > _MAX_CONTENT_BYTES:
                raise ValueError("Artifact encoded content exceeds profile bound")
            tables = {}
            section_json = _section_json(manifest)
            section_schemas = _section_schemas(manifest)
            decoded_bytes = logical_bytes = 0
            for path, descriptor in files.items():
                schema: object
                raw = (
                    _read_retained_file(root, path, descriptor.byte_size)
                    if tree is None
                    else tree.read_bytes(path, descriptor.byte_size)
                )
                if len(raw) != descriptor.byte_size or hashlib.sha256(raw).hexdigest() != descriptor.byte_sha256:
                    raise ValueError("Artifact physical size/hash differs before decoding")
                if path in section_json:
                    if raw != section_json[path]:
                        raise ValueError("required JSON section differs from retained owning facts")
                    continue
                if path in section_schemas:
                    expected_schema, rows = section_schemas[path]
                    byte_hash, schema = (
                        descriptor.byte_sha256,
                        only_research_calculation_arrow_schema_payload(expected_schema),
                    )
                else:
                    byte_hash, rows, schema, _ = manifest.partition_descriptors[path]
                    expected_schema = (
                        manifest.dataset.dataset_schema.arrow_schema if path.startswith("dataset/") else None
                    )
                if byte_hash != descriptor.byte_sha256 or rows > _MAX_PARTITION_ROWS:
                    raise ValueError("Artifact owning partition/hash/row bound differs")
                parquet = pq.ParquetFile(pa.BufferReader(raw))
                if (
                    parquet.metadata.num_rows != rows
                    or (expected_schema is not None and parquet.schema_arrow != expected_schema)
                    or (
                        expected_schema is None
                        and only_research_calculation_arrow_schema_payload(parquet.schema_arrow) != schema
                    )
                ):
                    raise ValueError("Artifact predecode schema/count differs")
                decoded_bytes += sum(
                    parquet.metadata.row_group(group).column(column).total_uncompressed_size
                    for group in range(parquet.metadata.num_row_groups)
                    for column in range(parquet.metadata.num_columns)
                )
                if decoded_bytes > _MAX_CONTENT_BYTES:
                    raise ValueError("Artifact declared decoded content exceeds profile bound")
                batches = []
                for batch in parquet.iter_batches(batch_size=1):
                    logical_bytes += batch.nbytes
                    if logical_bytes > _MAX_CONTENT_BYTES:
                        raise ValueError("Artifact logical decoded content exceeds profile bound")
                    batches.append(batch)
                tables[path] = pa.Table.from_batches(batches, schema=parquet.schema_arrow)
            return only_verify_calculation_artifact_tables_v2(manifest, tables)
        except OnlyResearchArtifactStoreError:
            raise
        except OSError as exc:
            code = (
                "ARTIFACT_CORRUPT"
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
                else "ARTIFACT_STORE_UNAVAILABLE"
            )
            raise OnlyResearchArtifactStoreError(code, "retained package read failed") from exc
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", str(exc)) from exc

    def _target(self, identity: str) -> Path:
        if type(identity) is not str or len(identity) != 64 or any(char not in "0123456789abcdef" for char in identity):
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", "invalid content fingerprint")
        path = self._root
        mode: int | None
        for part in ("research-calculation-v2", "sha256", identity[:2], identity):
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                mode = None
            except OSError as exc:
                code = "ARTIFACT_CORRUPT" if exc.errno in {errno.ENOTDIR, errno.ELOOP} else "ARTIFACT_STORE_UNAVAILABLE"
                raise OnlyResearchArtifactStoreError(code, "Artifact namespace unavailable") from exc
            if mode is not None and not stat.S_ISDIR(mode):
                raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", "malformed Artifact namespace")
            path = path / part
        return path


def _read_retained_file(root: Path, relative: str, limit: int) -> bytes:
    """Freeze bytes through no-follow directory descriptors before native decoding."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            nested = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = nested
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(leaf, "rb") as stream:
            import stat

            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("retained leaf must be a regular file")
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("retained file exceeds exact physical bound")
        return raw
    finally:
        os.close(descriptor)


def _sync_package(root: Path, *, tree: _OnlyBoundPublicationTree | None = None) -> None:
    if tree is not None:
        tree.synchronize(_sync_directory)
        return
    entries = tuple(root.rglob("*"))
    for path in entries:
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for path in sorted((item for item in entries if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        _sync_directory(path)
    _sync_directory(root)
