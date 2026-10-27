"""Browser acceptance consumes an explicitly selected artifact without rebuilding."""

from __future__ import annotations

import sys

import pytest

from scripts import native_web_e2e


def test_invalid_selected_artifact_is_rejected_before_database_access(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "manifest.json").write_text("{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "native_web_e2e.py",
            "--artifact",
            str(artifact),
            "--artifact-sha256",
            "0" * 64,
            "e2e/product-package-migration.spec.ts",
        ],
    )
    monkeypatch.setattr(
        native_web_e2e.psycopg,
        "connect",
        lambda *args, **kwargs: pytest.fail("database accessed before artifact admission"),
    )
    monkeypatch.setattr(native_web_e2e, "build", lambda *args, **kwargs: pytest.fail("selected artifact rebuilt"))
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT_SELECTION_MISMATCH"):
        native_web_e2e.main()


def test_selected_manifest_hash_is_checked_before_parsing_or_source_queries(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("not JSON")
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT_SELECTION_MISMATCH"):
        native_web_e2e.selected_artifact(tmp_path, tmp_path, "0" * 64)
