from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from onlyalpha.research import (
    OnlyResearchResult,
    OnlyResearchResultDisposition,
    OnlyResearchResultStoreError,
)
from tests.research.result.support import result_case


def _target(root: Path, fingerprint: str) -> Path:
    return root / "research-results" / "sha256" / fingerprint[:2] / fingerprint


def _physical_state(root: Path) -> tuple[tuple[str, str, bytes | str], ...]:
    return tuple(
        sorted(
            (
                path.name,
                "symlink" if path.is_symlink() else "file",
                os.readlink(path) if path.is_symlink() else path.read_bytes(),
            )
            for path in root.iterdir()
        )
    )


class _ControlledStatisticsStore:
    def __init__(self, values, failure: Exception | None = None):  # type: ignore[no-untyped-def]
        self._values = values
        self._failure = failure

    def load_verified(self, statistics_fingerprint: str):  # type: ignore[no-untyped-def]
        if self._failure is not None:
            raise self._failure
        return self._values[statistics_fingerprint]


def _upstream(reference, dataset: str, **changes):  # type: ignore[no-untyped-def]
    values = {
        "statistics_fingerprint": reference.statistics_fingerprint,
        "statistics_result_fingerprint": reference.statistics_result_fingerprint,
        "dataset_snapshot_fingerprint": dataset,
        **changes,
    }
    return SimpleNamespace(manifest=SimpleNamespace(**values))


def _forged_result(result, **changes):  # type: ignore[no-untyped-def]
    values = {
        "statistics_results": result.manifest.statistics_results,
        "dataset_snapshot_fingerprint": result.manifest.dataset_snapshot_fingerprint,
        "research_result_content_fingerprint": result.manifest.research_result_content_fingerprint,
        "research_result_plan_fingerprint": result.manifest.research_result_plan_fingerprint,
        "research_result_fingerprint": result.manifest.research_result_fingerprint,
        **changes,
    }
    return OnlyResearchResult(SimpleNamespace(**values))  # type: ignore[arg-type]


def test_atomic_commit_verified_load_and_equal_recommit_is_reused(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path)

    first = store.commit(result)
    second = store.commit(result)
    loaded = store.load_verified(plan.fingerprint)

    assert first.disposition is OnlyResearchResultDisposition.EXECUTED
    assert second.disposition is OnlyResearchResultDisposition.REUSED
    assert first.research_result_fingerprint == second.research_result_fingerprint
    assert loaded.manifest == result.manifest
    assert store.exists(plan.fingerprint)
    assert not any(path.name.startswith(".stage-") for path in _target(tmp_path, plan.fingerprint).parent.iterdir())


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown",
        "plan",
        "dataset",
        "reference",
        "content",
        "result",
        "created_at",
        "unexpected_file",
        "missing_manifest",
    ),
)
def test_own_corruption_is_never_missing_or_overwritten(tmp_path, mutation: str) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    store.commit(result)
    root = _target(tmp_path, plan.fingerprint)
    manifest_path = root / "manifest.json"
    if mutation == "unexpected_file":
        (root / "extra").write_text("x", encoding="utf-8")
    elif mutation == "missing_manifest":
        manifest_path.unlink()
    else:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "unknown":
            payload["unknown"] = True
        elif mutation == "plan":
            payload["research_result_plan_fingerprint"] = "1" * 64
        elif mutation == "dataset":
            payload["dataset_snapshot_fingerprint"] = "2" * 64
        elif mutation == "reference":
            payload["statistics_results"][0]["statistics_result_fingerprint"] = "3" * 64
        elif mutation == "content":
            payload["research_result_content_fingerprint"] = "4" * 64
        elif mutation == "result":
            payload["research_result_fingerprint"] = "5" * 64
        else:
            payload["created_at"] = "not-a-time"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.load_verified(plan.fingerprint)
    assert raised.value.code == "RESEARCH_RESULT_CORRUPT"
    corrupt_state = _physical_state(root)
    with pytest.raises(OnlyResearchResultStoreError) as recommit:
        store.commit(result)
    assert recommit.value.code == "RESEARCH_RESULT_CORRUPT"
    assert _physical_state(root) == corrupt_state


@pytest.mark.parametrize("mutation", ("malformed_json", "top_level", "manifest_symlink"))
def test_physical_manifest_corruption_is_fail_closed_and_immutable(tmp_path, mutation: str) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    store.commit(result)
    root = _target(tmp_path, plan.fingerprint)
    manifest_path = root / "manifest.json"
    if mutation == "malformed_json":
        manifest_path.write_text("{", encoding="utf-8")
    elif mutation == "top_level":
        manifest_path.write_text("[]", encoding="utf-8")
    else:
        original = root / "original-manifest"
        manifest_path.rename(original)
        manifest_path.symlink_to(original.name)
    corrupt_state = _physical_state(root)

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.load_verified(plan.fingerprint)
    assert raised.value.code == "RESEARCH_RESULT_CORRUPT"
    with pytest.raises(OnlyResearchResultStoreError) as recommit:
        store.commit(result)
    assert recommit.value.code == "RESEARCH_RESULT_CORRUPT"
    assert _physical_state(root) == corrupt_state


def test_authority_root_symlink_and_path_identity_mismatch_are_corrupt(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path / "root-symlink")
    target = _target(tmp_path / "root-symlink", plan.fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(OnlyResearchResultStoreError) as symlinked:
        store.load_verified(plan.fingerprint)
    assert symlinked.value.code == "RESEARCH_RESULT_CORRUPT"

    plan, _, store, result, _ = result_case(tmp_path / "path-mismatch")
    store.commit(result)
    wrong_identity = "f" * 64
    wrong_target = _target(tmp_path / "path-mismatch", wrong_identity)
    wrong_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_target(tmp_path / "path-mismatch", plan.fingerprint), wrong_target)
    with pytest.raises(OnlyResearchResultStoreError) as mismatched:
        store.load_verified(wrong_identity)
    assert mismatched.value.code == "RESEARCH_RESULT_CORRUPT"
    assert "path identity mismatch" in mismatched.value.detail


def test_missing_and_invalid_identity_have_exact_not_found_code(tmp_path) -> None:
    _, _, store, _, _ = result_case(tmp_path)
    for fingerprint in ("bad", "f" * 64):
        with pytest.raises(OnlyResearchResultStoreError) as raised:
            store.load_verified(fingerprint)
        assert raised.value.code == "RESEARCH_RESULT_NOT_FOUND"


def test_upstream_missing_or_corrupt_fails_referential_integrity(tmp_path) -> None:
    plan, _, store, result, statistics_store = result_case(tmp_path)
    store.commit(result)
    reference = result.manifest.statistics_results[0]
    statistics_root = (
        tmp_path
        / "statistics-results"
        / "sha256"
        / reference.statistics_fingerprint[:2]
        / reference.statistics_fingerprint
    )
    (statistics_root / "manifest.json").unlink()

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.load_verified(plan.fingerprint)
    assert raised.value.code == "RESEARCH_RESULT_CORRUPT"
    assert statistics_store.exists(reference.statistics_fingerprint)


def test_admission_rejects_wrong_object_and_normalizes_ordinary_upstream_failures(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    with pytest.raises(OnlyResearchResultStoreError) as wrong_type:
        store.commit(object())  # type: ignore[arg-type]
    assert wrong_type.value.code == "RESEARCH_RESULT_INVALID"
    assert not store.exists(plan.fingerprint)

    failing_store = type(store)(
        tmp_path / "ordinary-failure",
        _ControlledStatisticsStore({}, RuntimeError("unstable internal error")),
    )
    with pytest.raises(OnlyResearchResultStoreError) as ordinary:
        failing_store.commit(result)
    assert ordinary.value.code == "RESEARCH_RESULT_INVALID"
    assert "unstable internal error" in ordinary.value.detail
    assert not failing_store.exists(plan.fingerprint)


def test_formal_upstream_store_error_is_preserved_without_publication(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    upstream_error = OnlyResearchResultStoreError("UPSTREAM_CORRUPT", "injected")
    failing_store = type(store)(tmp_path / "formal-failure", _ControlledStatisticsStore({}, upstream_error))

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        failing_store.commit(result)
    assert raised.value is upstream_error
    assert not failing_store.exists(plan.fingerprint)


@pytest.mark.parametrize(
    ("mutation", "detail"),
    (
        ("logical_identity", "logical identity mismatch"),
        ("result_identity", "Result identity mismatch"),
        ("cross_dataset", "different Dataset Snapshots"),
        ("dataset_linkage", "Dataset Snapshot linkage mismatch"),
        ("content", "content fingerprint mismatch"),
        ("result", "Research Result fingerprint mismatch"),
    ),
)
def test_admission_enforces_exact_upstream_and_manifest_linkage(tmp_path, mutation: str, detail: str) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    references = result.manifest.statistics_results
    dataset = result.manifest.dataset_snapshot_fingerprint
    upstream = {reference.statistics_fingerprint: _upstream(reference, dataset) for reference in references}
    candidate = result
    if mutation == "logical_identity":
        upstream[references[0].statistics_fingerprint] = _upstream(
            references[0], dataset, statistics_fingerprint="e" * 64
        )
    elif mutation == "result_identity":
        upstream[references[0].statistics_fingerprint] = _upstream(
            references[0], dataset, statistics_result_fingerprint="e" * 64
        )
    elif mutation == "cross_dataset":
        upstream[references[1].statistics_fingerprint] = _upstream(references[1], "e" * 64)
    elif mutation == "dataset_linkage":
        candidate = _forged_result(result, dataset_snapshot_fingerprint="e" * 64)
    elif mutation == "content":
        candidate = _forged_result(result, research_result_content_fingerprint="e" * 64)
    else:
        candidate = _forged_result(result, research_result_fingerprint="e" * 64)
    checked_store = type(store)(tmp_path / f"admission-{mutation}", _ControlledStatisticsStore(upstream))

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        checked_store.commit(candidate)
    assert raised.value.code == "RESEARCH_RESULT_INVALID"
    assert detail in raised.value.detail
    assert not checked_store.exists(plan.fingerprint)


def test_restart_reuse_and_physical_root_neutrality(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    store.commit(result)
    plan_path = tmp_path / "research-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    script = """
import json, sys
from datetime import UTC, datetime
from pathlib import Path
from onlyalpha.research import *
root=Path(sys.argv[1])
plan=OnlyResearchResultPlan.from_dict(json.loads((root/'research-plan.json').read_text()))
datasets=OnlyParquetResearchDatasetSnapshotStore(root/'datasets')
calculations=OnlyParquetResearchCalculationResultStore(root/'calculation-results',datasets)
statistics=OnlyParquetResearchStatisticsResultStore(root/'statistics-results',calculations)
assembler=OnlyResearchResultAssembler(statistics,audit_time=lambda: datetime(2030,1,1,tzinfo=UTC))
store=OnlyJsonResearchResultStore(root/'research-results',statistics)
outcome=store.commit(assembler.assemble(plan))
print(outcome.disposition.value,outcome.research_result_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], check=True, capture_output=True, text=True, env=os.environ.copy()
    )
    assert completed.stdout.strip() == f"REUSED {result.manifest.research_result_fingerprint}"


def test_deterministic_conflict_is_fail_closed(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan, _, store, result, _ = result_case(tmp_path)
    store.commit(result)
    changed_reference = replace(
        result.manifest.statistics_results[0],
        statistics_result_fingerprint="f" * 64,
    )
    changed_references = (changed_reference, *result.manifest.statistics_results[1:])
    from onlyalpha.research import only_research_result_content_fingerprint, only_research_result_fingerprint

    content = only_research_result_content_fingerprint(tuple(item.to_dict() for item in changed_references))
    changed_manifest = replace(
        result.manifest,
        statistics_results=changed_references,
        research_result_content_fingerprint=content,
        research_result_fingerprint=only_research_result_fingerprint(plan.fingerprint, content),
    )
    changed = replace(result, manifest=changed_manifest)
    target = _target(tmp_path, plan.fingerprint)
    before = _physical_state(target)
    monkeypatch.setattr(store, "_admit", lambda candidate: candidate)
    monkeypatch.setattr(store, "load_verified", lambda fingerprint: result)

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.commit(changed)
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert _physical_state(target) == before


def test_staged_verification_failure_is_atomic_and_cleans_staging(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan, _, store, result, _ = result_case(tmp_path)
    original = store._read_verified

    def fail_stage(root, expected):  # type: ignore[no-untyped-def]
        if root.name.startswith(".stage-"):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_CORRUPT", "injected stage failure")
        return original(root, expected)

    monkeypatch.setattr(store, "_read_verified", fail_stage)
    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.commit(result)
    assert raised.value.code == "RESEARCH_RESULT_COMMIT_FAILED"
    target = _target(tmp_path, plan.fingerprint)
    assert not target.exists()
    assert not [item for item in target.parent.iterdir() if item.name.startswith(".stage-")]


def test_rename_failure_is_atomic_and_cleans_staging(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan, _, store, result, _ = result_case(tmp_path)
    import onlyalpha.research.result.result_store as module

    monkeypatch.setattr(module.os, "rename", lambda source, target: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.commit(result)
    assert raised.value.code == "RESEARCH_RESULT_COMMIT_FAILED"
    target = _target(tmp_path, plan.fingerprint)
    assert not target.exists()
    assert not [item for item in target.parent.iterdir() if item.name.startswith(".stage-")]


def test_publication_race_loser_verifies_and_reuses_winner(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan, _, store, result, _ = result_case(tmp_path)
    import onlyalpha.research.result.result_store as module

    original = module.os.rename

    def publish_then_report_race(source, target):  # type: ignore[no-untyped-def]
        original(source, target)
        raise OSError("winner already published")

    monkeypatch.setattr(module.os, "rename", publish_then_report_race)
    outcome = store.commit(result)
    assert outcome.disposition is OnlyResearchResultDisposition.REUSED
    target = _target(tmp_path, plan.fingerprint)
    assert target.is_dir()
    assert not [item for item in target.parent.iterdir() if item.name.startswith(".stage-")]


def test_publication_race_conflicting_winner_is_preserved_and_rejected(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan, _, store, result, _ = result_case(tmp_path)
    store.commit(result)
    target = _target(tmp_path, plan.fingerprint)
    winner = tmp_path / "race-winner"
    shutil.copytree(target, winner)
    shutil.rmtree(target)
    winner_state = _physical_state(winner)

    changed_reference = replace(result.manifest.statistics_results[0], statistics_result_fingerprint="f" * 64)
    changed_references = (changed_reference, *result.manifest.statistics_results[1:])
    from onlyalpha.research import only_research_result_content_fingerprint, only_research_result_fingerprint

    content = only_research_result_content_fingerprint(tuple(item.to_dict() for item in changed_references))
    changed = replace(
        result,
        manifest=replace(
            result.manifest,
            statistics_results=changed_references,
            research_result_content_fingerprint=content,
            research_result_fingerprint=only_research_result_fingerprint(plan.fingerprint, content),
        ),
    )
    original_read = store._read_verified

    def verify_stage(root, expected):  # type: ignore[no-untyped-def]
        return changed if root.name.startswith(".stage-") else original_read(root, expected)

    def publish_conflicting_winner(_source, race_target):  # type: ignore[no-untyped-def]
        shutil.copytree(winner, race_target)
        raise OSError("conflicting winner already published")

    import onlyalpha.research.result.result_store as module

    monkeypatch.setattr(store, "_admit", lambda candidate: candidate)
    monkeypatch.setattr(store, "_read_verified", verify_stage)
    monkeypatch.setattr(module.os, "rename", publish_conflicting_winner)

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.commit(changed)
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert _physical_state(target) == winner_state
    assert not [item for item in target.parent.iterdir() if item.name.startswith(".stage-")]


def test_concurrent_equal_publication_converges_to_one_authority(tmp_path) -> None:
    plan, _, store, result, _ = result_case(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: store.commit(result), range(2)))

    assert {outcome.disposition for outcome in outcomes} == {
        OnlyResearchResultDisposition.EXECUTED,
        OnlyResearchResultDisposition.REUSED,
    }
    assert len({outcome.research_result_fingerprint for outcome in outcomes}) == 1
    target = _target(tmp_path, plan.fingerprint)
    assert [item.name for item in target.parent.iterdir() if not item.name.startswith(".stage-")] == [plan.fingerprint]
    assert not [item for item in target.parent.iterdir() if item.name.startswith(".stage-")]
