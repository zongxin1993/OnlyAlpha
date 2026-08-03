import sqlite3
from pathlib import Path

from tests.support.recovery_baselines import load_recovery_baseline
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
