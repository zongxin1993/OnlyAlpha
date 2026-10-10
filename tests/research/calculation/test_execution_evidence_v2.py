from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pyarrow as pa
import pytest

from onlyalpha.research.calculation.errors import OnlyResearchCalculationError, OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.execution_evidence_v2 import (
    OnlyResearchCalculationExecutionEvidenceStoreV2,
    OnlyResearchCalculationExecutionEvidenceV2,
)
from onlyalpha.research.calculation.readiness import OnlyResearchOutputReadiness
from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _AtomicBackend, _registry, _setup
from tests.research.calculation.test_result_v2_store import _case as _result_case


def test_v2_process_death_before_rename_does_not_poison_fresh_process_query_or_retry(tmp_path):
    code = """
import os, sys
from pathlib import Path
import onlyalpha.research.calculation.execution_evidence_v2 as module
from tests.research.calculation.test_execution_evidence_v2 import _case
_, _, _, sealed, result, store = _case(Path(sys.argv[1]))
module._rename_exclusive = lambda source, target: os._exit(86)
store._publish_verified(sealed, result)
"""
    process = subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=False)
    assert process.returncode == 86
    # Verify query semantics first so the baseline proves the persistent defect,
    # not merely the old staging layout.
    retry = """
import sys
from pathlib import Path
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
from tests.research.calculation.test_execution_evidence_v2 import _case
_, _, _, sealed, result, store = _case(Path(sys.argv[1]))
try:
    store.require_for_result(result)
except OnlyResearchCalculationError as exc:
    assert exc.code == 'RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND', str(exc)
else:
    raise AssertionError('unpublished stage became Evidence')
evidence = store._publish_verified(sealed, result)
assert store.require_for_result(result) == evidence
assert store.exists(evidence.evidence_fingerprint)
assert store.load_verified(evidence.evidence_fingerprint) == evidence
"""
    subprocess.run([sys.executable, "-c", retry, str(tmp_path)], check=True)
    v2 = tmp_path / "semantic" / "calculation-execution-evidence" / "v2"
    orphans = list((v2 / ".staging").iterdir())
    assert len(orphans) == 1
    assert orphans[0].name.startswith(".stage-")
    assert (orphans[0] / "manifest.json").is_file()
    assert not list((v2 / "sha256").rglob(".stage-*"))


@pytest.mark.parametrize("name", (".stage-forged", "junk"))
def test_v2_authoritative_prefix_never_ignores_stage_like_or_nonfingerprint_entries(tmp_path, name):
    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    (_root(tmp_path, evidence).parent / name).mkdir()
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store.require_for_result(result)


@pytest.mark.parametrize("kind", ("file", "symlink", "dangling-symlink"))
def test_v2_staging_root_must_be_real_directory(tmp_path, kind):
    _, _, _, sealed, result, store = _case(tmp_path)
    stage = tmp_path / "semantic" / "calculation-execution-evidence" / "v2" / ".staging"
    stage.parent.mkdir(parents=True)
    if kind == "file":
        stage.write_bytes(b"untouched")
    else:
        stage.symlink_to(tmp_path / ("semantic" if kind == "symlink" else "missing"))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store._publish_verified(sealed, result)
    assert not _root(tmp_path, _model(sealed, result)).exists()
    if kind == "file":
        assert stage.read_bytes() == b"untouched"
    else:
        assert stage.is_symlink()


@pytest.mark.parametrize("unknown", (False, True))
def test_v2_staging_sync_failure_cannot_acknowledge_visible_target(tmp_path, monkeypatch, unknown):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = _model(sealed, result)
    root = _root(tmp_path, evidence)
    staging = root.parent.parent.parent / ".staging"
    sync, rename = module._sync_directory, module._rename_exclusive

    def publish(source, target):
        assert source.parent == staging
        assert source.parent.stat().st_dev == target.parent.stat().st_dev
        rename(source, target)
        if unknown:
            raise OSError("rename acknowledgement lost")

    def fail(path, **kwargs):
        if path == staging:
            raise OSError("source namespace sync failed")
        sync(path, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(module, "_rename_exclusive", publish)
        context.setattr(module, "_sync_directory", fail)
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
            store._publish_verified(sealed, result)
        before = (root / "manifest.json").read_bytes()
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
            store._publish_verified(sealed, result)
    assert store._publish_verified(sealed, result) == evidence
    assert (root / "manifest.json").read_bytes() == before


def _case(tmp_path, registry=None):
    executor, results, graph, sealed = _result_case(tmp_path, registry)
    result = results.commit(sealed, graph)
    semantic = tmp_path / "semantic"
    semantic.mkdir(exist_ok=True)
    store = OnlyResearchCalculationExecutionEvidenceStoreV2(semantic, results)
    return executor, results, graph, sealed, result, store


def _model(sealed, result, generation=None):
    manifest = result.manifest
    return OnlyResearchCalculationExecutionEvidenceV2(
        manifest.calculation_fingerprint,
        manifest.dataset_snapshot_fingerprint,
        manifest.calculation_graph_fingerprint,
        manifest.calculation_result_fingerprint,
        manifest.result_content_fingerprint,
        sealed.execution.research_implementation_bindings,
        generation,
    )


def _root(tmp_path, evidence):
    fingerprint = evidence.evidence_fingerprint
    return tmp_path / "semantic" / "calculation-execution-evidence" / "v2" / "sha256" / fingerprint[:2] / fingerprint


def test_v2_exact_inspection_is_read_only_and_acknowledgement_remains_separate(tmp_path, monkeypatch):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only inspection acknowledged or published")

    with monkeypatch.context() as scope:
        scope.setattr(store, "_acknowledge", forbidden)
        scope.setattr(store, "_publish", forbidden)
        scope.setattr(store._result_store, "commit", forbidden)
        scope.setattr("onlyalpha.research.calculation.execution_evidence_v2.os.fsync", forbidden)
        assert (
            store.load_exact_for_result(calculation, producer.research_implementation_bindings, context.provenance)
            == producer
        )
        with pytest.raises(AssertionError, match="read-only inspection acknowledged or published"):
            store.require_exact_for_result(calculation, producer.research_implementation_bindings, context.provenance)
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "field",
    [
        "runtime_generation_fingerprint",
        "validation_evidence_fingerprint",
        "core_execution_fingerprint",
        "catalog_generation_fingerprint",
    ],
)
def test_v2_read_only_exact_inspection_never_selects_a_complete_different_producer(tmp_path, field):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    different = replace(context.provenance, **{field: "f" * 64})
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"):
        store.load_exact_for_result(calculation, producer.research_implementation_bindings, different)


def test_v2_read_only_exact_inspection_rejects_relevant_missing_runtime_proof(tmp_path):
    from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1

    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
        store.load_exact_for_result(
            result,
            producer.research_implementation_bindings,
            OnlyResearchRuntimeExecutionProvenanceV1("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )


@pytest.mark.parametrize("expectation", [None, {}, True])
def test_v2_exact_inspection_cannot_select_unattested_evidence_without_runtime_expectation(tmp_path, expectation):
    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    for action in (store.load_exact_for_result, store.require_exact_for_result):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
            action(result, producer.research_implementation_bindings, expectation)


def test_v2_exact_inspection_unavailable_anchor_is_not_missing(tmp_path):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    store._semantic_root.rename(tmp_path / "unavailable")
    for action in (store.load_exact_for_result, store.require_exact_for_result):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"):
            action(calculation, producer.research_implementation_bindings, context.provenance)
    assert not store._semantic_root.exists()


@pytest.mark.parametrize("point", ["lookup", "open", "read"])
@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_v2_exact_inspection_io_error_is_unavailable_not_missing_or_corrupt(tmp_path, monkeypatch, point, error):
    import onlyalpha.research._durability as durability
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    reload_result = store._reload_result

    # Inject only after the distinct Calculation owning reader has succeeded.
    def inject(result):
        loaded = reload_result(result)
        if point == "lookup":
            original = Path.lstat

            def fail_lookup(path, *args, **kwargs):
                if path == store._semantic_root:
                    raise OSError(error, "injected Evidence lookup IO")
                return original(path, *args, **kwargs)

            monkeypatch.setattr(Path, "lstat", fail_lookup)
        else:

            def fail(*args, **kwargs):
                raise OSError(error, "injected Evidence descriptor IO")

            if point == "open":
                monkeypatch.setattr(durability.os, "open", fail)
            else:
                monkeypatch.setattr(durability._OnlyBoundPublicationTree, "read_bytes", fail)
        return loaded

    monkeypatch.setattr(store, "_reload_result", inject)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"):
        store.load_exact_for_result(calculation, producer.research_implementation_bindings, context.provenance)


def test_v2_exact_inspection_available_empty_namespace_is_local_not_found(tmp_path):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    store._semantic_root.rename(tmp_path / "saved")
    store._semantic_root.mkdir()
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"):
        store.load_exact_for_result(calculation, producer.research_implementation_bindings, context.provenance)
    assert not tuple(store._semantic_root.iterdir())


def test_v2_exact_inspection_missing_authoring_is_incomplete_before_runtime_equality(tmp_path):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    different = replace(context.provenance, runtime_generation_fingerprint="f" * 64)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
        store.load_exact_for_result(calculation, producer.research_implementation_bindings, different, "a" * 64)


def test_v2_exact_miss_cannot_lose_incomplete_proof_when_anchor_disappears_before_scan(tmp_path, monkeypatch):
    from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1

    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    target = store._target

    def lose_anchor(identity):
        path = target(identity)
        if identity == "0" * 64:
            store._semantic_root.rename(tmp_path / "unavailable")
        return path

    monkeypatch.setattr(store, "_target", lose_anchor)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_STORE_UNAVAILABLE"):
        store.load_exact_for_result(
            result,
            producer.research_implementation_bindings,
            OnlyResearchRuntimeExecutionProvenanceV1("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )


def test_v2_retained_scan_never_uses_unbound_pathname_reads(tmp_path, monkeypatch):
    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)

    def forbidden(*args, **kwargs):
        raise AssertionError("retained scan used an unbound pathname read")

    monkeypatch.setattr(Path, "read_text", forbidden)
    assert tuple(store._iter_retained()) == (producer,)


@pytest.mark.parametrize("mutation", ["inode", "symlink", "fifo"])
def test_v2_retained_scan_rejects_manifest_substitution_after_bound_read(tmp_path, monkeypatch, mutation):
    import onlyalpha.research._durability as durability

    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    target = store._target(producer.evidence_fingerprint)
    manifest = target / "manifest.json"
    read = durability._OnlyBoundPublicationTree.read_bytes
    substituted = False

    def substitute(tree, relative, *args, **kwargs):
        nonlocal substituted
        raw = read(tree, relative, *args, **kwargs)
        if relative.endswith(f"{producer.evidence_fingerprint}/manifest.json") and not substituted:
            substituted = True
            saved = target.parent / "original-manifest"
            manifest.rename(saved)
            if mutation == "inode":
                manifest.write_bytes(saved.read_bytes())
            elif mutation == "symlink":
                manifest.symlink_to(saved)
            else:
                os.mkfifo(manifest)
        return raw

    # Guard flags before the real FIFO open, so a broken implementation cannot
    # make this correctness test block or require a timing-based assertion.
    original_open = durability.os.open

    def guarded_open(path, flags, *args, **kwargs):
        if mutation == "fifo" and path == "manifest.json":
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(durability._OnlyBoundPublicationTree, "read_bytes", substitute)
    monkeypatch.setattr(durability.os, "open", guarded_open)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store._iter_retained()


@pytest.mark.parametrize("action", ["load", "exact"])
@pytest.mark.parametrize("entry", ["manifest", "target", "prefix"])
def test_v2_evidence_binding_survives_full_owning_result_verification(tmp_path, monkeypatch, action, entry):
    from tests.research.artifact.test_calculation_v2 import _publication

    _, _, context, selection, _, store = _publication(tmp_path)
    calculation = store._result_store.load_verified(selection[0][0])
    producer = store.load_verified(selection[0][1])
    target = store._target(producer.evidence_fingerprint)
    path = {"manifest": target / "manifest.json", "target": target, "prefix": target.parent}[entry]
    load_result = store._result_store.load_verified
    reads = 0

    def substitute(*args, **kwargs):
        nonlocal reads
        loaded = load_result(*args, **kwargs)
        reads += 1
        if reads == (2 if action == "exact" else 1):
            saved = path.with_name(".original")
            path.rename(saved)
            if saved.is_dir():
                shutil.copytree(saved, path)
                shutil.rmtree(saved)
            else:
                path.write_bytes(saved.read_bytes())
                saved.unlink()
        return loaded

    monkeypatch.setattr(store._result_store, "load_verified", substitute)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        if action == "load":
            store.load_verified(producer.evidence_fingerprint)
        else:
            store.load_exact_for_result(calculation, producer.research_implementation_bindings, context.provenance)


def test_v2_bound_evidence_read_preserves_owning_result_error(tmp_path, monkeypatch):
    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    fault = OnlyResearchCalculationResultStoreError("RESEARCH_RESULT_UNAVAILABLE", "owning reader")

    def unavailable(*args, **kwargs):
        raise fault

    monkeypatch.setattr(store._result_store, "load_verified", unavailable)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as observed:
        store.load_verified(producer.evidence_fingerprint)
    assert observed.value is fault


def test_v2_retained_scan_fifo_is_rejected_without_blocking_open(tmp_path, monkeypatch):
    import onlyalpha.research._durability as durability

    _, _, _, sealed, result, store = _case(tmp_path)
    producer = store._publish_verified(sealed, result)
    manifest = store._target(producer.evidence_fingerprint) / "manifest.json"
    manifest.unlink()
    os.mkfifo(manifest)
    original_open = durability.os.open

    def guarded_open(path, flags, *args, **kwargs):
        if path == "manifest.json":
            assert flags & os.O_NONBLOCK
            assert flags & os.O_NOFOLLOW
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(durability.os, "open", guarded_open)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store._iter_retained()


def test_v2_evidence_strict_round_trip_binds_versions_result_and_implementation(tmp_path):
    _, _, _, sealed, result, _ = _case(tmp_path)
    evidence = _model(sealed, result)
    assert OnlyResearchCalculationExecutionEvidenceV2.from_dict(evidence.to_dict()) == evidence
    assert evidence.schema_version == evidence.calculation_result_schema_version == 2
    assert evidence.readiness_contract_version == 1
    assert evidence.execution_contract_version == "RESEARCH_CALCULATION_EXECUTION_V2"
    assert evidence.calculation_result_fingerprint == result.manifest.calculation_result_fingerprint
    assert evidence.research_implementation_bindings == sealed.execution.research_implementation_bindings


@pytest.mark.parametrize(
    "field",
    (
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
    ),
)
def test_v2_evidence_every_field_is_mandatory(tmp_path, field):
    _, _, _, sealed, result, _ = _case(tmp_path)
    payload = _model(sealed, result).to_dict()
    del payload[field]
    with pytest.raises(ValueError):
        OnlyResearchCalculationExecutionEvidenceV2.from_dict(payload)


@pytest.mark.parametrize("field", ("schema_version", "calculation_result_schema_version", "readiness_contract_version"))
@pytest.mark.parametrize("value", (True, False, 2.0, "2", 99, None))
def test_v2_evidence_rejects_coerced_or_unknown_versions(tmp_path, field, value):
    _, _, _, sealed, result, _ = _case(tmp_path)
    evidence = _model(sealed, result)
    payload = evidence.to_dict()
    payload[field] = value
    with pytest.raises(ValueError):
        OnlyResearchCalculationExecutionEvidenceV2.from_dict(payload)
    with pytest.raises(ValueError):
        replace(evidence, **{field: value})


@pytest.mark.parametrize(
    "mutation",
    (
        "extra",
        "binding-extra",
        "binding-missing",
        "binding-sha",
        "non-list",
        "empty",
        "duplicate",
        "unsorted",
        "sha",
        "contract",
        "fingerprint",
        "generation-null",
        "generation-sha",
    ),
)
def test_v2_evidence_rejects_noncanonical_fields_and_bindings(tmp_path, mutation):
    _, _, _, sealed, result, _ = _case(tmp_path)
    payload = _model(sealed, result).to_dict()
    bindings = payload["research_implementation_bindings"]
    if mutation == "extra":
        payload["extra"] = 1
    elif mutation == "binding-extra":
        bindings[0]["extra"] = 1
    elif mutation == "binding-missing":
        del bindings[0]["node_fingerprint"]
    elif mutation == "binding-sha":
        bindings[0]["research_implementation_fingerprint"] = "A" * 64
    elif mutation == "non-list":
        payload["research_implementation_bindings"] = tuple(bindings)
    elif mutation == "empty":
        payload["research_implementation_bindings"] = []
    elif mutation == "duplicate":
        bindings.append(dict(bindings[0]))
    elif mutation == "unsorted":
        bindings.append({"node_fingerprint": "0" * 64, "research_implementation_fingerprint": "f" * 64})
    elif mutation == "sha":
        payload["calculation_fingerprint"] = "A" * 64
    elif mutation == "contract":
        payload["execution_contract_version"] = "RESEARCH_CALCULATION_EXECUTION_V1"
    elif mutation == "fingerprint":
        payload["evidence_fingerprint"] = "0" * 64
    else:
        payload["authoring_generation_fingerprint"] = None if mutation == "generation-null" else "bad"
    with pytest.raises(ValueError):
        OnlyResearchCalculationExecutionEvidenceV2.from_dict(payload)


def test_v2_evidence_identity_changes_with_implementation_or_authoring_generation(tmp_path):
    _, _, _, sealed, result, _ = _case(tmp_path)
    first = _model(sealed, result)
    changed = replace(first.research_implementation_bindings[0], research_implementation_fingerprint="f" * 64)
    assert (
        first.evidence_fingerprint != replace(first, research_implementation_bindings=(changed,)).evidence_fingerprint
    )
    assert first.evidence_fingerprint != replace(first, authoring_generation_fingerprint="a" * 64).evidence_fingerprint
    from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidence

    legacy = OnlyResearchCalculationExecutionEvidence(
        first.calculation_fingerprint,
        first.dataset_snapshot_fingerprint,
        first.calculation_graph_fingerprint,
        first.calculation_result_fingerprint,
        first.result_content_fingerprint,
        first.research_implementation_bindings,
    )
    assert legacy.evidence_fingerprint != first.evidence_fingerprint
    with pytest.raises(ValueError):
        OnlyResearchCalculationExecutionEvidenceV2.from_dict(legacy.to_dict())


@pytest.mark.parametrize("candidate", ("public", "copy", "replace", "v1", "dict", "missing"))
def test_v2_evidence_cannot_be_minted_from_public_copied_or_v1_execution(tmp_path, candidate):
    executor, _, graph, sealed, result, store = _case(tmp_path)
    claims = {
        "public": sealed.execution,
        "copy": replace(sealed),
        "replace": replace(sealed, execution=replace(sealed.execution, readiness=())),
        "v1": executor._execute_verified(sealed.execution.dataset_snapshot_fingerprint, graph),
        "dict": {},
        "missing": None,
    }
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        store._publish_verified(claims[candidate], result)
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()


def test_v2_evidence_requires_authoritative_persisted_result_v2(tmp_path):
    _, results, graph, sealed = _result_case(tmp_path)
    # A public read model from another root is not a publication witness here.
    from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
    from tests.research.calculation.test_result_v2_store import AUDIT

    other = OnlyParquetResearchCalculationResultStoreV2(
        tmp_path / "other", results._dataset_store, audit_time=lambda: AUDIT
    )
    result = other.commit(sealed, graph)
    semantic = tmp_path / "semantic"
    semantic.mkdir()
    store = OnlyResearchCalculationExecutionEvidenceStoreV2(semantic, results)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_NOT_FOUND"):
        store._publish_verified(sealed, result)
    assert not (semantic / "calculation-execution-evidence").exists()


@pytest.mark.parametrize("mutation", ("numeric", "readiness"))
def test_v2_evidence_rejects_sealed_projection_different_from_result(tmp_path, mutation):
    _, _, graph, sealed, result, store = _case(tmp_path)

    def drift(outputs, readiness, calls):
        values = sealed.execution.outputs[calls - 1].table["value"]
        numbers = values.to_pylist()
        if mutation == "numeric":
            numbers[-1] += Decimal("1")
        outputs["value"] = pa.array(numbers, type=values.type)
        table = sealed.execution.readiness[calls - 1].table
        states = table["readiness"].to_pylist()
        reasons = table["reason"].to_pylist()
        if mutation == "readiness":
            states[0], reasons[0] = "READY", "NONE"
        readiness["value"] = OnlyResearchOutputReadiness(pa.array(states), pa.array(reasons))

    executor, _, fingerprint = _setup(tmp_path / "datasets", _registry(_AtomicBackend(drift)))
    different = executor._execute_verified_v2(fingerprint, graph, PUBLICATION)
    assert different.execution.calculation_fingerprint == sealed.execution.calculation_fingerprint
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
        store._publish_verified(different, result)
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()


def test_v2_evidence_publishes_reloads_and_reuses_in_fresh_store_instance(tmp_path):
    _, results, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    path = _root(tmp_path, evidence) / "manifest.json"
    before = path.read_bytes()
    fresh = OnlyResearchCalculationExecutionEvidenceStoreV2(tmp_path / "semantic", results)
    assert fresh.exists(evidence.evidence_fingerprint)
    assert fresh.load_verified(evidence.evidence_fingerprint) == evidence
    assert fresh.require_for_result(result) == evidence
    assert fresh._publish_verified(sealed, result) == evidence
    assert path.read_bytes() == before
    code = """
import json, sys
from pathlib import Path
from tests.research.calculation.test_execution_evidence_v2 import _case
_, _, _, sealed, result, store = _case(Path(sys.argv[1]))
print(json.dumps(store._publish_verified(sealed, result).to_dict(), sort_keys=True))
"""
    loaded = json.loads(subprocess.check_output([sys.executable, "-c", code, str(tmp_path)], text=True))
    assert loaded == evidence.to_dict()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest-byte",
        "wrong-schema",
        "wrong-result-version",
        "wrong-readiness-version",
        "extra-file",
        "missing-manifest",
        "duplicate-json-key",
        "symlink-root",
        "symlink-manifest",
    ),
)
def test_v2_evidence_corruption_fails_closed(tmp_path, mutation):
    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    root = _root(tmp_path, evidence)
    manifest = root / "manifest.json"
    if mutation == "manifest-byte":
        manifest.write_bytes(manifest.read_bytes() + b" ")
    elif mutation.startswith("wrong-"):
        payload = json.loads(manifest.read_text())
        field = {
            "wrong-schema": "schema_version",
            "wrong-result-version": "calculation_result_schema_version",
            "wrong-readiness-version": "readiness_contract_version",
        }[mutation]
        payload[field] = 99
        manifest.write_text(json.dumps(payload))
    elif mutation == "extra-file":
        (root / "extra").write_text("bad")
    elif mutation == "missing-manifest":
        manifest.unlink()
    elif mutation == "duplicate-json-key":
        manifest.write_text('{"schema_version":2,' + manifest.read_text()[1:])
    else:
        path = root if mutation == "symlink-root" else manifest
        outside = tmp_path / "outside"
        path.rename(outside)
        path.symlink_to(outside)
    for action in (
        lambda: store.load_verified(evidence.evidence_fingerprint),
        lambda: store.exists(evidence.evidence_fingerprint),
        lambda: store._publish_verified(sealed, result),
        lambda: store.require_for_result(result),
    ):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
            action()


@pytest.mark.parametrize("kind", ("empty", "file", "dangling-symlink"))
def test_v2_malformed_existing_authority_is_not_replaced(tmp_path, kind):
    _, _, _, sealed, result, store = _case(tmp_path)
    root = _root(tmp_path, _model(sealed, result))
    root.parent.mkdir(parents=True)
    if kind == "empty":
        root.mkdir()
    elif kind == "file":
        root.write_bytes(b"winner")
    else:
        root.symlink_to(tmp_path / "missing")
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store._publish_verified(sealed, result)
    assert root.is_symlink() if kind == "dangling-symlink" else root.exists()
    if kind == "file":
        assert root.read_bytes() == b"winner"


def test_v2_evidence_concurrent_exact_publishers_converge(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    barrier = Barrier(2)
    rename = module._rename_exclusive

    def race(source, target):
        barrier.wait(timeout=10)
        rename(source, target)

    monkeypatch.setattr(module, "_rename_exclusive", race)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store._publish_verified(sealed, result), range(2)))
    assert results[0] == results[1]
    assert list(_root(tmp_path, results[0]).parent.iterdir()) == [_root(tmp_path, results[0])]


@pytest.mark.parametrize("kind", ("exact", "empty", "file", "symlink", "corrupt"))
def test_v2_evidence_unknown_rename_outcome_converges_only_to_exact_root(tmp_path, monkeypatch, kind):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    rename = module._rename_exclusive

    def unknown(source, target):
        if kind in ("exact", "corrupt"):
            rename(source, target)
            if kind == "corrupt":
                (target / "manifest.json").write_text("{}")
        elif kind == "empty":
            target.mkdir()
        elif kind == "file":
            target.write_bytes(b"winner")
        else:
            target.symlink_to(tmp_path / "missing")
        raise OSError("lost rename acknowledgment")

    monkeypatch.setattr(module, "_rename_exclusive", unknown)
    if kind == "exact":
        assert store._publish_verified(sealed, result) == store.require_for_result(result)
    else:
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
            store._publish_verified(sealed, result)


def test_v2_evidence_durability_stops_at_semantic_root(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    root = _root(tmp_path, evidence)
    sync, paths = module._sync_directory, []

    def record(path, **kwargs):
        paths.append(path)
        if path != tmp_path / "semantic" and tmp_path / "semantic" not in path.parents:
            raise OSError("above authority anchor")
        sync(path, **kwargs)

    monkeypatch.setattr(module, "_sync_directory", record)
    assert store._publish_verified(sealed, result) == evidence
    assert paths == [
        root,
        root.parent,
        root.parent.parent,
        root.parent.parent.parent / ".staging",
        root.parent.parent.parent,
        tmp_path / "semantic" / "calculation-execution-evidence",
        tmp_path / "semantic",
    ]


@pytest.mark.parametrize("point", ("manifest", "target", "prefix", "sha256", "v2", "authority", "anchor"))
def test_v2_required_sync_failure_is_not_acknowledged_and_retry_converges(tmp_path, monkeypatch, point):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = _model(sealed, result)
    root = _root(tmp_path, evidence)
    # Visible exact authority still requires every durability step on re-entry.
    store._publish_verified(sealed, result)
    before = (root / "manifest.json").read_bytes()
    sync = module._sync_directory
    failure = {
        "target": root,
        "prefix": root.parent,
        "sha256": root.parent.parent,
        "v2": root.parent.parent.parent,
        "authority": tmp_path / "semantic" / "calculation-execution-evidence",
        "anchor": tmp_path / "semantic",
    }.get(point)

    def fail(path, **kwargs):
        if path == failure:
            raise OSError("required sync failed")
        sync(path, **kwargs)

    if point == "manifest":
        with monkeypatch.context() as context:
            context.setattr(
                module, "_sync_manifest", lambda path, **kwargs: (_ for _ in ()).throw(OSError("file sync failed"))
            )
            with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
                store._publish_verified(sealed, result)
    else:
        with monkeypatch.context() as context:
            context.setattr(module, "_sync_directory", fail)
            with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
                store._publish_verified(sealed, result)
    assert store._publish_verified(sealed, result) == evidence
    assert (root / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("kind", ("missing", "file", "symlink", "dangling-symlink"))
def test_v2_evidence_requires_preprovisioned_real_semantic_root(tmp_path, kind):
    _, results, _, sealed, result, _ = _case(tmp_path)
    anchor = tmp_path / "anchor"
    if kind == "file":
        anchor.write_text("bad")
    elif "symlink" in kind:
        anchor.symlink_to(tmp_path / ("semantic" if kind == "symlink" else "missing"))
    store = OnlyResearchCalculationExecutionEvidenceStoreV2(anchor, results)
    with pytest.raises(OnlyResearchCalculationError):
        store._publish_verified(sealed, result)
    assert not (anchor / "calculation-execution-evidence").exists()


def test_v2_duplicate_exact_producers_require_explicit_provenance(tmp_path):
    _, _, _, sealed, result, store = _case(tmp_path)
    first = store._publish_verified(sealed, result, "a" * 64)
    second = store._publish_verified(sealed, result, "b" * 64)
    assert first.evidence_fingerprint != second.evidence_fingerprint
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
        store.require_for_result(result)
    assert store.require_for_result(result, "a" * 64) == first
    assert store.require_for_result(result, "b" * 64) == second
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"):
        store.require_for_result(result, "c" * 64)


def test_v2_require_for_result_never_falls_back_to_v1_evidence(tmp_path):
    executor, results, graph, sealed, result, store = _case(tmp_path)
    from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
    from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
    from tests.research.calculation.test_result_v2_store import AUDIT

    legacy = executor._execute_verified(sealed.execution.dataset_snapshot_fingerprint, graph)
    legacy_result = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", results._dataset_store, audit_time=lambda: AUDIT
    ).commit(legacy.execution, graph)
    old = OnlyResearchCalculationExecutionEvidenceStore(tmp_path / "semantic")
    old_evidence = old._publish_verified(legacy, legacy_result)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"):
        store.require_for_result(result)
    assert old.load_verified(old_evidence.evidence_fingerprint) == old_evidence


@pytest.mark.parametrize("kind", ("bad-prefix", "wrong-prefix", "symlink-prefix", "bad-target"))
def test_v2_authoritative_scan_never_skips_malformed_entries(tmp_path, kind):
    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    root = _root(tmp_path, evidence)
    if kind == "bad-prefix":
        (root.parent.parent / "zz").mkdir()
    elif kind == "wrong-prefix":
        prefix = root.parent.parent / ("00" if root.parent.name != "00" else "11")
        prefix.mkdir()
        root.rename(prefix / root.name)
    elif kind == "symlink-prefix":
        outside = tmp_path / "outside"
        root.parent.rename(outside)
        root.parent.symlink_to(outside)
    else:
        (root.parent / "bad").mkdir()
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_CORRUPT"):
        store.require_for_result(result)


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "readiness_contract_version",
        "dataset_snapshot_fingerprint",
        "calculation_graph_fingerprint",
        "result_content_fingerprint",
        "calculation_result_fingerprint",
    ),
)
def test_v2_supplied_result_identity_must_equal_authoritative_reload(tmp_path, field):
    _, _, _, sealed, result, store = _case(tmp_path)
    manifest = replace(result.manifest)
    object.__setattr__(manifest, field, True if field.endswith("version") else "f" * 64)
    claim = replace(result, manifest=manifest)
    for action in (lambda: store._publish_verified(sealed, claim), lambda: store.require_for_result(claim)):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
            action()
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()


def test_v2_different_implementation_for_same_semantic_result_is_ambiguous(tmp_path):
    from onlyalpha_plugin_indicators.registration import registrations

    from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationRegistry
    from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor

    executor, _, graph, sealed, result, store = _case(tmp_path)
    first = store._publish_verified(sealed, result)
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        if (
            registration.backend is OnlyCalculationBackendKind.RESEARCH
            and registration.type_definition.type_id == graph.nodes[0].definition.type_id
        ):
            manifest = registration.implementation_manifest
            resources = list(manifest.resources)
            resources[0] = replace(resources[0], byte_sha256="f" * 64)
            registration = replace(registration, implementation_manifest=replace(manifest, resources=tuple(resources)))
        registry.register(registration)
    different = OnlyResearchCalculationExecutor(
        executor._store, OnlyResearchCalculationBackendResolver(registry)
    )._execute_verified_v2(sealed.execution.dataset_snapshot_fingerprint, graph, PUBLICATION)
    second = store._publish_verified(different, result)
    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    assert first.research_implementation_bindings != second.research_implementation_bindings
    assert first.evidence_fingerprint != second.evidence_fingerprint
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_IDENTITY_MISMATCH"):
        store.require_for_result(result)


@pytest.mark.parametrize("unknown", (False, True))
def test_v2_initial_sync_failure_after_visible_rename_does_not_acknowledge(tmp_path, monkeypatch, unknown):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = _model(sealed, result)
    root = _root(tmp_path, evidence)
    sync, rename = module._sync_directory, module._rename_exclusive

    def publish(source, target):
        rename(source, target)
        if unknown:
            raise OSError("rename effect unknown")

    def fail(path, **kwargs):
        if path == root.parent:
            raise OSError("required namespace sync failed")
        sync(path, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(module, "_rename_exclusive", publish)
        context.setattr(module, "_sync_directory", fail)
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
            store._publish_verified(sealed, result)
        before = (root / "manifest.json").read_bytes()
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"):
            store._publish_verified(sealed, result)
    assert store._publish_verified(sealed, result) == evidence
    assert (root / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("point", ("write", "stage-verify", "stage-sync", "rename"))
def test_v2_failed_stage_is_not_published_and_is_cleaned(tmp_path, monkeypatch, point):
    import onlyalpha.research.calculation.execution_evidence_v2 as module

    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = _model(sealed, result)
    root = _root(tmp_path, evidence)

    def fail(*args, **kwargs):
        raise OSError("injected publication failure")

    if point == "write":
        monkeypatch.setattr(module.os, "fsync", fail)
    elif point == "stage-sync":
        monkeypatch.setattr(module, "_sync_directory", fail)
    elif point == "rename":
        monkeypatch.setattr(module, "_rename_exclusive", fail)
    else:
        read = store._read_verified

        def verify(path, fingerprint):
            if path.name.startswith(".stage-"):
                raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "injected")
            return read(path, fingerprint)

        monkeypatch.setattr(store, "_read_verified", verify)
    with pytest.raises(OnlyResearchCalculationError):
        store._publish_verified(sealed, result)
    assert not root.exists()
    assert list(root.parent.iterdir()) == []
    assert list((root.parent.parent.parent / ".staging").iterdir()) == []


def test_v2_readers_revalidate_upstream_result_and_never_certify_corrupt_absence(tmp_path):
    _, _, _, sealed, result, store = _case(tmp_path)
    evidence = store._publish_verified(sealed, result)
    fingerprint = result.manifest.calculation_fingerprint
    manifest = tmp_path / "results" / "v2" / "sha256" / fingerprint[:2] / fingerprint / "manifest.json"
    manifest.write_text("{}")
    for action in (
        lambda: store.load_verified(evidence.evidence_fingerprint),
        lambda: store.exists(evidence.evidence_fingerprint),
        lambda: store.require_for_result(result),
        lambda: store._publish_verified(sealed, result),
    ):
        with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
            action()


def test_v2_evidence_covers_nullable_readiness_state_space(tmp_path):
    from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
    from tests.research.calculation.test_execution_readiness_v2 import SMA, _graph
    from tests.research.calculation.test_result_v2_store import AUDIT

    def states(outputs, readiness, calls):
        for name in outputs:
            outputs[name] = pa.array([None] * 4, type=outputs[name].type)
            readiness[name] = OnlyResearchOutputReadiness(
                pa.array(["PARTIAL", "READY", "UNAVAILABLE", "UNAVAILABLE"]),
                pa.array(["WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"]),
            )

    definition = replace(SMA, outputs=(replace(SMA.outputs[0], name="a"), replace(SMA.outputs[0], name="z")))
    executor, spy, fingerprint = _setup(
        tmp_path / "datasets", _registry(_AtomicBackend(states), type_definition=definition)
    )
    graph = _graph(type_definition=definition)
    sealed = executor._execute_verified_v2(fingerprint, graph, PUBLICATION)
    results = OnlyParquetResearchCalculationResultStoreV2(tmp_path / "results", spy.store, audit_time=lambda: AUDIT)
    result = results.commit(sealed, graph)
    semantic = tmp_path / "semantic"
    semantic.mkdir()
    store = OnlyResearchCalculationExecutionEvidenceStoreV2(semantic, results)
    evidence = store._publish_verified(sealed, result)
    assert store.load_verified(evidence.evidence_fingerprint) == evidence
    assert store.require_for_result(result) == evidence
