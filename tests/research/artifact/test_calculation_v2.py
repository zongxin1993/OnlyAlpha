"""Portable Calculation V2 complete proof, exact selection and publication recovery."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pyarrow.parquet as pq
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.artifact import (
    OnlyParquetResearchCalculationArtifactStoreV2,
    OnlyResearchArtifactProfileReader,
    OnlyResearchCalculationArtifactMaterializerV2,
)
from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.execution_provenance import (
    OnlyResearchRuntimeExecutionProvenanceV1,
    _only_issue_research_runtime_execution_context,
)
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.result import OnlyJsonResearchResultStore, OnlyResearchResultAssembler
from onlyalpha.research.result.plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
)
from tests.quant_assets.test_retained_generation_proof import retained_proof_case
from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _registry
from tests.research.calculation.test_result_v2_store import AUDIT
from tests.support.calculation_publication_input import source_dataset, verified_test_input

pytestmark = pytest.mark.contract


def _publication(tmp_path, *, proof_case=retained_proof_case, registry=None):
    proof, graph, bindings = proof_case()
    provenance = OnlyResearchRuntimeExecutionProvenanceV1(
        proof.generation.runtime_generation_fingerprint,
        proof.validation.validation_evidence_fingerprint,
        proof.generation.core_execution.fingerprint,
        proof.generation.catalog_generation_fingerprint,
    )
    context = _only_issue_research_runtime_execution_context(provenance, graph.fingerprint, bindings)
    dataset, snapshot = source_dataset(tmp_path)
    executor = OnlyResearchCalculationExecutor(dataset, OnlyResearchCalculationBackendResolver(registry or _registry()))
    calculations = OnlyParquetResearchCalculationResultStoreV2(
        tmp_path / "calculations", dataset, audit_time=lambda: AUDIT
    )
    sealed = executor._execute_verified_v2(snapshot, graph, PUBLICATION, runtime_context=context)
    calculation = calculations.commit(sealed, graph)
    (tmp_path / "semantic").mkdir()
    evidence = OnlyResearchCalculationExecutionEvidenceStoreV2(tmp_path / "semantic", calculations)
    producer = evidence._publish_verified(sealed, calculation)
    plan = OnlyResearchResultPlan(
        (),
        4,
        snapshot,
        (OnlyResearchResultCalculationPlan(calculation.manifest.calculation_fingerprint, graph.fingerprint),),
        (),
        (
            OnlyResearchResultSeriesPlan(
                None, calculation.manifest.calculation_fingerprint, graph.nodes[0].fingerprint, "value"
            ),
        ),
        (),
        OnlyResearchCalculationPublicationSelectionV1(),
    )
    results = OnlyJsonResearchResultStore(
        tmp_path / "results", None, readiness_result_store=calculations, readiness_evidence_store=evidence
    )
    result = OnlyResearchResultAssembler(
        None, audit_time=lambda: AUDIT, readiness_result_store=calculations, readiness_evidence_store=evidence
    ).assemble(plan)
    results.commit(result)
    (tmp_path / "artifacts").mkdir()
    store = OnlyParquetResearchCalculationArtifactStoreV2(tmp_path / "artifacts", audit_time=lambda: AUDIT)
    materializer = OnlyResearchCalculationArtifactMaterializerV2(results, dataset, calculations, evidence)
    selection = ((calculation.manifest.calculation_fingerprint, producer.evidence_fingerprint),)
    verified_input = verified_test_input(
        tmp_path, plan.fingerprint, graph.fingerprint, provenance.runtime_generation_fingerprint
    )

    def publish(*, selection=selection, context=context, store=store, verified_input=verified_input):
        return materializer.publish(
            plan.fingerprint,
            selection,
            runtime_context=context,
            retained_generation=proof,
            artifact_store=store,
            verified_input=verified_input,
        )

    return publish, store, context, selection, results, evidence


def _root(tmp_path, identity):
    return tmp_path / "artifacts" / "research-calculation-v2" / "sha256" / identity[:2] / identity


def test_artifact_v2_complete_round_trip_and_legacy_locator_is_not_a_fallback(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    identity = artifact.manifest.artifact_content_fingerprint
    result_id = artifact.manifest.result.research_result_fingerprint
    assert store.load_verified(identity, research_result_fingerprint=result_id).manifest == artifact.manifest
    assert publish().manifest == artifact.manifest
    assert artifact.dataset_table.num_rows == artifact.manifest.dataset.row_count
    assert len(artifact.market_rows) == artifact.dataset_table.num_rows
    assert artifact.manifest.dataset.content_fingerprint
    assert (
        artifact.manifest.selected_evidence[0].runtime_execution_provenance
        == artifact.manifest.expected_runtime_provenance
    )
    reader = OnlyResearchArtifactProfileReader(tmp_path / "artifacts")
    assert (
        reader.load_calculation_v2_verified("RESEARCH_CALCULATION_V2", 2, result_id, identity).manifest
        == artifact.manifest
    )
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_NOT_FOUND"):
        reader.load_verified(artifact.manifest.result.research_result_fingerprint)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_PROFILE_UNSUPPORTED"):
        reader.load_calculation_v2_verified("RESEARCH_CALCULATION_V2", True, result_id, identity)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_PROVENANCE_MISMATCH"):
        store.load_verified(
            identity,
            research_result_fingerprint=result_id,
            expected_runtime_provenance=replace(
                artifact.manifest.expected_runtime_provenance, runtime_generation_fingerprint="f" * 64
            ),
        )


@pytest.mark.parametrize("selection_kind", ("missing", "duplicate", "wrong_member", "wrong_leaf", "forged_context"))
def test_artifact_selection_and_native_expectation_fail_before_publication(tmp_path, selection_kind):
    publish, _, context, selection, _, _ = _publication(tmp_path)
    if selection_kind == "forged_context":
        kwargs = {"context": replace(context)}
    else:
        selections = {
            "missing": (),
            "duplicate": (*selection, *selection),
            "wrong_member": (("f" * 64, selection[0][1]),),
            "wrong_leaf": ((selection[0][0], "f" * 64),),
        }
        kwargs = {"selection": selections[selection_kind]}
    with pytest.raises(OnlyResearchArtifactError):
        publish(**kwargs)
    assert not tuple((tmp_path / "artifacts").iterdir())


@pytest.mark.parametrize("result_id", ("f" * 64, "", None, True))
def test_artifact_v2_explicit_result_artifact_pair_cannot_be_mixed(tmp_path, result_id):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    identity = artifact.manifest.artifact_content_fingerprint
    before = {path: path.read_bytes() for path in _root(tmp_path, identity).rglob("*") if path.is_file()}
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_IDENTITY_MISMATCH"):
        store.load_verified(identity, research_result_fingerprint=result_id)
    reader = OnlyResearchArtifactProfileReader(tmp_path / "artifacts")
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_IDENTITY_MISMATCH"):
        reader.load_calculation_v2_verified("RESEARCH_CALCULATION_V2", 2, result_id, identity)
    with pytest.raises(TypeError):
        store.load_verified(identity)
    assert before == {path: path.read_bytes() for path in _root(tmp_path, identity).rglob("*") if path.is_file()}


def test_portable_artifact_copy_requires_no_upstream_runtime_or_execution(tmp_path):
    publish, _, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = tmp_path / "portable"
    shutil.copytree(tmp_path / "artifacts", root)
    source = r"""
import importlib.abc, sys
forbidden = ('onlyalpha.runtime', 'onlyalpha.application', 'onlyalpha_runtime_generation_manager',
             'onlyalpha.quant_assets.private_factor_execution', 'onlyalpha.quant_assets.example_seed')
class RejectExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(forbidden):
            raise AssertionError('offline executable import: ' + fullname)
sys.meta_path.insert(0, RejectExecution())
from pathlib import Path
from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.calculation import execution_provenance
from importlib import metadata
def fail(*args, **kwargs):
    raise AssertionError('offline execution/upstream/discovery/issuance')
metadata.entry_points = fail
OnlyResearchCalculationExecutor.execute = fail
OnlyResearchCalculationExecutor._execute_verified_v2 = fail
OnlyParquetResearchDatasetSnapshotStore.load_verified_table = fail
execution_provenance._only_issue_research_runtime_execution_context = fail
artifact = OnlyParquetResearchCalculationArtifactStoreV2(Path(sys.argv[1])).load_verified(
    sys.argv[2], research_result_fingerprint=sys.argv[3])
assert artifact.manifest.schema_version == 2
assert len(artifact.market_rows) == artifact.dataset_table.num_rows
print(artifact.manifest.artifact_content_fingerprint)
"""
    identity = artifact.manifest.artifact_content_fingerprint
    shutil.rmtree(tmp_path / "owning-input")
    (tmp_path / "source-owner.json").unlink()
    shutil.rmtree(tmp_path / "calculations")
    shutil.rmtree(tmp_path / "results")
    shutil.rmtree(tmp_path / "semantic")
    assert (
        subprocess.check_output(
            [sys.executable, "-c", source, str(root), identity, artifact.manifest.result.research_result_fingerprint],
            text=True,
        ).strip()
        == identity
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "dataset_value",
        "dataset_subprecision",
        "calculation_value",
        "readiness",
        "missing_file",
        "extra_file",
        "symlink",
        "duplicate_json",
        "missing_proof",
        "bool_version",
    ),
)
def test_artifact_rehashed_physical_and_structural_mutations_fail_closed(tmp_path, monkeypatch, mutation):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    identity = artifact.manifest.artifact_content_fingerprint
    root = _root(tmp_path, identity)
    manifest_path = root / "artifact_manifest.json"
    payload = artifact.manifest.to_dict()
    if mutation in {"dataset_value", "dataset_subprecision", "calculation_value", "readiness"}:
        prefix = "dataset/" if mutation.startswith("dataset_") else "calculations/"
        descriptor = next(
            item
            for item in payload["files"]
            if item["relative_path"].startswith(prefix)
            and (mutation != "readiness" or "/readiness/" in item["relative_path"])
            and (mutation != "calculation_value" or "/values/" in item["relative_path"])
        )
        path = root / descriptor["relative_path"]
        table = pq.read_table(path)
        column = (
            "close" if mutation.startswith("dataset_") else "value" if mutation == "calculation_value" else "readiness"
        )
        import pyarrow as pa

        values = table[column].to_pylist()
        values[0] = "READY" if mutation == "readiness" else values[0] + 1
        if mutation == "dataset_subprecision":
            from decimal import Decimal

            values[0] = table[column][0].as_py() + Decimal("1E-18")
        table = table.set_column(
            table.schema.get_field_index(column), table.schema.field(column), pa.array(values, type=table[column].type)
        )
        pq.write_table(table, path)
        raw = path.read_bytes()
        descriptor.update(byte_sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw))
        partitions = (
            payload["dataset"]["partitions"]
            if mutation.startswith("dataset_")
            else payload["calculations"][0]["readiness_partitions" if mutation == "readiness" else "value_partitions"]
        )
        partitions[0]["byte_sha256"] = descriptor["byte_sha256"]
        manifest_path.write_text(only_canonical_json(payload))
    elif mutation == "missing_file":
        (root / payload["files"][0]["relative_path"]).unlink()
    elif mutation == "extra_file":
        (root / "unexpected.json").write_text("{}")
    elif mutation == "symlink":
        path = root / payload["files"][0]["relative_path"]
        path.unlink()
        path.symlink_to(manifest_path)
    elif mutation == "duplicate_json":
        manifest_path.write_text('{"schema_version":2,' + manifest_path.read_text()[1:])
    else:
        if mutation == "bool_version":
            payload["schema_version"] = True
        else:
            payload["retained_generation"].pop("validation")
        manifest_path.write_text(only_canonical_json(payload))
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_verified(identity, research_result_fingerprint=artifact.manifest.result.research_result_fingerprint)
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    with pytest.raises(OnlyResearchArtifactError):
        publish()
    assert before == {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def test_artifact_physical_hash_is_checked_before_parquet_decoder(tmp_path, monkeypatch):
    from onlyalpha.research.artifact import calculation_v2_store

    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    identity = artifact.manifest.artifact_content_fingerprint
    path = _root(tmp_path, identity) / artifact.manifest.files[0].relative_path
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)
    monkeypatch.setattr(
        calculation_v2_store.pq, "ParquetFile", lambda *_: pytest.fail("corrupt physical bytes reached native decoder")
    )
    with pytest.raises(OnlyResearchArtifactError, match="physical size/hash"):
        store.load_verified(identity, research_result_fingerprint=artifact.manifest.result.research_result_fingerprint)


def test_artifact_equal_concurrent_publish_and_sync_failure_reentry(tmp_path, monkeypatch):
    from onlyalpha.research.artifact import calculation_v2_store

    publish, store, _, _, _, _ = _publication(tmp_path)
    barrier = Barrier(2)
    original = calculation_v2_store._rename_exclusive

    def raced(source, target):
        barrier.wait(timeout=20)
        return original(source, target)

    monkeypatch.setattr(calculation_v2_store, "_rename_exclusive", raced)
    with ThreadPoolExecutor(2) as pool:
        winners = tuple(pool.map(lambda _: publish(), range(2)))
    assert winners[0].manifest == winners[1].manifest
    monkeypatch.setattr(calculation_v2_store, "_rename_exclusive", original)
    sync = calculation_v2_store._sync_directory

    def unavailable(_, **kwargs):
        raise OSError("controlled acknowledgement failure")

    monkeypatch.setattr(calculation_v2_store, "_sync_directory", unavailable)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_COMMIT_FAILED"):
        publish()
    assert (
        store.load_verified(
            winners[0].manifest.artifact_content_fingerprint,
            research_result_fingerprint=winners[0].manifest.result.research_result_fingerprint,
        ).manifest
        == winners[0].manifest
    )
    monkeypatch.setattr(calculation_v2_store, "_sync_directory", sync)
    assert publish().manifest == winners[0].manifest
