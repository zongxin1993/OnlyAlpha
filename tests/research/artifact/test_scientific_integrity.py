from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from hashlib import sha256

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import OnlyResearchArtifactDisposition, OnlyResearchArtifactStoreError
from onlyalpha.research.artifact.scientific_model import (
    OnlyResearchScientificSection,
    only_research_scientific_artifact_content_fingerprint,
    only_research_scientific_section_fingerprint,
)
from tests.research.artifact.support import scientific_artifact_case, scientific_artifact_target


def test_scientific_manifest_requires_exact_result_schema_version(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    manifest = store.load_verified(candidate.result.manifest.research_result_fingerprint).manifest

    with pytest.raises(ValueError, match="Research Result schema"):
        replace(manifest, research_result_schema_version=1)


def test_scientific_store_rejects_non_sha_path_identity_before_lookup(tmp_path) -> None:
    _, _, store = scientific_artifact_case(tmp_path)
    for identity in ("A" * 64, "z" * 64, " " * 64, "a" * 63):
        with pytest.raises(OnlyResearchArtifactStoreError) as raised:
            store._target(identity)
        assert raised.value.code == "ARTIFACT_NOT_FOUND"


def test_scientific_publication_race_loser_verifies_and_reuses_winner(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, candidate, store = scientific_artifact_case(tmp_path)
    original = os.rename

    def publish_then_report_race(source, target):  # type: ignore[no-untyped-def]
        original(source, target)
        raise OSError("winner already published")

    monkeypatch.setattr("onlyalpha.research.artifact.scientific_store.os.rename", publish_then_report_race)
    outcome = store.commit(candidate)
    assert outcome.disposition is OnlyResearchArtifactDisposition.REUSED


def test_scientific_store_detects_duplicate_keys_axis_and_scalar_corruption(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    store.commit(candidate)
    root = scientific_artifact_target(tmp_path, candidate.result.manifest.research_result_fingerprint)
    originals = {item.name: item.read_bytes() for item in root.iterdir()}

    mutations = (
        ("market.parquet", lambda table: pa.concat_tables((table, table.slice(0, 1)))),
        ("variables.parquet", lambda table: pa.concat_tables((table, table.slice(0, 1)))),
        ("signals.parquet", lambda table: pa.concat_tables((table, table.slice(0, 1)))),
        ("variables.parquet", lambda table: table.slice(1)),
        ("signals.parquet", _append_signal_timestamp),
        ("variables.parquet", _noncanonical_integer),
        ("variables.parquet", _noncanonical_decimal),
    )
    for path, mutation in mutations:
        for name, content in originals.items():
            (root / name).write_bytes(content)
        _rewrite_semantically_consistent(root, path, mutation(pq.read_table(root / path)))
        with pytest.raises(OnlyResearchArtifactStoreError) as raised:
            store.load_verified(candidate.result.manifest.research_result_fingerprint)
        assert raised.value.code == "ARTIFACT_CORRUPT"


def test_scientific_store_file_manifest_and_conflict_matrix(tmp_path) -> None:
    _, candidate, store = scientific_artifact_case(tmp_path)
    first = store.commit(candidate)
    assert first.disposition is OnlyResearchArtifactDisposition.EXECUTED
    assert store.commit(candidate).disposition is OnlyResearchArtifactDisposition.REUSED
    with pytest.raises(OnlyResearchArtifactStoreError) as conflict:
        store.commit(replace(candidate, artifact_content_fingerprint="e" * 64))
    assert conflict.value.code == "DETERMINISTIC_ARTIFACT_CONFLICT"

    identity = candidate.result.manifest.research_result_fingerprint
    root = scientific_artifact_target(tmp_path, identity)
    originals = {item.name: item.read_bytes() for item in root.iterdir()}
    manifest_path = root / "artifact_manifest.json"
    cases = ("unexpected", "missing", "section_symlink", "byte", "statistics_logical", "statistics_result", "version")
    for case in cases:
        for item in tuple(root.iterdir()):
            if item.is_symlink() or item.is_file():
                item.unlink()
            else:
                shutil.rmtree(item)
        for name, content in originals.items():
            (root / name).write_bytes(content)
        if case == "unexpected":
            (root / "unexpected").write_text("x", encoding="utf-8")
        elif case == "missing":
            (root / "signals.parquet").unlink()
        elif case == "section_symlink":
            path = root / "signals.parquet"
            outside = root.parent / "signals-copy.parquet"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
        elif case == "byte":
            path = root / "market.parquet"
            path.write_bytes(path.read_bytes() + b"corrupt")
        else:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if case == "statistics_logical":
                payload["statistics_catalog"][0]["result_content_fingerprint"] = "e" * 64
            elif case == "statistics_result":
                payload["statistics_catalog"][0]["statistics_result_fingerprint"] = "e" * 64
            else:
                payload["research_result_schema_version"] = 1
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(OnlyResearchArtifactStoreError) as raised:
            store.load_verified(identity)
        assert raised.value.code == "ARTIFACT_CORRUPT"

    for item in tuple(root.iterdir()):
        if item.is_symlink() or item.is_file():
            item.unlink()
    for name, content in originals.items():
        (root / name).write_bytes(content)
    moved = root.with_name(f"{root.name}-real")
    root.rename(moved)
    root.symlink_to(moved)
    try:
        with pytest.raises(OnlyResearchArtifactStoreError) as raised:
            store.load_verified(identity)
        assert raised.value.code == "ARTIFACT_CORRUPT"
    finally:
        root.unlink()
        moved.rename(root)


def test_scientific_semantic_identity_ignores_physical_encoding(tmp_path) -> None:
    _, candidate, _ = scientific_artifact_case(tmp_path)
    zstd = __import__(
        "onlyalpha.research.artifact.scientific_store",
        fromlist=["OnlyParquetResearchScientificArtifactStore"],
    ).OnlyParquetResearchScientificArtifactStore(
        tmp_path / "zstd", compression="zstd", audit_time=lambda: candidate.result.manifest.created_at
    )
    gzip = type(zstd)(
        tmp_path / "gzip", compression="gzip", row_group_size=1, audit_time=lambda: candidate.result.manifest.created_at
    )
    assert zstd.commit(candidate).artifact_content_fingerprint == gzip.commit(candidate).artifact_content_fingerprint


def _append_signal_timestamp(table: pa.Table) -> pa.Table:
    row = table.slice(0, 1).to_pylist()[0]
    row["ts_event_ns"] = max(table.column("ts_event_ns").to_pylist()) + 1
    return pa.concat_tables((table, pa.Table.from_pylist([row], schema=table.schema)))


def _noncanonical_integer(table: pa.Table) -> pa.Table:
    rows = table.to_pylist()
    index = next(index for index, row in enumerate(rows) if row["value_kind"] == "DECIMAL")
    rows[index]["value_kind"] = "INTEGER"
    rows[index]["decimal_value"] = None
    rows[index]["integer_value"] = "01"
    return pa.Table.from_pylist(rows, schema=table.schema)


def _noncanonical_decimal(table: pa.Table) -> pa.Table:
    rows = table.to_pylist()
    index = next(index for index, row in enumerate(rows) if row["value_kind"] == "DECIMAL")
    rows[index]["decimal_value"] = "NaN"
    return pa.Table.from_pylist(rows, schema=table.schema)


def _rewrite_semantically_consistent(root, path: str, table: pa.Table) -> None:  # type: ignore[no-untyped-def]
    data_path = root / path
    pq.write_table(table, data_path)
    manifest_path = root / "artifact_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    section = next(item for item in payload["sections"] if item["relative_path"] == path)
    rows = table.to_pylist()
    if path == "statistics.parquet":
        for row in rows:
            row["status"] = row["status"]
    section["row_count"] = len(rows)
    section["logical_fingerprint"] = only_research_scientific_section_fingerprint(path.split(".", 1)[0], rows)
    section["byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    sections = tuple(OnlyResearchScientificSection.from_dict(item) for item in payload["sections"])
    payload["artifact_content_fingerprint"] = only_research_scientific_artifact_content_fingerprint(
        payload["research_result_fingerprint"], sections
    )
    manifest_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
