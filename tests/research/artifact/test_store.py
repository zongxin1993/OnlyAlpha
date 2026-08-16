from __future__ import annotations

import json
import os
from hashlib import sha256
from types import SimpleNamespace

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import (
    OnlyParquetResearchArtifactStore,
    OnlyResearchArtifactDisposition,
    OnlyResearchArtifactStoreError,
)
from tests.research.artifact.support import artifact_case, artifact_target


def test_atomic_commit_reentry_and_physical_location_time_neutrality(tmp_path) -> None:
    _, _, _, _, first_candidate, first_store = artifact_case(tmp_path / "one", year=2026)
    _, _, _, _, second_candidate, second_store = artifact_case(tmp_path / "two", year=2035)
    first = first_store.commit(first_candidate)
    reused = first_store.commit(first_candidate)
    second = second_store.commit(second_candidate)

    assert first.disposition is OnlyResearchArtifactDisposition.EXECUTED
    assert reused.disposition is OnlyResearchArtifactDisposition.REUSED
    assert first.artifact_content_fingerprint == reused.artifact_content_fingerprint
    assert first.artifact_content_fingerprint == second.artifact_content_fingerprint
    assert first_store.load_verified(first_candidate.research_result_fingerprint).rows


def test_portable_load_is_self_contained_when_all_upstream_roots_are_unavailable(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    for name in ("research-results", "statistics-results", "calculation-results", "datasets"):
        root = tmp_path / name
        if root.exists():
            root.rename(tmp_path / f"unavailable-{name}")

    fresh = OnlyParquetResearchArtifactStore(tmp_path / "research-artifacts")
    loaded = fresh.load_verified(candidate.research_result_fingerprint)
    assert loaded.manifest.artifact_content_fingerprint == candidate.artifact_content_fingerprint
    assert loaded.rows == candidate.rows
    assert fresh.commit(candidate).disposition is OnlyResearchArtifactDisposition.REUSED


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown_manifest",
        "result_identity",
        "statistics_identity",
        "statistics_plan",
        "row_count",
        "byte_hash",
        "data_bytes",
        "unexpected_file",
        "missing_data",
        "manifest_symlink",
        "data_symlink",
    ),
)
def test_published_corruption_is_never_missing_or_rebuilt(tmp_path, mutation: str) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    root = artifact_target(tmp_path, candidate.research_result_fingerprint)
    manifest_path = root / "artifact_manifest.json"
    data_path = root / "statistics.parquet"
    if mutation == "unexpected_file":
        (root / "extra").write_text("x", encoding="utf-8")
    elif mutation == "missing_data":
        data_path.unlink()
    elif mutation == "manifest_symlink":
        original = root / "original-manifest"
        manifest_path.rename(original)
        manifest_path.symlink_to(original.name)
    elif mutation == "data_symlink":
        original = root / "original-data"
        data_path.rename(original)
        data_path.symlink_to(original.name)
    elif mutation == "data_bytes":
        data_path.write_bytes(data_path.read_bytes() + b"corrupt")
    else:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "unknown_manifest":
            payload["unknown"] = True
        elif mutation == "result_identity":
            payload["research_result_fingerprint"] = "e" * 64
        elif mutation == "statistics_identity":
            payload["statistics_results"][0]["statistics_result_fingerprint"] = "e" * 64
        elif mutation == "statistics_plan":
            payload["statistics_results"][0]["plan"]["definition"]["minimum_observations"] += 1
        elif mutation == "row_count":
            payload["statistics_table"]["row_count"] += 1
        else:
            payload["statistics_table"]["data_byte_sha256"] = "e" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(candidate.research_result_fingerprint)
    assert raised.value.code == "ARTIFACT_CORRUPT"
    with pytest.raises(OnlyResearchArtifactStoreError) as recommit:
        store.commit(candidate)
    assert recommit.value.code == "ARTIFACT_CORRUPT"


def test_parseable_semantic_row_corruption_with_new_byte_hash_fails_identity(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    root = artifact_target(tmp_path, candidate.research_result_fingerprint)
    data_path = root / "statistics.parquet"
    manifest_path = root / "artifact_manifest.json"
    table = pq.read_table(data_path)
    values = table.column("sample_count").to_pylist()
    values[0] += 1
    table = table.set_column(3, table.schema.field(3), pa.array(values, type=pa.int64()))
    pq.write_table(table, data_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["statistics_table"]["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(candidate.research_result_fingerprint)
    assert raised.value.code == "ARTIFACT_CORRUPT"
    assert "content identity" in raised.value.detail


def test_noncanonical_rows_and_duplicate_key_fail_closed(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    root = artifact_target(tmp_path, candidate.research_result_fingerprint)
    data_path = root / "statistics.parquet"
    manifest_path = root / "artifact_manifest.json"
    table = pq.read_table(data_path)
    changed = pa.concat_tables((table.slice(1), table.slice(0, 1)))
    pq.write_table(changed, data_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["statistics_table"]["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OnlyResearchArtifactStoreError, match="canonical"):
        store.load_verified(candidate.research_result_fingerprint)


def test_missing_invalid_identity_and_target_symlink_have_stable_codes(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    for identity in ("bad", "f" * 64):
        with pytest.raises(OnlyResearchArtifactStoreError) as raised:
            store.load_verified(identity)
        assert raised.value.code == "ARTIFACT_NOT_FOUND"
    target = artifact_target(tmp_path, candidate.research_result_fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(tmp_path)
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(candidate.research_result_fingerprint)
    assert raised.value.code == "ARTIFACT_CORRUPT"


def test_publication_race_loser_verifies_and_reuses_winner(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    original = os.rename

    def publish_then_report_race(source, target):  # type: ignore[no-untyped-def]
        original(source, target)
        raise OSError("winner already published")

    monkeypatch.setattr(os, "rename", publish_then_report_race)
    outcome = store.commit(candidate)
    assert outcome.disposition is OnlyResearchArtifactDisposition.REUSED


def test_staged_verification_failure_publishes_no_authoritative_target(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, candidate, store = artifact_case(tmp_path)

    def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", "injected")

    monkeypatch.setattr(store, "_read_verified", fail)
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.commit(candidate)
    assert raised.value.code == "ARTIFACT_COMMIT_FAILED"
    assert not artifact_target(tmp_path, candidate.research_result_fingerprint).exists()


def test_deterministic_conflict_is_fail_closed(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    changed = SimpleNamespace(
        research_result_plan_fingerprint=candidate.research_result_plan_fingerprint,
        research_result_content_fingerprint=candidate.research_result_content_fingerprint,
        research_result_fingerprint=candidate.research_result_fingerprint,
        dataset_snapshot_fingerprint=candidate.dataset_snapshot_fingerprint,
        statistics_results=candidate.statistics_results,
        rows=candidate.rows,
        artifact_content_fingerprint="e" * 64,
    )
    table = store.load_verified(candidate.research_result_fingerprint).table
    monkeypatch.setattr(store, "_admit", lambda _candidate: (changed, table))
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.commit(changed)
    assert raised.value.code == "DETERMINISTIC_ARTIFACT_CONFLICT"
