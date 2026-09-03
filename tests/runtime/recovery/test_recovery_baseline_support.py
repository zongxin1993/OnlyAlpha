import json
import sqlite3
from pathlib import Path

import pytest

import tests.support.recovery_baselines as recovery_baselines
from tests.support.recovery_baselines import (
    assert_recovery_baseline_compatible,
    load_recovery_baseline,
)
from tests.support.sqlite_templates import copy_sqlite_template, validate_sqlite_template


def test_all_formal_recovery_baselines_are_immutable_and_content_addressed() -> None:
    for baseline_id in (
        "long_close_whole_baseline",
        "long_close_multi_fill_baseline",
        "multi_cluster_close_baseline",
        "terminal_after_partial_fill_baseline",
    ):
        baseline = load_recovery_baseline(baseline_id)
        assert baseline.baseline_id == baseline_id
        assert baseline.manifest["baseline_schema_version"] == 2
        assert baseline.strategy_fingerprints == tuple(sorted(set(baseline.strategy_fingerprints)))
        assert baseline.result_fingerprint
        assert str(baseline.manifest["database_fingerprint"]) in baseline.database_template.name


def test_sqlite_template_copy_is_private_and_writable(tmp_path: Path) -> None:
    baseline = load_recovery_baseline("long_close_whole_baseline")
    expected = str(baseline.manifest["database_fingerprint"])
    validate_sqlite_template(baseline.database_template, expected)
    first = copy_sqlite_template(baseline.database_template, tmp_path / "first" / "runtime.sqlite3", expected)
    second = copy_sqlite_template(baseline.database_template, tmp_path / "second" / "runtime.sqlite3", expected)

    connection = sqlite3.connect(first)
    try:
        connection.execute("CREATE TABLE test_private_write(value TEXT)")
    finally:
        connection.close()
    validate_sqlite_template(second, expected)
    validate_sqlite_template(baseline.database_template, expected)


def test_matching_strategy_identity_passes_and_mismatch_fails_before_engine_execution() -> None:
    baseline = load_recovery_baseline("long_close_whole_baseline")
    assert_recovery_baseline_compatible(baseline, list(baseline.strategy_fingerprints))
    with pytest.raises(AssertionError, match="RECOVERY_BASELINE_STRATEGY_IDENTITY_MISMATCH"):
        assert_recovery_baseline_compatible(baseline, ["f" * 64])


@pytest.mark.parametrize(
    ("metadata", "message"),
    (
        ({"baseline_schema_version": 1}, "unsupported Recovery baseline schema"),
        ({"baseline_schema_version": 2}, "strategy_fingerprints must be a non-empty list"),
        (
            {"baseline_schema_version": 2, "strategy_fingerprints": ["not-a-fingerprint"]},
            "malformed Strategy fingerprint",
        ),
        (
            {"baseline_schema_version": 2, "strategy_fingerprints": ["f" * 64, "f" * 64]},
            "contain duplicates",
        ),
        (
            {"baseline_schema_version": 2, "strategy_fingerprints": ["f" * 64, "e" * 64]},
            "not canonically ordered",
        ),
    ),
)
def test_loader_rejects_stale_or_malformed_strategy_metadata(tmp_path, monkeypatch, metadata, message) -> None:  # type: ignore[no-untyped-def]
    baseline_id = "invalid_baseline"
    directory = tmp_path / baseline_id
    directory.mkdir()
    manifest = {"baseline_id": baseline_id, **metadata}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(recovery_baselines, "RECOVERY_FIXTURE_ROOT", tmp_path)
    with pytest.raises(ValueError, match=message):
        load_recovery_baseline(baseline_id)
