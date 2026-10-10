"""Sealed, verified and exclusively published immutable Parquet Result V2."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import OnlyCalculationDefinition, OnlyFactorKind, only_calculation_execution_shape
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research._durability import _only_bind_publication_tree, _OnlyBoundPublicationTree
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.source_cut import OnlySourcePublicationBarrier, _only_barrier_publication

from .errors import OnlyResearchCalculationResultStoreError
from .execution import (
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationNodeOutput,
    OnlyResearchCalculationNodeReadiness,
    _only_require_verified_research_calculation_execution_v2,
    _OnlyVerifiedResearchCalculationExecutionV2,
    _validate_outputs,
)
from .identity import only_research_calculation_fingerprint
from .publication import OnlyResearchCalculationPublicationContract
from .readiness import OnlyResearchOutputReadiness, only_validate_research_output_readiness
from .result import OnlyResearchCalculationResultPartitionManifest
from .result_store import (
    _canonical_outputs,
    _canonical_table,
    _expected_axes,
    _expected_partition_keys,
    _sha,
    _tables_equal,
    _valid_sha,
)
from .result_v2 import (
    OnlyResearchCalculationResultManifestV2,
    OnlyResearchCalculationResultV2,
    OnlyResearchCalculationResultVerificationV2,
    _logical,
)
from .result_v2_identity import (
    _descriptor,
    only_research_calculation_result_content_fingerprint_v2,
    only_research_calculation_result_fingerprint_v2,
    only_research_calculation_value_projection_fingerprint,
)


class OnlyParquetResearchCalculationResultStoreV2:
    def __init__(
        self,
        root: Path,
        dataset_store: OnlyResearchDatasetSnapshotStore,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._dataset_store = dataset_store
        self._compression = compression
        self._row_group_size = row_group_size
        self._audit_time = audit_time
        self._publication_barrier = OnlySourcePublicationBarrier(root)

    def exists(self, calculation_fingerprint: str) -> bool:
        target = self._target(calculation_fingerprint)
        if not _present(target):
            return False
        self._read_verified(target, calculation_fingerprint)
        return True

    def commit(
        self, verified_execution: _OnlyVerifiedResearchCalculationExecutionV2, graph: OnlyCalculationGraphDefinition
    ) -> OnlyResearchCalculationResultV2:
        _only_require_verified_research_calculation_execution_v2(verified_execution)
        # Deployment preprovisions this anchor; the Store may create its root,
        # but never owns creation or durability of ancestors above the anchor.
        authority_parent = self._root.parent
        if authority_parent.is_symlink() or not authority_parent.is_dir():
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", "authority parent must be a real directory")
        try:
            with closing(_OnlyBoundPublicationTree(self._root, authority_parent)) as tree:
                tree.bind_directory(authority_parent)
                result = self._commit_with_parent(verified_execution, graph, tree)
                tree.require_namespace()
                return result
        except OnlyResearchCalculationResultStoreError:
            raise
        except (OSError, ValueError) as exc:
            raise OnlyResearchCalculationResultStoreError(
                "RESULT_COMMIT_FAILED", "owning parent binding failed"
            ) from exc

    def _commit_with_parent(
        self,
        verified_execution: _OnlyVerifiedResearchCalculationExecutionV2,
        graph: OnlyCalculationGraphDefinition,
        tree: _OnlyBoundPublicationTree,
    ) -> OnlyResearchCalculationResultV2:
        execution = _only_require_verified_research_calculation_execution_v2(verified_execution)
        try:
            if execution.calculation_graph_fingerprint != graph.fingerprint:
                raise ValueError("sealed Graph linkage mismatch")
            if execution.calculation_fingerprint != only_research_calculation_fingerprint(
                execution.dataset_snapshot_fingerprint, graph.fingerprint
            ):
                raise ValueError("sealed Calculation linkage mismatch")
            if tuple(item.node_fingerprint for item in execution.research_implementation_bindings) != tuple(
                sorted(node.fingerprint for node in graph.nodes)
            ):
                raise ValueError("sealed producer node membership mismatch")
            OnlyResearchCalculationPublicationContract.from_dict(execution.publication.to_dict())
            axes = self._source(execution.dataset_snapshot_fingerprint, graph)
            outputs = _canonical_outputs(execution.outputs, graph, axes)
            readiness = _canonical_readiness(execution.readiness, outputs, graph, axes)
            values_logical = tuple(
                _descriptor(item.node_fingerprint, item.instrument_id, item.table) for item in outputs
            )
            readiness_logical = tuple(
                _descriptor(item.node_fingerprint, item.instrument_id, item.table, readiness=True) for item in readiness
            )
            content = only_research_calculation_result_content_fingerprint_v2(values_logical, readiness_logical)
            result_id = only_research_calculation_result_fingerprint_v2(execution.calculation_fingerprint, content)
            created_at = self._audit_timestamp()
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", str(exc)) from exc
        self._acknowledge_dataset(execution.dataset_snapshot_fingerprint)
        tree.create_directory(self._root)
        with self._publication_barrier.publication_bound(tree):
            target = self._target(execution.calculation_fingerprint)
            if _present(target):
                return self._resolve_existing(execution.calculation_fingerprint, content)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._target(execution.calculation_fingerprint)
            stage = target.parent / f".stage-{uuid.uuid4().hex}"
            stage.mkdir()
            try:
                families = []
                sections: tuple[
                    tuple[str, tuple[OnlyResearchCalculationNodeOutput | OnlyResearchCalculationNodeReadiness, ...]],
                    ...,
                ] = (("values", outputs), ("readiness", readiness))
                for name, partitions in sections:
                    (stage / name).mkdir()
                    descriptors = []
                    for index, item in enumerate(partitions):
                        relative = f"{name}/p-{index:06d}.parquet"
                        path = stage / relative
                        pq.write_table(
                            item.table, path, compression=self._compression, row_group_size=self._row_group_size
                        )
                        if not _tables_equal(pq.read_table(path), item.table):
                            raise ValueError("Parquet logical round-trip mismatch")
                        node, instrument, rows, semantic, schema = _descriptor(
                            item.node_fingerprint, item.instrument_id, item.table, readiness=name == "readiness"
                        )
                        descriptors.append(
                            OnlyResearchCalculationResultPartitionManifest(
                                node, instrument, rows, schema, semantic, relative, _sha(path)
                            )
                        )
                    families.append(tuple(descriptors))
                manifest = OnlyResearchCalculationResultManifestV2(
                    execution.calculation_fingerprint,
                    execution.dataset_snapshot_fingerprint,
                    graph.fingerprint,
                    graph,
                    only_research_calculation_value_projection_fingerprint(values_logical),
                    content,
                    result_id,
                    families[0],
                    families[1],
                    created_at,
                )
                (stage / "manifest.json").write_text(
                    json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                try:
                    self._read_verified(stage, execution.calculation_fingerprint)
                except OnlyResearchCalculationResultStoreError as exc:
                    raise OnlyResearchCalculationResultStoreError(
                        "RESULT_COMMIT_FAILED", "staged verification failed"
                    ) from exc
                _sync_tree(stage)
                try:
                    _rename_exclusive(stage, target)
                except OSError:
                    # A race loser has no authority to replace or repair its winner.
                    if not _present(target):
                        raise
                    return self._resolve_existing(execution.calculation_fingerprint, content)
                return self._resolve_existing(execution.calculation_fingerprint, content)
            except OnlyResearchCalculationResultStoreError:
                raise
            except Exception as exc:
                raise OnlyResearchCalculationResultStoreError("RESULT_COMMIT_FAILED", str(exc)) from exc
            finally:
                if stage.is_dir():
                    shutil.rmtree(stage)

    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultV2:
        return self._read_verified(self._target(calculation_fingerprint), calculation_fingerprint)

    @contextmanager
    def inspect_verified(self, calculation_fingerprint: str) -> Iterator[OnlyResearchCalculationResultV2]:
        """Retain the complete Result and owning Dataset, without durability acknowledgement."""
        from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore

        if not isinstance(self._dataset_store, OnlyParquetResearchDatasetSnapshotStore):
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", "scoped Dataset reader required")
        target = self._target(calculation_fingerprint)
        consumer_error: BaseException | None = None
        try:
            with closing(_OnlyBoundPublicationTree(target, self._root)) as tree:
                try:
                    tree.bind_directory(self._root)
                except FileNotFoundError as exc:
                    raise OnlyResearchCalculationResultStoreError(
                        "RESULT_STORE_UNAVAILABLE", "owning root missing"
                    ) from exc
                if not tree.bind_existing_target():
                    raise OnlyResearchCalculationResultStoreError("RESULT_NOT_FOUND", calculation_fingerprint)
                original_manifest = tree.read_bytes("manifest.json")
                payload = json.loads(original_manifest, object_pairs_hook=_unique_object)
                if not isinstance(payload, dict):
                    raise ValueError("manifest must be an object")
                manifest = OnlyResearchCalculationResultManifestV2.from_dict(payload)
                tree.require_exact(
                    {
                        "manifest.json",
                        *(part.relative_path for part in (*manifest.value_partitions, *manifest.readiness_partitions)),
                    }
                )
                with self._dataset_store.inspect_verified_table(manifest.dataset_snapshot_fingerprint) as dataset:
                    result = self._read_verified(target, calculation_fingerprint, tree, dataset)
                    tree.require_namespace()
                    try:
                        yield result
                    except BaseException as exc:
                        consumer_error = exc
                        raise
                    if tree.read_bytes("manifest.json") != original_manifest:
                        raise ValueError("Calculation manifest changed in place during inspection")
                    reloaded = self._read_verified(target, calculation_fingerprint, tree, dataset)
                    if reloaded.manifest != result.manifest:
                        raise ValueError("Calculation changed during inspection")
                    tree.require_namespace()
        except (OSError, ValueError) as exc:
            if exc is consumer_error:
                raise
            code = (
                "RESULT_STORE_UNAVAILABLE"
                if isinstance(exc, OSError)
                and exc.errno not in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR}
                else "RESULT_CORRUPT"
            )
            raise OnlyResearchCalculationResultStoreError(code, "scoped Result binding failed") from exc

    @_only_barrier_publication
    def acknowledge_exact(
        self, calculation_fingerprint: str, result_fingerprint: str
    ) -> OnlyResearchCalculationResultV2:
        result = self.load_verified(calculation_fingerprint)
        if result.manifest.calculation_result_fingerprint != result_fingerprint:
            raise OnlyResearchCalculationResultStoreError("DETERMINISTIC_RESULT_CONFLICT", calculation_fingerprint)
        return self._resolve_existing(calculation_fingerprint, result.manifest.result_content_fingerprint)

    def verify(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultVerificationV2:
        manifest = self.load_verified(calculation_fingerprint).manifest
        return OnlyResearchCalculationResultVerificationV2(
            True,
            calculation_fingerprint,
            manifest.calculation_result_fingerprint,
            len(manifest.value_partitions),
            sum(item.row_count for item in manifest.value_partitions),
            sum(item.row_count for item in manifest.readiness_partitions),
        )

    def _resolve_existing(self, fingerprint: str, content: str) -> OnlyResearchCalculationResultV2:
        result = self.load_verified(fingerprint)
        if result.manifest.result_content_fingerprint != content:
            raise OnlyResearchCalculationResultStoreError("DETERMINISTIC_RESULT_CONFLICT", fingerprint)
        self._acknowledge_dataset(result.manifest.dataset_snapshot_fingerprint)
        # Readability is not durability. A peer or UNKNOWN rename may have made
        # the exact root visible before synchronizing its namespace links.
        target = self._target(fingerprint)
        try:
            with _only_bind_publication_tree(target, self._root.parent) as tree:
                tree.require_exact(
                    {
                        "manifest.json",
                        *(
                            item.relative_path
                            for item in (*result.manifest.value_partitions, *result.manifest.readiness_partitions)
                        ),
                    }
                )
                bound = self._read_verified(target, fingerprint, tree)
                if bound.manifest != result.manifest:
                    raise ValueError("Calculation Result changed before acknowledgement")
                tree.synchronize(_sync_directory)
                reloaded = self._read_verified(target, fingerprint, tree)
                tree.require_namespace()
                if reloaded.manifest != bound.manifest:
                    raise ValueError("Calculation Result changed during acknowledgement")
                return reloaded
        except (OSError, ValueError) as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_COMMIT_FAILED", "publication sync failed") from exc

    def _acknowledge_dataset(self, fingerprint: str) -> None:
        try:
            verified = self._dataset_store.acknowledge_exact(fingerprint)
            if verified.snapshot.snapshot_fingerprint != fingerprint:
                raise ValueError("Dataset acknowledgement identity differs")
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError(
                "RESULT_COMMIT_FAILED", "Dataset acknowledgement failed"
            ) from exc

    def _source(
        self,
        fingerprint: str,
        graph: OnlyCalculationGraphDefinition,
        verified: OnlyVerifiedResearchDataset | None = None,
    ) -> dict[str, tuple[int, ...]]:
        if (
            len(graph.nodes) != 1
            or only_calculation_execution_shape(graph.nodes[0].definition) is not OnlyFactorKind.TIME_SERIES
        ):
            raise ValueError("V2 requires one TIME_SERIES node")
        if verified is None:
            verified = self._dataset_store.load_verified_table(fingerprint)
        if verified.snapshot.snapshot_fingerprint != fingerprint:
            raise ValueError("upstream Dataset identity mismatch")
        # Revalidate actual source contracts, not only matching row counts/timestamps.
        definition = graph.nodes[0].definition
        OnlyResearchCalculationExecutor._resolve_instrument_inputs(
            definition, verified.table, verified.snapshot.dataset_schema, {}, ""
        )
        return _expected_axes(verified.table)

    def _read_verified(
        self,
        root: Path,
        expected: str,
        tree: _OnlyBoundPublicationTree | None = None,
        dataset: OnlyVerifiedResearchDataset | None = None,
    ) -> OnlyResearchCalculationResultV2:
        if tree is None and not _present(root):
            raise OnlyResearchCalculationResultStoreError("RESULT_NOT_FOUND", expected)
        try:
            if tree is None and (
                root.is_symlink()
                or not root.is_dir()
                or {item.name for item in root.iterdir()} != {"values", "readiness", "manifest.json"}
            ):
                raise ValueError("malformed Result root")
            manifest_path = root / "manifest.json"
            if tree is None and (manifest_path.is_symlink() or not manifest_path.is_file()):
                raise ValueError("malformed manifest file")
            raw_manifest = manifest_path.read_bytes() if tree is None else tree.read_bytes("manifest.json")
            payload = json.loads(raw_manifest, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            manifest = OnlyResearchCalculationResultManifestV2.from_dict(payload)
            if manifest.calculation_fingerprint != expected:
                raise ValueError("Result path identity mismatch")
            axes = self._source(manifest.dataset_snapshot_fingerprint, manifest.calculation_graph, dataset)
            expected_keys = _expected_partition_keys(manifest.calculation_graph, axes)
            outputs = []
            readiness = []
            for family, partitions in (
                ("values", manifest.value_partitions),
                ("readiness", manifest.readiness_partitions),
            ):
                folder = root / family
                if tree is None and (folder.is_symlink() or not folder.is_dir()):
                    raise ValueError("malformed partition directory")
                if tuple((item.node_fingerprint, item.instrument_id) for item in partitions) != expected_keys:
                    raise ValueError("partition membership mismatch")
                if tree is None and {item.name for item in folder.iterdir()} != {
                    Path(item.relative_path).name for item in partitions
                }:
                    raise ValueError("unexpected/missing partition entry")
                for item in partitions:
                    path = root / item.relative_path
                    if tree is None:
                        if path.is_symlink() or not path.is_file() or _sha(path) != item.byte_sha256:
                            raise ValueError("partition physical integrity mismatch")
                        table = pq.read_table(path)
                    else:
                        import hashlib

                        raw = tree.read_bytes(item.relative_path)
                        if hashlib.sha256(raw).hexdigest() != item.byte_sha256:
                            raise ValueError("partition physical integrity mismatch")
                        table = pq.read_table(pa.BufferReader(raw))
                    descriptor = _descriptor(
                        item.node_fingerprint, item.instrument_id, table, readiness=family == "readiness"
                    )
                    if descriptor != _logical((item,))[0]:
                        raise ValueError("partition logical identity/schema/count mismatch")
                    if family == "values":
                        canonical = _canonical_table(
                            manifest.calculation_graph.nodes[0].definition, table, axes[item.instrument_id]
                        )
                        if not _tables_equal(canonical, table):
                            raise ValueError("noncanonical values schema")
                        outputs.append(
                            OnlyResearchCalculationNodeOutput(item.node_fingerprint, item.instrument_id, table)
                        )
                    else:
                        readiness.append(
                            OnlyResearchCalculationNodeReadiness(item.node_fingerprint, item.instrument_id, table)
                        )
            _canonical_readiness(tuple(readiness), tuple(outputs), manifest.calculation_graph, axes)
            return OnlyResearchCalculationResultV2(manifest, tuple(outputs), tuple(readiness))
        except Exception as exc:
            raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", "invalid Calculation fingerprint")
        path = self._root
        for part in ("v2", "sha256", fingerprint[:2], fingerprint):
            if _present(path) and (path.is_symlink() or not path.is_dir()):
                raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", "malformed authority directory")
            path = path / part
        return path

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise ValueError("explicit audit time required")
        value = self._audit_time()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("audit time must be timezone-aware UTC")
        return value


def _canonical_readiness(
    raw: tuple[OnlyResearchCalculationNodeReadiness, ...],
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...],
    graph: OnlyCalculationGraphDefinition,
    axes: dict[str, tuple[int, ...]],
) -> tuple[OnlyResearchCalculationNodeReadiness, ...]:
    by_key = {(item.node_fingerprint, item.instrument_id): item for item in raw}
    keys = _expected_partition_keys(graph, axes)
    if len(by_key) != len(raw) or tuple(sorted(by_key)) != keys:
        raise ValueError("readiness partition bijection mismatch")
    definition = graph.nodes[0].definition
    for output in outputs:
        table = by_key[(output.node_fingerprint, output.instrument_id)].table
        _validate_pair(definition, output.table, table, axes[output.instrument_id])
    return tuple(by_key[key] for key in keys)


def _validate_pair(
    definition: OnlyCalculationDefinition, values: pa.Table, readiness: pa.Table, axis: tuple[int, ...]
) -> None:
    schema = pa.schema(
        [
            pa.field("ts_event_ns", pa.int64(), False),
            pa.field("output_name", pa.string(), False),
            pa.field("readiness", pa.string(), False),
            pa.field("reason", pa.string(), False),
        ]
    )
    if not isinstance(readiness, pa.Table) or not readiness.schema.equals(schema, check_metadata=True):
        raise ValueError("readiness schema mismatch")
    names = sorted(item.name for item in definition.outputs)
    if list(zip(readiness["output_name"].to_pylist(), readiness["ts_event_ns"].to_pylist(), strict=True)) != [
        (name, ts) for name in names for ts in axis
    ]:
        raise ValueError("readiness output/timestamp axis mismatch")
    carriers = {}
    for index, name in enumerate(names):
        selected = readiness.slice(index * len(axis), len(axis))
        carriers[name] = OnlyResearchOutputReadiness(selected["readiness"], selected["reason"])
    output_arrays = {name: values[name] for name in names}
    _validate_outputs(definition, output_arrays, len(axis))
    only_validate_research_output_readiness(definition, output_arrays, carriers, row_count=len(axis))


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", "authority entry unavailable") from exc
    return True


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _rename_exclusive(source: Path, target: Path) -> None:
    """Native no-replace rename: even an empty raced directory is immutable."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "linux":
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        status = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # AT_FDCWD / RENAME_NOREPLACE
    elif sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        status = rename(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    else:
        raise OSError("exclusive directory rename unavailable")
    if status != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def _sync_directory(path: Path, *, descriptor: int | None = None) -> None:
    if descriptor is not None:
        os.fsync(descriptor)
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for family in ("values", "readiness"):
        _sync_directory(root / family)
    _sync_directory(root)
