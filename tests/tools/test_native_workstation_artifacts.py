"""Native release artifacts remain bound to frozen inputs and original paths."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.native_workstation_build import verify_artifacts, web_environment


def _artifact(root: Path) -> dict[str, str]:
    (root / "bin").mkdir()
    (root / "bin/onlyalpha-http-server").write_bytes(b"original executable")
    inputs = {"pyproject.toml": "a" * 64}
    manifest = {
        "schema_version": 1,
        "version": "0.11.0",
        "runtime_root": str(root),
        "source_inputs": inputs,
        "build_environment": {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"},
        "algorithm_artifact": "b" * 64,
        "files": {"bin/onlyalpha-http-server": hashlib.sha256(b"original executable").hexdigest()},
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return inputs


def test_native_artifact_keeps_original_frozen_source_and_absolute_installation(tmp_path: Path) -> None:
    inputs = _artifact(tmp_path)
    assert verify_artifacts(tmp_path, inputs, "0.11.0")["runtime_root"] == str(tmp_path)
    for wrong_inputs, version in (({"pyproject.toml": "c" * 64}, "0.11.0"), (inputs, "0.10.21")):
        with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
            verify_artifacts(tmp_path, wrong_inputs, version)
    (tmp_path / "bin/onlyalpha-http-server").write_bytes(b"replaced executable")
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0")


@pytest.mark.parametrize("name", ("../outside", "/absolute", "bin/../manifest.json"))
def test_native_artifact_rejects_paths_outside_its_original_resource_root(tmp_path: Path, name: str) -> None:
    inputs = _artifact(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"] = {name: "d" * 64}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0")


def test_native_artifact_rejects_symlink_substitution_and_unrecorded_payload(tmp_path: Path) -> None:
    inputs = _artifact(tmp_path)
    original = tmp_path / "bin/onlyalpha-http-server"
    original.rename(tmp_path / "original")
    original.symlink_to(tmp_path / "original")
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0")


def test_shipping_assets_build_with_explicit_cookie_session_inputs() -> None:
    environment = web_environment(
        {"PATH": "/tools", "VITE_ONLYALPHA_LOCAL_SESSION": "false", "VITE_TOKEN": "unbound", "NODE_ENV": "development"}
    )
    assert environment == {"PATH": "/tools", "VITE_ONLYALPHA_LOCAL_SESSION": "true", "NODE_ENV": "production"}
