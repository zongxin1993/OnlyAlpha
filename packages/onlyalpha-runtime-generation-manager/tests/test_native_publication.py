"""Real installed native publication, with no production Host capability or Run mutation."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore

from tests.runtime_support.chart_execution_host import compile_chart_in_exact_host
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment
from tests.runtime_support.native_calculation_publication import PUBLISH as _PUBLISH
from tests.runtime_support.native_calculation_publication import provision_native_publication_roots

pytestmark = pytest.mark.contract


@pytest.fixture
def native_publication_case(exact_host_environment, tmp_path):
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    builder, built, host_type, _ = exact_host_environment
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="fixture", occurred_at=now)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=now)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=now)
    host = host_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
    try:
        chart, _, compilation = compile_chart_in_exact_host(tmp_path, registry, builder, generation, host)
    finally:
        host.close()
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps(compilation.resolution.to_dict()))
    (tmp_path / "artifact-store-root.txt").write_text(str(builder.artifact_store.root))
    semantic = tmp_path / "semantic"
    semantic.mkdir()
    return chart, compilation, registry, builder.artifact_store.root.parent / "built" / "bin" / "python", frozen


def test_installed_native_publication_and_fresh_process_exact_reuse(native_publication_case, tmp_path):
    chart, compilation, registry, python, _ = native_publication_case
    provision_native_publication_roots(tmp_path)
    source = {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    registry_bytes = {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}
    first = json.loads(
        subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    second = json.loads(
        subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "no_reexecute"], text=True)
    )
    assert first == second
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert first["result"]["schema_version"] == 4
    proof = first["evidence"]["runtime_execution_provenance"]
    assert proof["runtime_generation_fingerprint"] == compilation.runtime_generation_fingerprint
    assert (
        proof["validation_evidence_fingerprint"]
        == registry.load_validation_evidence(compilation.runtime_generation_fingerprint).validation_evidence_fingerprint
    )
    assert source == {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    assert registry_bytes == {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}


def test_ambient_process_cannot_issue_runtime_provenance(native_publication_case, tmp_path, monkeypatch):
    from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_result

    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor

    _, compilation, registry, _, _ = native_publication_case

    def forbidden(*args, **kwargs):
        raise AssertionError("ambient process reached native backend")

    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden)
    with pytest.raises(RuntimeError, match="RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH"):
        only_publish_native_calculation_result(
            generations=registry,
            distribution_artifact_store=OnlyLocalImmutableArtifactStore(
                Path((tmp_path / "artifact-store-root.txt").read_text())
            ),
            frozen=compilation.resolution,
            dataset_store_root=tmp_path / "chart-input" / "dataset",
            calculation_result_root=tmp_path / "calculation-results",
            execution_evidence_root=tmp_path / "semantic",
            research_result_root=tmp_path / "research-results",
            research_artifact_root=tmp_path / "artifacts",
            audit_time=lambda: datetime(2026, 10, 9, tzinfo=UTC),
        )
    assert not (tmp_path / "calculation-results").exists()
    assert not (tmp_path / "research-results").exists()


def test_native_foundation_rejects_unverified_authoring_provenance(native_publication_case, tmp_path):
    from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_result

    _, compilation, registry, _, _ = native_publication_case
    with pytest.raises(ValueError, match="no verified Authoring Generation relation"):
        only_publish_native_calculation_result(
            generations=registry,
            distribution_artifact_store=OnlyLocalImmutableArtifactStore(
                Path((tmp_path / "artifact-store-root.txt").read_text())
            ),
            frozen=compilation.resolution,
            dataset_store_root=tmp_path / "chart-input" / "dataset",
            calculation_result_root=tmp_path / "calculation-results",
            execution_evidence_root=tmp_path / "semantic",
            research_result_root=tmp_path / "research-results",
            research_artifact_root=tmp_path / "artifacts",
            audit_time=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            authoring_generation_fingerprint="a" * 64,
        )
    assert not (tmp_path / "calculation-results").exists()


def test_retained_result_with_missing_calculation_cannot_reconstruct_upstream(native_publication_case, tmp_path):
    _, _, _, python, _ = native_publication_case
    provision_native_publication_roots(tmp_path)
    first = json.loads(
        subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    calculation = first["evidence"]["calculation_fingerprint"]
    root = tmp_path / "calculation-results" / "v2" / "sha256" / calculation[:2] / calculation
    root.rename(tmp_path / "retained-unavailable-calculation")
    evidence = first["evidence"]["evidence_fingerprint"]
    evidence_root = tmp_path / "semantic" / "calculation-execution-evidence" / "v2" / "sha256" / evidence[:2] / evidence
    evidence_root.rename(tmp_path / "retained-unavailable-evidence")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    attempt = subprocess.run(
        [str(python), "-I", "-c", _PUBLISH, str(tmp_path), "no_reexecute"], capture_output=True, text=True
    )
    assert attempt.returncode != 0
    assert "RESEARCH_RESULT_CORRUPT" in attempt.stderr
    assert "reuse reexecuted" not in attempt.stderr
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert not root.exists()
    assert not evidence_root.exists()


@pytest.mark.parametrize("missing", ["calculation", "evidence", "result"])
def test_installed_guard_handover_never_recreates_an_observed_prefix(native_publication_case, tmp_path, missing):
    import hashlib

    _, _, _, python, _ = native_publication_case
    provision_native_publication_roots(tmp_path)
    first = json.loads(
        subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    calculation = first["evidence"]["calculation_fingerprint"]
    evidence = first["evidence"]["evidence_fingerprint"]
    plan = first["result"]["research_result_plan_fingerprint"]
    paths = {
        "calculation": tmp_path / "calculation-results" / "v2" / "sha256" / calculation[:2] / calculation,
        "evidence": tmp_path
        / "semantic"
        / "calculation-execution-evidence"
        / "v2"
        / "sha256"
        / evidence[:2]
        / evidence,
        "result": tmp_path / "research-results" / "sha256" / plan[:2] / plan,
    }
    # Fault injected after the guard's successful release, in the real installed
    # process, before Job entry. This launcher is not the production wire protocol.
    fault = r"""
import hashlib
from onlyalpha_runtime_generation_manager import native_publication
issue = native_publication._only_issue_research_runtime_execution_context
def lose_prefix(*args, **kwargs):
    context = issue(*args, **kwargs)
    root = Path(sys.argv[1])
    target = Path(sys.argv[3])
    target.rename(root / 'unavailable-prefix')
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()}
    (root/'guard-handover-snapshot.json').write_text(json.dumps(before))
    return context
native_publication._only_issue_research_runtime_execution_context = lose_prefix
"""
    launch = _PUBLISH.replace(
        "result, evidence = only_publish_native_calculation_result(",
        fault + "\nresult, evidence = only_publish_native_calculation_result(",
    )
    attempt = subprocess.run(
        [str(python), "-I", "-c", launch, str(tmp_path), "execute", str(paths[missing])], capture_output=True, text=True
    )
    assert attempt.returncode != 0
    assert {
        "calculation": "RESULT_NOT_FOUND",
        "evidence": "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND",
        "result": "RESEARCH_RESULT_NOT_FOUND",
    }[missing] in attempt.stderr
    snapshot = tmp_path / "guard-handover-snapshot.json"
    assert json.loads(snapshot.read_text()) == {
        str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file() and path != snapshot
    }
    assert not paths[missing].exists()
