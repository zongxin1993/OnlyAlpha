from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.research import (
    OnlyResearchArtifactManifest,
    OnlyResearchArtifactStatisticsEntry,
    OnlyResearchArtifactStatisticsTable,
)
from tests.research.artifact.support import artifact_case


def _manifest(tmp_path):  # type: ignore[no-untyped-def]
    _, _, _, _, candidate, store = artifact_case(tmp_path)
    store.commit(candidate)
    return store.load_verified(candidate.research_result_fingerprint).manifest


def test_manifest_is_strict_round_trip_and_audit_time_is_semantically_neutral(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    restored = OnlyResearchArtifactManifest.from_dict(manifest.to_dict())
    changed = replace(restored, created_at=datetime(2035, 1, 1, tzinfo=UTC))

    assert restored == manifest
    assert changed.artifact_content_fingerprint == manifest.artifact_content_fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("unknown", True),
        ("schema_version", 2),
        ("profile", "OTHER"),
        ("research_result_schema_version", 2),
        ("research_result_fingerprint", "bad"),
        ("created_at", "2026-08-16T00:00:00"),
        ("statistics_results", []),
    ),
)
def test_manifest_reader_rejects_unknown_malformed_and_unsupported_fields(tmp_path, field: str, value: object) -> None:
    payload = _manifest(tmp_path).to_dict()
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        OnlyResearchArtifactManifest.from_dict(payload)


def test_catalog_rejects_noncanonical_duplicate_and_plan_linkage(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    first, second = manifest.statistics_results
    with pytest.raises(ValueError, match="canonical"):
        replace(manifest, statistics_results=(second, first))
    with pytest.raises(ValueError, match="duplicates"):
        replace(manifest, statistics_results=(first, first))
    with pytest.raises(ValueError, match="Plan linkage"):
        replace(first, statistics_fingerprint=second.statistics_fingerprint)


def test_catalog_and_table_parsers_are_exact(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    entry_payload = manifest.statistics_results[0].to_dict()
    table_payload = manifest.statistics_table.to_dict()
    entry_payload["unknown"] = True
    table_payload["relative_path"] = "other.parquet"
    with pytest.raises(ValueError):
        OnlyResearchArtifactStatisticsEntry.from_dict(entry_payload)
    with pytest.raises(ValueError):
        OnlyResearchArtifactStatisticsTable.from_dict(table_payload)
