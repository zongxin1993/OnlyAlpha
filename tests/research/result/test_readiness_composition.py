"""Result V4 scientific identity and explicit V2 authority/durability closure."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1
from onlyalpha.research.result import OnlyJsonResearchResultStore, OnlyResearchResultAssembler
from onlyalpha.research.result.errors import OnlyResearchResultError, OnlyResearchResultStoreError
from onlyalpha.research.result.plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
)
from onlyalpha.research.result.result import OnlyResearchResultManifest
from tests.research.calculation.test_result_v2_store import AUDIT, _case


class _Never:
    def load_verified(self, fingerprint):
        raise AssertionError("Result V4 must not query legacy/Statistics authority")


def _composition(tmp_path):
    _, calculations, graph, sealed = _case(tmp_path)
    calculation = calculations.commit(sealed, graph)
    evidence_root = tmp_path / "semantic"
    evidence_root.mkdir()
    evidence = OnlyResearchCalculationExecutionEvidenceStoreV2(evidence_root, calculations)
    evidence._publish_verified(sealed, calculation)
    manifest = calculation.manifest
    plan = OnlyResearchResultPlan(
        (),
        4,
        manifest.dataset_snapshot_fingerprint,
        (OnlyResearchResultCalculationPlan(manifest.calculation_fingerprint, graph.fingerprint),),
        (),
        (OnlyResearchResultSeriesPlan(None, manifest.calculation_fingerprint, graph.nodes[0].fingerprint, "value"),),
        (),
        OnlyResearchCalculationPublicationSelectionV1(),
    )
    assembler = OnlyResearchResultAssembler(
        _Never(),
        audit_time=lambda: AUDIT,
        calculation_result_store=_Never(),
        readiness_result_store=calculations,
        readiness_evidence_store=evidence,
    )
    store = OnlyJsonResearchResultStore(
        tmp_path / "compositions",
        _Never(),
        _Never(),
        readiness_result_store=calculations,
        readiness_evidence_store=evidence,
    )
    return plan, assembler, store, calculations


def test_result_v4_complete_round_trip_and_scientific_identity(tmp_path):
    plan, assembler, store, calculations = _composition(tmp_path)
    result = assembler.assemble(plan)
    manifest = result.manifest
    expected_content = only_canonical_fingerprint(
        {
            "schema_version": 4,
            "statistics_results": (),
            "calculation_results": tuple(item.to_dict() for item in manifest.calculation_results),
        }
    )
    assert manifest.research_result_content_fingerprint == expected_content
    assert manifest.statistics_results == ()
    assert OnlyResearchResultManifest.from_dict(manifest.to_dict()) == manifest
    outcome = store.commit(result)
    assert store.load_verified(plan.fingerprint) == result
    assert (
        store.commit(
            replace(result, manifest=replace(manifest, created_at=datetime(2025, 1, 1, tzinfo=UTC)))
        ).research_result_fingerprint
        == outcome.research_result_fingerprint
    )
    assert not any("generation" in key or "evidence" in key for key in manifest.to_dict())
    assert calculations.load_verified(plan.calculations[0].calculation_fingerprint).manifest.schema_version == 2


def test_result_v4_no_v1_authority_fallback(tmp_path):
    plan, assembler, _, _ = _composition(tmp_path)
    assert assembler.assemble(plan).manifest.schema_version == 4
    with pytest.raises(OnlyResearchResultError, match="V2 authority"):
        OnlyResearchResultAssembler(_Never(), audit_time=lambda: AUDIT, calculation_result_store=_Never()).assemble(
            plan
        )


@pytest.mark.parametrize(
    "dimension", ("dataset", "graph", "node", "output", "result_identity", "missing", "wrong_family")
)
def test_result_v4_rejects_wrong_complete_relation_or_missing_proof(tmp_path, monkeypatch, dimension):
    plan, assembler, store, calculations = _composition(tmp_path)
    result = assembler.assemble(plan)
    upstream = calculations.load_verified(plan.calculations[0].calculation_fingerprint)
    if dimension == "dataset":
        plan = replace(plan, dataset_snapshot_fingerprint="f" * 64)
    elif dimension == "graph":
        plan = replace(plan, calculations=(replace(plan.calculations[0], graph_fingerprint="f" * 64),))
    elif dimension in {"node", "output"}:
        field = "node_fingerprint" if dimension == "node" else "output_name"
        plan = replace(plan, published_series=(replace(plan.published_series[0], **{field: "f" * 64}),))
    elif dimension == "missing":
        monkeypatch.setattr(
            calculations, "load_verified", lambda _: (_ for _ in ()).throw(FileNotFoundError("upstream unavailable"))
        )
    elif dimension == "wrong_family":
        monkeypatch.setattr(calculations, "load_verified", lambda _: object())
    else:
        object.__setattr__(upstream.manifest, "calculation_result_fingerprint", "f" * 64)
        monkeypatch.setattr(calculations, "load_verified", lambda _: upstream)
    with pytest.raises(OnlyResearchResultError):
        assembler.assemble(plan)
    if dimension in {"missing", "wrong_family", "result_identity"}:
        with pytest.raises(OnlyResearchResultStoreError):
            store.commit(result)


def test_result_v4_every_verified_reload_requires_exact_predecessor(tmp_path, monkeypatch):
    plan, assembler, store, calculations = _composition(tmp_path)
    store.commit(assembler.assemble(plan))
    monkeypatch.setattr(calculations, "load_verified", lambda _: (_ for _ in ()).throw(FileNotFoundError("gone")))
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        store.load_verified(plan.fingerprint)


def test_result_v4_equal_exclusive_race_preserves_one_authority(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.result_v2_store as atomic

    plan, assembler, store, _ = _composition(tmp_path)
    result = assembler.assemble(plan)
    real, barrier = atomic._rename_exclusive, Barrier(2)

    def rename(source, target):
        barrier.wait(timeout=10)
        return real(source, target)

    monkeypatch.setattr(atomic, "_rename_exclusive", rename)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: store.commit(result), range(2)))
    assert {item.research_result_fingerprint for item in outcomes} == {result.manifest.research_result_fingerprint}
    assert store.load_verified(plan.fingerprint) == result


@pytest.mark.parametrize("phase", ("result_tree", "prefix", "sha256", "root", "anchor", "predecessor"))
def test_result_v4_sync_failure_cannot_be_bypassed_by_readable_reuse(tmp_path, monkeypatch, phase):
    import onlyalpha.research.calculation.result_v2_store as atomic

    plan, assembler, store, calculations = _composition(tmp_path)
    result = assembler.assemble(plan)
    target = tmp_path / "compositions" / "sha256" / plan.fingerprint[:2] / plan.fingerprint
    paths = {
        "result_tree": target,
        "prefix": target.parent,
        "sha256": target.parent.parent,
        "root": tmp_path / "compositions",
        "anchor": tmp_path,
    }
    real_sync = atomic._sync_directory

    def sync(path, **kwargs):
        if path == paths.get(phase):
            raise OSError("injected acknowledgement failure")
        return real_sync(path, **kwargs)

    with monkeypatch.context() as patch:
        if phase == "predecessor":
            patch.setattr(
                calculations,
                "acknowledge_exact",
                lambda *args: (_ for _ in ()).throw(OSError("predecessor sync failure")),
            )
        else:
            patch.setattr(atomic, "_sync_directory", sync)
        with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_COMMIT_FAILED"):
            store.commit(result)
        assert store.load_verified(plan.fingerprint) == result
        with pytest.raises(OnlyResearchResultStoreError):
            store.commit(result)
    assert store.commit(result).research_result_fingerprint == result.manifest.research_result_fingerprint


def test_result_v4_duplicate_json_key_is_corruption(tmp_path):
    plan, assembler, store, _ = _composition(tmp_path)
    store.commit(assembler.assemble(plan))
    path = tmp_path / "compositions" / "sha256" / plan.fingerprint[:2] / plan.fingerprint / "manifest.json"
    raw = path.read_text()
    path.write_text('{"schema_version":4,' + raw[1:])
    assert json.loads(path.read_text())["schema_version"] == 4
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        store.load_verified(plan.fingerprint)


def test_result_v4_rejects_missing_anchor_before_publication_barrier_creates_namespace(tmp_path):
    plan, assembler, _, calculations = _composition(tmp_path)
    result = assembler.assemble(plan)
    anchor = tmp_path / "not-provisioned"
    store = OnlyJsonResearchResultStore(anchor / "compositions", None, readiness_result_store=calculations)
    with pytest.raises(OnlyResearchResultStoreError, match="anchor must be preprovisioned"):
        store.commit(result)
    assert not anchor.exists()


@pytest.mark.parametrize("mutation", ("missing", "corrupt", "disconnected", "unavailable"))
def test_result_v4_requires_evidence_before_assembly_commit_and_every_reload(tmp_path, monkeypatch, mutation):
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor

    plan, assembler, store, calculations = _composition(tmp_path)
    result = assembler.assemble(plan)
    store.commit(result)
    evidence = store._readiness_evidence_store
    producer = evidence.require_for_result(calculations.load_verified(plan.calculations[0].calculation_fingerprint))
    target = evidence._target(producer.evidence_fingerprint)
    if mutation == "missing":
        target.rename(tmp_path / "removed-evidence")
    elif mutation == "corrupt":
        (target / "manifest.json").write_text("{}")
    elif mutation == "disconnected":
        (tmp_path / "semantic").rename(tmp_path / "unavailable-evidence")
    else:
        attempted_reads = []

        def unavailable_read(*args):
            attempted_reads.append(args)
            raise PermissionError("controlled owning Evidence reader I/O failure")

        monkeypatch.setattr(evidence, "_read_verified", unavailable_read)

    def forbidden_execution(*args, **kwargs):
        pytest.fail("incomplete Evidence caused numeric execution")

    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden_execution)
    retained = {
        path: path.read_bytes()
        for family in ("semantic", "removed-evidence", "unavailable-evidence")
        for path in (tmp_path / family).rglob("*")
        if path.is_file()
    }
    original = store._target(plan.fingerprint) / "manifest.json"
    before = original.read_bytes()
    with pytest.raises(OnlyResearchResultError) as rejected:
        assembler.assemble(plan)
    if mutation == "unavailable":
        assert rejected.value.__cause__.code == "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"
    with pytest.raises(OnlyResearchResultStoreError):
        store.commit(result)
    with pytest.raises(OnlyResearchResultStoreError):
        store.load_verified(plan.fingerprint)
    assert original.read_bytes() == before
    other = OnlyJsonResearchResultStore(
        tmp_path / "new-results", None, readiness_result_store=calculations, readiness_evidence_store=evidence
    )
    with pytest.raises(OnlyResearchResultStoreError):
        other.commit(result)
    assert not other._target(plan.fingerprint).exists()
    assert retained == {
        path: path.read_bytes()
        for family in ("semantic", "removed-evidence", "unavailable-evidence")
        for path in (tmp_path / family).rglob("*")
        if path.is_file()
    }
    if mutation == "unavailable":
        assert attempted_reads


def test_result_v4_cannot_publish_a_caller_declaration_without_evidence_authority(tmp_path):
    plan, assembler, _, calculations = _composition(tmp_path)
    candidate = assembler.assemble(plan)
    naked = OnlyResearchResultAssembler(None, audit_time=lambda: AUDIT, readiness_result_store=calculations)
    with pytest.raises(OnlyResearchResultError, match="Execution Evidence V2"):
        naked.assemble(plan)
    store = OnlyJsonResearchResultStore(tmp_path / "unattested", None, readiness_result_store=calculations)
    with pytest.raises(OnlyResearchResultStoreError, match="Execution Evidence V2"):
        store.commit(candidate)
    assert not store._target(plan.fingerprint).exists()


def test_result_v4_complete_multiple_producers_do_not_select_or_change_scientific_identity(tmp_path):
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
    from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION
    from tests.research.calculation.test_runtime_execution_provenance import _context

    plan, assembler, store, calculations = _composition(tmp_path)
    original = assembler.assemble(plan)
    store.commit(original)
    executor, _, graph, _ = _case(tmp_path / "other-producer")
    context = _context(executor, graph, generation="b")
    sealed = executor._execute_verified_v2(
        plan.dataset_snapshot_fingerprint, graph, PUBLICATION, runtime_context=context
    )
    result = calculations.load_verified(plan.calculations[0].calculation_fingerprint)
    evidence = store._readiness_evidence_store
    evidence._publish_verified(sealed, result)
    assert len(evidence.require_all_for_result(result)) == 2
    with pytest.raises(OnlyResearchCalculationError, match="multiple exact producers"):
        evidence.require_for_result(result)
    assert assembler.assemble(plan) == original
    assert store.commit(original).research_result_fingerprint == original.manifest.research_result_fingerprint
    assert store.load_verified(plan.fingerprint) == original


def test_result_v4_evidence_ack_failure_is_not_bypassed_by_readable_result_reuse(tmp_path, monkeypatch):
    plan, assembler, store, _ = _composition(tmp_path)
    result = assembler.assemble(plan)
    evidence = store._readiness_evidence_store
    with monkeypatch.context() as scope:
        scope.setattr(evidence, "acknowledge_exact", lambda _: (_ for _ in ()).throw(OSError("evidence fsync")))
        with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_COMMIT_FAILED"):
            store.commit(result)
        assert store.load_verified(plan.fingerprint) == result
        with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_COMMIT_FAILED"):
            store.commit(result)
    assert store.commit(result).research_result_fingerprint == result.manifest.research_result_fingerprint
