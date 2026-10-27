"""Runtime preflight rejects invalid selection before constructing artifacts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import runtime_build
from scripts.dev_verification import freeze_source
from scripts.release_inputs import candidate, encode
from tests.tools.test_release_sources import selections
from tests.tools.test_release_sources import source_repo as source_repo


def test_partial_or_invalid_runtime_selection_never_creates_a_receipt(tmp_path):
    output = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        runtime_build.preflight(tmp_path, output, selection_dir=None, digest="a" * 64)
    assert not output.exists()
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        runtime_build.preflight(tmp_path, output, selection_dir=tmp_path / "missing", digest="")
    assert not output.exists()


def test_runtime_sealing_refuses_changed_source_before_writing_manifest(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"source_inputs": {"file": "a" * 64}, "release_inputs": None}))
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    with pytest.raises(ValueError, match="RUNTIME_BUILD_SOURCE_CHANGED"):
        runtime_build.finish(tmp_path, artifact, receipt, selection_dir=None, digest="")
    assert not (artifact / "manifest.json").exists()


@pytest.mark.parametrize("build_fails", [False, True])
def test_runtime_image_uses_only_fixed_tag_and_preserves_unknown_build_fence(
    source_repo, tmp_path, monkeypatch, build_fails
):
    root, revision = source_repo
    refs = selections(root, revision, tmp_path)
    selected = tmp_path / "inputs.json"
    selected.write_bytes(encode(candidate(root, source_bundles=refs)))
    import hashlib

    digest = hashlib.sha256(selected.read_bytes()).hexdigest()
    freeze_source(root, "image")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "build"] and build_fails:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="[]", returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda command, **kwargs: json.dumps([{"Id": "sha256:" + "a" * 64}]) if "inspect" in command else "",
    )
    reservation = {"operation_id": "image", "completed": True}
    command = ["--release-inputs", str(selected), "--release-inputs-sha256", digest, "--source-bundles", str(refs)]
    if build_fails:
        with pytest.raises(subprocess.CalledProcessError):
            runtime_build.build_image(root, command, reservation)
        assert reservation["completed"] is False
    else:
        assert runtime_build.build_image(root, command, reservation) == 0
        assert reservation["completed"] is True
    build = next(row for row in calls if row[:2] == ["docker", "build"])
    assert build[build.index("--tag") + 1] == "onlyalpha-runtime:dev"
    assert Path(build[-1]) == root / ".test-cache/dev-source-cut"
    assert not any("up" in row or "run" in row or "down" in row for row in calls)
