from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields, replace
from decimal import Decimal
from threading import Barrier

import pyarrow as pa
import pytest

from onlyalpha.research.calculation.errors import OnlyResearchCalculationError, OnlyResearchCalculationResultStoreError
from onlyalpha.research.job import (
    OnlyResearchJobDisposition,
    OnlyResearchJobError,
    OnlyResearchJobExecutor,
    OnlyResearchJobPhase,
)
from tests.research.job.support import readiness_job_case


class _CountingCalculation:
    def __init__(self, delegate, barrier=None):
        self.delegate = delegate
        self.calls = 0
        self.barrier = barrier

    def _execute_verified(self, *args):
        raise AssertionError("V2 never executes V1")

    def _execute_verified_v2(self, *args):
        self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return self.delegate._execute_verified_v2(*args)


def _job(calculation, legacy, results, evidence, generation=None):
    return OnlyResearchJobExecutor(
        calculation,
        legacy,
        legacy._test_execution_evidence_store,
        generation,
        readiness_result_store=results,
        readiness_execution_evidence_store=evidence,
    )


def _result_root(root, plan):
    fingerprint = plan.calculation_fingerprint
    return root / "results" / "v2" / "sha256" / fingerprint[:2] / fingerprint


def _bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _precommit(plan, calculation, results):
    sealed = calculation._execute_verified_v2(
        plan.dataset_snapshot_fingerprint, plan.calculation_graph, plan.publication
    )
    return sealed, results.commit(sealed, plan.calculation_graph)


class _Never:
    def __getattr__(self, name):
        raise AssertionError(f"unavailable authority must fail before {name}")


@pytest.mark.parametrize("available", ("none", "result-only", "evidence-only"))
def test_v2_job_requires_both_v2_authorities_before_any_store_or_backend_call(tmp_path, available):
    plan, _, _, _, _ = readiness_job_case(tmp_path)
    never = _Never()
    job = OnlyResearchJobExecutor(
        never,
        never,
        never,
        readiness_result_store=never if available == "result-only" else None,
        readiness_execution_evidence_store=never if available == "evidence-only" else None,
    )
    with pytest.raises(OnlyResearchJobError) as raised:
        job.execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.PLAN_VALIDATION
    assert raised.value.code == "RESEARCH_JOB_READINESS_AUTHORITIES_UNAVAILABLE"


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema_version", True),
        ("schema_version", 2.0),
        ("schema_version", 99),
        ("publication", None),
        ("dataset_snapshot_fingerprint", "bad"),
        ("calculation_graph", None),
    ),
)
def test_v2_corrupted_plan_fails_before_any_authority_access(tmp_path, field, value):
    plan, _, _, _, _ = readiness_job_case(tmp_path)
    object.__setattr__(plan, field, value)
    never = _Never()
    with pytest.raises(OnlyResearchJobError) as raised:
        OnlyResearchJobExecutor(
            never, never, never, readiness_result_store=never, readiness_execution_evidence_store=never
        ).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.PLAN_VALIDATION
    assert raised.value.code == "RESEARCH_JOB_INVALID"


def test_v1_job_import_does_not_load_v2_result_or_evidence_implementations():
    code = """
import importlib.abc, sys
class RejectV2(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('onlyalpha.research.calculation.result_v2') or fullname.endswith('execution_evidence_v2'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, RejectV2())
from onlyalpha.research import OnlyResearchJobPlan, OnlyResearchJobExecutor
assert not any('result_v2' in name or 'execution_evidence_v2' in name for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_v2_job_executes_then_reuses_same_result_and_evidence(tmp_path, monkeypatch):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    source_before = _bytes(tmp_path / "datasets")
    counted = _CountingCalculation(calculation)
    job = _job(counted, legacy, results, evidence)
    first = job.execute(plan)
    before = _bytes(tmp_path / "results") | _bytes(tmp_path / "semantic")
    monkeypatch.setattr(
        legacy, "load_verified", lambda _: (_ for _ in ()).throw(AssertionError("reuse must not inspect V1"))
    )
    second = job.execute(plan)
    assert first.disposition is OnlyResearchJobDisposition.EXECUTED
    assert second.disposition is OnlyResearchJobDisposition.REUSED
    assert replace(second, disposition=first.disposition) == first
    assert counted.calls == 1
    assert before == _bytes(tmp_path / "results") | _bytes(tmp_path / "semantic")
    assert source_before == _bytes(tmp_path / "datasets")
    result = results.load_verified(plan.calculation_fingerprint)
    assert evidence.require_for_result(result).evidence_fingerprint == first.calculation_execution_evidence_fingerprint


def test_v2_job_fresh_process_reentry_preserves_all_identities(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    first = _job(calculation, legacy, results, evidence).execute(plan)
    code = """
import json, sys
from dataclasses import asdict
from pathlib import Path
from tests.research.job.support import readiness_job_case
from tests.research.job.test_readiness_publication import _job, _Never
plan, _, legacy, results, evidence = readiness_job_case(Path(sys.argv[1]))
print(json.dumps(asdict(_job(_Never(), legacy, results, evidence).execute(plan))))
"""
    value = json.loads(subprocess.check_output([sys.executable, "-c", code, str(tmp_path)], text=True))
    assert value == asdict(replace(first, disposition=OnlyResearchJobDisposition.REUSED))


def test_v2_job_concurrent_exact_execution_converges_to_one_result_and_evidence(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    counted = _CountingCalculation(calculation, Barrier(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _job(counted, legacy, results, evidence).execute(plan), range(2)))
    assert outcomes[0] == outcomes[1]
    assert counted.calls == 2
    assert outcomes[0].disposition is OnlyResearchJobDisposition.EXECUTED
    result = results.load_verified(plan.calculation_fingerprint)
    assert (
        evidence.require_for_result(result).evidence_fingerprint
        == outcomes[0].calculation_execution_evidence_fingerprint
    )


def test_v2_job_recovers_result_committed_before_evidence_publication(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    _, result = _precommit(plan, calculation, results)
    before = _bytes(_result_root(tmp_path, plan))
    counted = _CountingCalculation(calculation)
    job = _job(counted, legacy, results, evidence)
    first, second = job.execute(plan), job.execute(plan)
    assert counted.calls == 1
    assert first.disposition is OnlyResearchJobDisposition.EXECUTED
    assert second.disposition is OnlyResearchJobDisposition.REUSED
    assert first.calculation_result_fingerprint == result.manifest.calculation_result_fingerprint
    assert before == _bytes(_result_root(tmp_path, plan))


def test_v2_job_evidence_publish_failure_reentry_recovers_without_rewriting_result(tmp_path, monkeypatch):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    counted = _CountingCalculation(calculation)

    def fail(*args):
        raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", "injected")

    with monkeypatch.context() as context:
        context.setattr(evidence, "_publish_verified", fail)
        with pytest.raises(OnlyResearchJobError) as raised:
            _job(counted, legacy, results, evidence).execute(plan)
        assert raised.value.phase is OnlyResearchJobPhase.RESULT_COMMIT
        assert raised.value.code == "RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED"
    before = _bytes(_result_root(tmp_path, plan))
    fresh_plan, fresh_calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    fresh = _CountingCalculation(fresh_calculation)
    outcome = _job(fresh, legacy, results, evidence).execute(fresh_plan)
    assert outcome.disposition is OnlyResearchJobDisposition.EXECUTED
    assert counted.calls == fresh.calls == 1
    assert before == _bytes(_result_root(tmp_path, plan))


@pytest.mark.parametrize("kind", ("result", "evidence", "ambiguous"))
def test_v2_job_does_not_reexecute_for_corrupt_or_ambiguous_authority(tmp_path, kind):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, result = _precommit(plan, calculation, results)
    witness = evidence._publish_verified(sealed, result, "a" * 64)
    if kind == "result":
        (_result_root(tmp_path, plan) / "manifest.json").write_text("{}")
    elif kind == "evidence":
        fingerprint = witness.evidence_fingerprint
        (
            tmp_path
            / "semantic"
            / "calculation-execution-evidence"
            / "v2"
            / "sha256"
            / fingerprint[:2]
            / fingerprint
            / "manifest.json"
        ).write_text("{}")
    else:
        evidence._publish_verified(sealed, result, "b" * 64)
    counted = _CountingCalculation(calculation)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert (
        raised.value.code
        == {
            "result": "RESULT_CORRUPT",
            "evidence": "RESEARCH_EXECUTION_EVIDENCE_CORRUPT",
            "ambiguous": "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
        }[kind]
    )
    assert counted.calls == 0


def test_v2_job_other_explicit_generation_recovers_new_evidence_then_reuses(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    counted = _CountingCalculation(calculation)
    first = _job(counted, legacy, results, evidence, "a" * 64).execute(plan)
    before = _bytes(_result_root(tmp_path, plan))
    job = _job(counted, legacy, results, evidence, "b" * 64)
    second, reused = job.execute(plan), job.execute(plan)
    assert counted.calls == 2
    assert second.disposition is OnlyResearchJobDisposition.EXECUTED
    assert reused.disposition is OnlyResearchJobDisposition.REUSED
    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    assert first.calculation_execution_evidence_fingerprint != second.calculation_execution_evidence_fingerprint
    assert before == _bytes(_result_root(tmp_path, plan))


def test_v1_result_without_v1_evidence_can_serve_as_numeric_parity_only(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    execution = calculation._execute_verified(plan.dataset_snapshot_fingerprint, plan.calculation_graph)
    old = legacy.commit(execution.execution, plan.calculation_graph)
    before = _bytes(tmp_path / "results" / "sha256")
    counted = _CountingCalculation(calculation)
    outcome = _job(counted, legacy, results, evidence).execute(plan)
    assert counted.calls == 1
    assert outcome.calculation_result_fingerprint != old.manifest.calculation_result_fingerprint
    assert before == _bytes(tmp_path / "results" / "sha256")
    assert not (tmp_path / "semantic" / "calculation-execution-evidence" / "sha256").exists()


def test_v2_job_rejects_corrupt_v1_result_before_v2_execution(tmp_path):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    legacy.commit(
        calculation.execute(plan.dataset_snapshot_fingerprint, plan.calculation_graph), plan.calculation_graph
    )
    fingerprint = plan.calculation_fingerprint
    (tmp_path / "results" / "sha256" / fingerprint[:2] / fingerprint / "manifest.json").write_text("{}")
    counted = _CountingCalculation(calculation)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.code == "RESULT_CORRUPT"
    assert counted.calls == 0
    assert not (tmp_path / "results" / "v2").exists()


@pytest.mark.parametrize(
    "field",
    (
        "whole",
        "manifest",
        "schema_version",
        "calculation_fingerprint",
        "dataset_snapshot_fingerprint",
        "calculation_graph_fingerprint",
        "result_content_fingerprint",
        "calculation_result_fingerprint",
    ),
)
def test_v2_job_invalid_v1_authority_response_is_not_a_parity_miss(tmp_path, monkeypatch, field):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    old = legacy.commit(
        calculation.execute(plan.dataset_snapshot_fingerprint, plan.calculation_graph), plan.calculation_graph
    )
    if field == "whole":
        claim = None
    elif field == "manifest":
        claim = replace(old, manifest=None)
    else:
        claim = replace(old, manifest=replace(old.manifest, **{field: True if field == "schema_version" else "f" * 64}))
    monkeypatch.setattr(legacy, "load_verified", lambda _: claim)
    counted = _CountingCalculation(calculation)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == 0
    assert not (tmp_path / "results" / "v2").exists()
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()


@pytest.mark.parametrize("boundary", ("reuse", "commit"))
@pytest.mark.parametrize("mutation", ("value-list", "readiness-list", "partition-subclass", "wrong-partition-family"))
def test_v2_original_result_nested_contract_is_validated_before_serialization(
    tmp_path, monkeypatch, boundary, mutation
):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, result = _precommit(plan, calculation, results)
    evidence._publish_verified(sealed, result)
    manifest = replace(result.manifest)
    field = "readiness_partitions" if mutation == "readiness-list" else "value_partitions"
    partitions = getattr(manifest, field)
    if mutation.endswith("list"):
        value = list(partitions)
    else:
        partition = partitions[0]

        class _PartitionSubclass(type(partition)):
            pass

        changed = _PartitionSubclass(**{item.name: getattr(partition, item.name) for item in fields(partition)})
        value = (changed, *partitions[1:]) if mutation == "partition-subclass" else (result, *partitions[1:])
    object.__setattr__(manifest, field, value)
    claim = replace(result, manifest=manifest)
    counted = _CountingCalculation(calculation)
    if boundary == "reuse":
        monkeypatch.setattr(results, "load_verified", lambda _: claim)
    else:
        monkeypatch.setattr(
            evidence,
            "require_for_result",
            lambda *args: (_ for _ in ()).throw(
                OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", "incomplete")
            ),
        )
        monkeypatch.setattr(results, "commit", lambda *args: claim)
        monkeypatch.setattr(
            evidence,
            "_publish_verified",
            lambda *args: (_ for _ in ()).throw(AssertionError("malformed typed Result reached publication")),
        )
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is (
        OnlyResearchJobPhase.RESULT_REUSE if boundary == "reuse" else OnlyResearchJobPhase.RESULT_COMMIT
    )
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == (0 if boundary == "reuse" else 1)


@pytest.mark.parametrize("boundary", ("reuse", "publish"))
@pytest.mark.parametrize("mutation", ("list", "binding-subclass", "wrong-binding-family", "duplicate", "wrong-owner"))
def test_v2_original_evidence_nested_contract_is_validated_before_serialization(
    tmp_path, monkeypatch, boundary, mutation
):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, result = _precommit(plan, calculation, results)
    witness = evidence._publish_verified(sealed, result)
    binding = witness.research_implementation_bindings[0]

    class _BindingSubclass(type(binding)):
        pass

    changed = _BindingSubclass(binding.node_fingerprint, binding.research_implementation_fingerprint)
    value = {
        "list": list(witness.research_implementation_bindings),
        "binding-subclass": (changed,),
        "wrong-binding-family": (result,),
        "duplicate": (binding, binding),
        "wrong-owner": (replace(binding, node_fingerprint="f" * 64),),
    }[mutation]
    claim = replace(witness)
    object.__setattr__(claim, "research_implementation_bindings", value)
    counted = _CountingCalculation(calculation)
    if boundary == "reuse":
        monkeypatch.setattr(evidence, "require_for_result", lambda *args: claim)
    else:
        monkeypatch.setattr(
            evidence,
            "require_for_result",
            lambda *args: (_ for _ in ()).throw(
                OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", "incomplete")
            ),
        )
        monkeypatch.setattr(evidence, "_publish_verified", lambda *args: claim)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is (
        OnlyResearchJobPhase.RESULT_REUSE if boundary == "reuse" else OnlyResearchJobPhase.RESULT_COMMIT
    )
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == (0 if boundary == "reuse" else 1)


@pytest.mark.parametrize(
    "mutation", ("partition-key", "duplicate", "order", "schema", "metadata", "timestamp", "null", "value")
)
def test_v2_job_rejects_numeric_parity_mismatch_without_publication(tmp_path, monkeypatch, mutation):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    old = legacy.commit(
        calculation.execute(plan.dataset_snapshot_fingerprint, plan.calculation_graph), plan.calculation_graph
    )
    outputs = list(old.outputs)
    item, table = outputs[0], outputs[0].table
    if mutation == "partition-key":
        outputs[0] = replace(item, instrument_id="other")
    elif mutation == "duplicate":
        outputs.append(item)
    elif mutation == "order":
        outputs.reverse()
    else:
        if mutation == "metadata":
            table = table.replace_schema_metadata({"owner": "wrong"})
        elif mutation == "schema":
            table = table.set_column(1, "value", pa.array([1] * table.num_rows, type=pa.int64()))
        else:
            column = "ts_event_ns" if mutation == "timestamp" else "value"
            values = table[column].to_pylist()
            values[0] = None if mutation == "null" else values[0] + (1 if mutation == "timestamp" else Decimal("1"))
            index = table.column_names.index(column)
            table = table.set_column(index, table.schema.field(index), pa.array(values, type=table[column].type))
        outputs[0] = replace(item, table=table)
    monkeypatch.setattr(legacy, "load_verified", lambda _: replace(old, outputs=tuple(outputs)))
    counted = _CountingCalculation(calculation)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.CALCULATION_EXECUTION
    assert raised.value.code == "READINESS_NUMERIC_PARITY_MISMATCH"
    assert counted.calls == 1
    assert not (tmp_path / "results" / "v2").exists()
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()


def test_v2_numeric_parity_ignores_arrow_chunk_layout(tmp_path, monkeypatch):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    old = legacy.commit(
        calculation.execute(plan.dataset_snapshot_fingerprint, plan.calculation_graph), plan.calculation_graph
    )
    outputs = tuple(
        replace(item, table=pa.concat_tables([item.table.slice(0, 1), item.table.slice(1)])) for item in old.outputs
    )
    monkeypatch.setattr(legacy, "load_verified", lambda _: replace(old, outputs=outputs))
    assert _job(calculation, legacy, results, evidence).execute(plan).disposition is OnlyResearchJobDisposition.EXECUTED


@pytest.mark.parametrize(
    "boundary,code,phase",
    (
        ("result-reuse", "RESULT_INVALID", OnlyResearchJobPhase.RESULT_REUSE),
        ("evidence-reuse", "RESEARCH_EXECUTION_EVIDENCE_CORRUPT", OnlyResearchJobPhase.RESULT_REUSE),
        ("backend", "RESEARCH_EXECUTION_FAILED", OnlyResearchJobPhase.CALCULATION_EXECUTION),
        ("result-commit", "DETERMINISTIC_RESULT_CONFLICT", OnlyResearchJobPhase.RESULT_COMMIT),
        ("evidence-publish", "RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", OnlyResearchJobPhase.RESULT_COMMIT),
    ),
)
def test_v2_failure_phase_preserves_stable_authority_error(tmp_path, monkeypatch, boundary, code, phase):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    if boundary == "evidence-reuse":
        _precommit(plan, calculation, results)
    owner, name = {
        "result-reuse": (results, "load_verified"),
        "evidence-reuse": (evidence, "require_for_result"),
        "backend": (calculation, "_execute_verified_v2"),
        "result-commit": (results, "commit"),
        "evidence-publish": (evidence, "_publish_verified"),
    }[boundary]

    def fail(*args):
        error = (
            OnlyResearchCalculationResultStoreError if boundary.startswith("result-") else OnlyResearchCalculationError
        )
        raise error(code, "injected")

    monkeypatch.setattr(owner, name, fail)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(calculation, legacy, results, evidence).execute(plan)
    assert raised.value.phase is phase
    assert raised.value.code == code


@pytest.mark.parametrize("boundary", ("reuse", "commit"))
@pytest.mark.parametrize(
    "field",
    (
        "manifest",
        "calculation_fingerprint",
        "dataset_snapshot_fingerprint",
        "calculation_graph_fingerprint",
        "calculation_graph",
        "result_content_fingerprint",
        "calculation_result_fingerprint",
        "schema_version",
        "readiness_contract_version",
        "value_partitions",
        "readiness_partitions",
    ),
)
def test_v2_result_proof_mutations_cannot_construct_success_or_trigger_rebuild(tmp_path, monkeypatch, boundary, field):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, result = _precommit(plan, calculation, results)
    witness = evidence._publish_verified(sealed, result)
    manifest = replace(result.manifest)
    if field == "manifest":
        claim = replace(result, manifest=None)
    else:
        value = (
            True
            if field.endswith("version")
            else ()
            if field.endswith("partitions")
            else None
            if field == "calculation_graph"
            else "f" * 64
        )
        object.__setattr__(manifest, field, value)
        claim = replace(result, manifest=manifest)
    counted = _CountingCalculation(calculation)
    if boundary == "reuse":
        monkeypatch.setattr(results, "load_verified", lambda _: claim)
    else:
        monkeypatch.setattr(
            evidence,
            "require_for_result",
            lambda *args: (_ for _ in ()).throw(
                OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", "incomplete")
            ),
        )
        monkeypatch.setattr(results, "commit", lambda *args: claim)
        monkeypatch.setattr(
            evidence,
            "_publish_verified",
            lambda *args: (_ for _ in ()).throw(AssertionError("invalid Result cannot reach Evidence")),
        )
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is (
        OnlyResearchJobPhase.RESULT_REUSE if boundary == "reuse" else OnlyResearchJobPhase.RESULT_COMMIT
    )
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == (0 if boundary == "reuse" else 1)
    if boundary == "commit":
        assert evidence.load_verified(witness.evidence_fingerprint) == witness


@pytest.mark.parametrize("boundary", ("reuse", "publish"))
@pytest.mark.parametrize(
    "field",
    (
        "whole",
        "calculation_fingerprint",
        "dataset_snapshot_fingerprint",
        "calculation_graph_fingerprint",
        "calculation_result_fingerprint",
        "result_content_fingerprint",
        "schema_version",
        "execution_contract_version",
        "calculation_result_schema_version",
        "readiness_contract_version",
        "research_implementation_bindings",
        "authoring_generation_fingerprint",
    ),
)
def test_v2_evidence_proof_mutations_cannot_construct_success(tmp_path, monkeypatch, boundary, field):
    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, result = _precommit(plan, calculation, results)
    witness = evidence._publish_verified(sealed, result, "a" * 64)
    claim = replace(witness)
    if field == "whole":
        claim = None
    else:
        value = (
            True
            if field.endswith("version") and field != "execution_contract_version"
            else ()
            if field == "research_implementation_bindings"
            else "RESEARCH_CALCULATION_EXECUTION_V1"
            if field == "execution_contract_version"
            else "f" * 64
        )
        object.__setattr__(claim, field, value)
    counted = _CountingCalculation(calculation)
    if boundary == "reuse":
        monkeypatch.setattr(evidence, "require_for_result", lambda *args: claim)
    else:
        monkeypatch.setattr(
            evidence,
            "require_for_result",
            lambda *args: (_ for _ in ()).throw(
                OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", "incomplete")
            ),
        )
        monkeypatch.setattr(evidence, "_publish_verified", lambda *args: claim)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence, "a" * 64).execute(plan)
    assert raised.value.phase is (
        OnlyResearchJobPhase.RESULT_REUSE if boundary == "reuse" else OnlyResearchJobPhase.RESULT_COMMIT
    )
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == (0 if boundary == "reuse" else 1)


def test_v2_mutated_publication_rejected_before_any_authority_call(tmp_path):
    plan, _, _, _, _ = readiness_job_case(tmp_path)
    object.__setattr__(plan.publication, "execution_evidence_schema_version", True)
    never = _Never()
    with pytest.raises(OnlyResearchJobError) as raised:
        OnlyResearchJobExecutor(
            never, never, never, readiness_result_store=never, readiness_execution_evidence_store=never
        ).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.PLAN_VALIDATION
    assert raised.value.code == "RESEARCH_JOB_INVALID"


def test_v2_job_hard_death_after_result_commit_recovers_in_fresh_process(tmp_path):
    code = """
import os, sys
from pathlib import Path
from tests.research.job.support import readiness_job_case
from tests.research.job.test_readiness_publication import _job
plan, calculation, legacy, results, evidence = readiness_job_case(Path(sys.argv[1]))
evidence._publish_verified = lambda *args: os._exit(86)
_job(calculation, legacy, results, evidence).execute(plan)
"""
    assert subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=False).returncode == 86
    plan, _, _, results, _ = readiness_job_case(tmp_path)
    result = results.load_verified(plan.calculation_fingerprint)
    before = _bytes(_result_root(tmp_path, plan))
    recover = """
import json, sys
from dataclasses import asdict
from pathlib import Path
from tests.research.job.support import readiness_job_case
from tests.research.job.test_readiness_publication import _job, _CountingCalculation
plan, calculation, legacy, results, evidence = readiness_job_case(Path(sys.argv[1]))
counted = _CountingCalculation(calculation)
job = _job(counted, legacy, results, evidence)
first, second = job.execute(plan), job.execute(plan)
assert counted.calls == 1
assert first.disposition == 'EXECUTED' and second.disposition == 'REUSED'
assert first.calculation_execution_evidence_fingerprint == second.calculation_execution_evidence_fingerprint
print(json.dumps(asdict(first)))
"""
    recovered = json.loads(subprocess.check_output([sys.executable, "-c", recover, str(tmp_path)], text=True))
    assert recovered["calculation_result_fingerprint"] == result.manifest.calculation_result_fingerprint
    assert before == _bytes(_result_root(tmp_path, plan))


def test_v2_result_only_recovery_conflicting_live_readiness_does_not_rewrite_result(tmp_path):
    from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from tests.research.calculation.test_execution_readiness_v2 import _AtomicBackend, _registry

    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    sealed, _ = _precommit(plan, calculation, results)
    before = _bytes(_result_root(tmp_path, plan))

    def values(outputs, readiness, calls):
        outputs["value"] = sealed.execution.outputs[calls - 1].table["value"]

    different = OnlyResearchCalculationExecutor(
        calculation._store, OnlyResearchCalculationBackendResolver(_registry(_AtomicBackend(values)))
    )
    counted = _CountingCalculation(different)
    with pytest.raises(OnlyResearchJobError) as raised:
        _job(counted, legacy, results, evidence).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_COMMIT
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert counted.calls == 1
    assert before == _bytes(_result_root(tmp_path, plan))
    assert not (tmp_path / "semantic" / "calculation-execution-evidence").exists()
