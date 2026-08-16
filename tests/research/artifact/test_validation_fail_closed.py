from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import (
    OnlyResearchArtifactCandidate,
    OnlyResearchArtifactDisposition,
    OnlyResearchArtifactManifest,
    OnlyResearchArtifactOutcome,
    OnlyResearchArtifactStatisticsEntry,
    OnlyResearchArtifactStoreError,
)
from onlyalpha.research.artifact.materializer import OnlyResearchArtifactMaterializer
from onlyalpha.research.artifact.store import _rows, _schema_payload, _verify_groups
from tests.research.artifact.support import artifact_case, artifact_target


def test_candidate_rejects_invalid_identity_catalog_and_research_linkage(tmp_path) -> None:
    _, _, _, _, candidate, _ = artifact_case(tmp_path)
    changes = (
        {"dataset_snapshot_fingerprint": "bad"},
        {"statistics_results": cast(tuple[OnlyResearchArtifactStatisticsEntry, ...], [])},
        {"research_result_plan_fingerprint": "e" * 64},
        {"research_result_content_fingerprint": "e" * 64},
        {"research_result_fingerprint": "e" * 64},
    )
    for change in changes:
        with pytest.raises(ValueError):
            replace(candidate, **change)


def test_entry_table_manifest_and_outcome_direct_validation(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    manifest = store.load_verified(candidate.research_result_fingerprint).manifest
    entry = manifest.statistics_results[0]
    table = manifest.statistics_table
    invalid_entries = (
        {"statistics_result_schema_version": 2},
        {"plan": cast(object, None)},
        {"statistics_result_fingerprint": "e" * 64},
        {"row_count": -1},
    )
    for change in invalid_entries:
        with pytest.raises(ValueError):
            replace(entry, **change)
    for change in (
        {"row_count": -1},
        {"arrow_schema": ()},
        {"data_byte_sha256": "bad"},
    ):
        with pytest.raises(ValueError):
            replace(table, **change)
    invalid_manifests = (
        {"research_result_plan_fingerprint": "e" * 64},
        {"research_result_content_fingerprint": "e" * 64},
        {"research_result_fingerprint": "e" * 64},
        {"statistics_table": cast(object, None)},
        {"artifact_content_fingerprint": "e" * 64},
        {"created_at": datetime(2026, 1, 1)},
    )
    for change in invalid_manifests:
        with pytest.raises(ValueError):
            replace(manifest, **change)
    with pytest.raises(ValueError):
        OnlyResearchArtifactOutcome(cast(OnlyResearchArtifactDisposition, "EXECUTED"), "a" * 64, "b" * 64)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("statistics_results",), {}),
        (("statistics_results", 0), []),
        (("statistics_table",), []),
        (("profile",), 1),
        (("schema_version",), True),
        (("created_at",), "not-a-time"),
    ),
)
def test_manifest_nested_parser_types_fail_closed(tmp_path, path: tuple[object, ...], value: object) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    payload = store.load_verified(candidate.research_result_fingerprint).manifest.to_dict()
    if len(path) == 1:
        payload[cast(str, path[0])] = value
    else:
        cast(list[object], payload[cast(str, path[0])])[cast(int, path[1])] = value
    with pytest.raises((TypeError, ValueError)):
        OnlyResearchArtifactManifest.from_dict(payload)


def test_materializer_rejects_result_path_projection_and_all_statistics_tampering(tmp_path) -> None:
    plan, research_result, statistics_store, _, _, _ = artifact_case(tmp_path)
    reference = research_result.manifest.statistics_results[0]
    statistics = statistics_store.load_verified(reference.statistics_fingerprint)

    class ResultStore:
        def load_verified(self, _identity):  # type: ignore[no-untyped-def]
            return replace(
                research_result,
                manifest=SimpleNamespace(
                    **{
                        **research_result.manifest.to_dict(),
                        "research_result_plan_fingerprint": "e" * 64,
                        "statistics_results": (),
                    }
                ),
            )

    with pytest.raises(Exception, match="Plan identity mismatch"):
        OnlyResearchArtifactMaterializer(ResultStore(), statistics_store).materialize(plan.fingerprint)

    base = statistics.manifest
    mutations = (
        SimpleNamespace(**{**base.__dict__}) if hasattr(base, "__dict__") else None,
        SimpleNamespace(
            plan=base.plan,
            statistics_fingerprint="e" * 64,
            result_content_fingerprint=base.result_content_fingerprint,
            statistics_result_fingerprint=base.statistics_result_fingerprint,
            row_count=base.row_count,
        ),
        SimpleNamespace(
            plan=base.plan,
            statistics_fingerprint=base.statistics_fingerprint,
            result_content_fingerprint="e" * 64,
            statistics_result_fingerprint=base.statistics_result_fingerprint,
            row_count=base.row_count,
        ),
        SimpleNamespace(
            plan=base.plan,
            statistics_fingerprint=base.statistics_fingerprint,
            result_content_fingerprint=base.result_content_fingerprint,
            statistics_result_fingerprint="e" * 64,
            row_count=base.row_count,
        ),
        SimpleNamespace(
            plan=base.plan,
            statistics_fingerprint=base.statistics_fingerprint,
            result_content_fingerprint=base.result_content_fingerprint,
            statistics_result_fingerprint=base.statistics_result_fingerprint,
            row_count=base.row_count + 1,
        ),
    )[1:]
    for mutation in mutations:
        with pytest.raises(ValueError):
            OnlyResearchArtifactMaterializer._verify_statistics(
                reference.statistics_result_fingerprint,
                replace(statistics, manifest=mutation),
            )
    with pytest.raises(ValueError, match="row contract"):
        OnlyResearchArtifactMaterializer._verify_statistics(
            reference.statistics_result_fingerprint,
            replace(statistics, rows=cast(tuple, (object(),))),
        )


def test_store_rejects_invalid_candidate_audit_time_and_atomic_failure(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    assert not store.exists(candidate.research_result_fingerprint)
    with pytest.raises(OnlyResearchArtifactStoreError, match="candidate contract"):
        store.commit(cast(OnlyResearchArtifactCandidate, object()))
    no_time = type(store)(tmp_path / "no-time")
    with pytest.raises(OnlyResearchArtifactStoreError, match="audit time authority"):
        no_time.commit(candidate)
    naive = type(store)(tmp_path / "naive", audit_time=lambda: datetime(2026, 1, 1))
    with pytest.raises(OnlyResearchArtifactStoreError, match="timezone-aware"):
        naive.commit(candidate)

    monkeypatch.setattr("onlyalpha.research.artifact.store.os.rename", lambda *_args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.commit(candidate)
    assert raised.value.code == "ARTIFACT_COMMIT_FAILED"


def test_store_reader_rejects_non_object_non_file_wrong_path_schema_and_count(tmp_path) -> None:
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    root = artifact_target(tmp_path, candidate.research_result_fingerprint)
    manifest_path = root / "artifact_manifest.json"
    data_path = root / "statistics.parquet"
    original_manifest = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text("[]", encoding="utf-8")
    with pytest.raises(OnlyResearchArtifactStoreError, match="object"):
        store.load_verified(candidate.research_result_fingerprint)
    manifest_path.write_text(original_manifest, encoding="utf-8")

    with pytest.raises(OnlyResearchArtifactStoreError, match="path identity"):
        store._read_verified(root, "e" * 64)

    original_data = data_path.read_bytes()
    data_path.unlink()
    data_path.mkdir()
    with pytest.raises(OnlyResearchArtifactStoreError, match="non-file"):
        store.load_verified(candidate.research_result_fingerprint)
    data_path.rmdir()
    data_path.write_bytes(original_data)

    table = pq.read_table(data_path)
    pq.write_table(table.remove_column(4), data_path)
    payload = json.loads(original_manifest)
    from hashlib import sha256

    payload["statistics_table"]["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OnlyResearchArtifactStoreError, match="schema"):
        store.load_verified(candidate.research_result_fingerprint)

    pq.write_table(table.slice(1), data_path)
    payload["statistics_table"]["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OnlyResearchArtifactStoreError, match="row count"):
        store.load_verified(candidate.research_result_fingerprint)


def test_private_logical_helpers_reject_invalid_rows_groups_and_schema(tmp_path) -> None:
    _, _, _, _, candidate, _ = artifact_case(tmp_path)
    valid_row = candidate.rows[0]
    bad_table = pa.table(
        {
            "statistics_fingerprint": [valid_row.statistics_fingerprint],
            "ts_event_ns": [valid_row.ts_event_ns],
            "statistic_value": [valid_row.statistic_value],
            "sample_count": [valid_row.sample_count],
            "status": ["BAD"],
        }
    )
    with pytest.raises(ValueError, match="logical row"):
        _rows(bad_table)
    with pytest.raises(ValueError, match="catalog is invalid"):
        _verify_groups((object(),), candidate.rows)
    outside = replace(valid_row, statistics_fingerprint="e" * 64)
    with pytest.raises(ValueError, match="outside"):
        _verify_groups(candidate.statistics_results, (outside,))
    with pytest.raises(ValueError, match="group row count"):
        _verify_groups(candidate.statistics_results, candidate.rows[1:])
    with pytest.raises(ValueError, match="unsupported"):
        _schema_payload(pa.schema((pa.field("x", pa.bool_()),)))
