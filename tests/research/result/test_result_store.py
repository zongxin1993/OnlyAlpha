from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.research import (
    OnlyResearchResultDisposition,
    OnlyResearchResultStoreError,
)
from tests.research.result.support import result_case


def _target(root: Path, fingerprint: str) -> Path:
    return root / "research-results" / "sha256" / fingerprint[:2] / fingerprint


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
    with pytest.raises(OnlyResearchResultStoreError) as recommit:
        store.commit(result)
    assert recommit.value.code == "RESEARCH_RESULT_CORRUPT"


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
    monkeypatch.setattr(store, "_admit", lambda candidate: candidate)
    monkeypatch.setattr(store, "load_verified", lambda fingerprint: result)

    with pytest.raises(OnlyResearchResultStoreError) as raised:
        store.commit(changed)
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"
