"""Native release artifacts remain bound to frozen inputs and original paths."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import native_workstation_build, release_inputs
from scripts.dev_verification import CUT_METADATA, source_inputs
from scripts.native_workstation_build import verify_artifacts, web_environment
from tests.tools.test_runtime_artifacts import composition as composition


def _artifact(root: Path) -> dict[str, str]:
    payloads = {
        "bin/onlyalpha-backend": b"original executable",
        "web/index.html": b"Shipping UI",
        "contracts/openapi.json": b"{}",
        "contracts/market-data-stream.schema.json": b"{}",
        "algorithm-artifact.sha256": ("b" * 64 + "\n").encode(),
    }
    for name, content in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    files = {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}
    inputs = {
        "pyproject.toml": "a" * 64,
        **{
            "contracts/product-api/v2/" + name: files["contracts/" + name]
            for name in ("openapi.json", "market-data-stream.schema.json")
        },
    }
    web = {"web/index.html": files["web/index.html"]}
    manifest = {
        "schema_version": 2,
        "version": "0.11.0",
        "runtime_root": str(root),
        "source_inputs": inputs,
        "build_environment": {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"},
        "algorithm_artifact": "b" * 64,
        "files": files,
        "default_pair": {
            "policy": "EXACT_BUNDLED_PAIR",
            "api_major": 2,
            "backend_version": "0.11.0",
            "frontend_version": "0.10.7",
            "backend_sha256": files["bin/onlyalpha-backend"],
            "frontend_sha256": hashlib.sha256(release_inputs.encode(web)).hexdigest(),
            "openapi_sha256": files["contracts/openapi.json"],
            "stream_sha256": files["contracts/market-data-stream.schema.json"],
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return inputs


def test_native_artifact_keeps_original_frozen_source_and_absolute_installation(tmp_path: Path) -> None:
    inputs = _artifact(tmp_path)
    assert verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")["runtime_root"] == str(tmp_path)
    for wrong_inputs, version in (({"pyproject.toml": "c" * 64}, "0.11.0"), (inputs, "0.10.21")):
        with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
            verify_artifacts(tmp_path, wrong_inputs, version, frontend_version="0.10.7")
    (tmp_path / "bin/onlyalpha-backend").write_bytes(b"replaced executable")
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")


@pytest.mark.parametrize("name", ("../outside", "/absolute", "bin/../manifest.json"))
def test_native_artifact_rejects_paths_outside_its_original_resource_root(tmp_path: Path, name: str) -> None:
    inputs = _artifact(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"] = {name: "d" * 64}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")


def test_native_artifact_rejects_symlink_substitution_and_unrecorded_payload(tmp_path: Path) -> None:
    inputs = _artifact(tmp_path)
    original = tmp_path / "bin/onlyalpha-backend"
    original.rename(tmp_path / "original")
    original.symlink_to(tmp_path / "original")
    with pytest.raises(ValueError, match="NATIVE_ARTIFACT"):
        verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")


def test_shipping_assets_build_with_explicit_cookie_session_inputs() -> None:
    environment = web_environment(
        {"PATH": "/tools", "VITE_ONLYALPHA_LOCAL_SESSION": "false", "VITE_TOKEN": "unbound", "NODE_ENV": "development"}
    )
    assert environment == {"PATH": "/tools", "VITE_ONLYALPHA_LOCAL_SESSION": "true", "NODE_ENV": "production"}


def test_default_native_build_does_not_install_or_start_agent(composition, monkeypatch, tmp_path: Path) -> None:
    from scripts import build_agent_service
    from scripts.embed_build_provenance import build_provenance_bytes, write_build_provenance

    root, original = composition
    (root / "pyproject.toml").write_text('[project]\nversion = "0.12.0"\n')
    schema = root / "database/postgres/migrations"
    schema.mkdir(parents=True)
    (schema / "0001_schema.sql").write_text("SELECT 1;\n")
    write_build_provenance(root, root / "src/onlyalpha/_build_provenance.json", build_provenance_bytes(root, "1" * 40))
    inputs = source_inputs(root)
    (root / CUT_METADATA).write_text(json.dumps({"operation_id": "test", "inputs": inputs}))
    monkeypatch.setattr(native_workstation_build, "ROOT", root)
    monkeypatch.setenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "test")
    monkeypatch.setattr(native_workstation_build, "native_executable", lambda: original / "bin/onlyalpha-backend")

    def install_algorithms(wheels: Path, destination: Path) -> str:
        destination.mkdir()
        (destination / "algorithm-installation.json").write_text("{}")
        return "b" * 64

    def forbidden_agent_install(*args, **kwargs):
        raise AssertionError("ordinary workstation build requires the paused Agent")

    actual_run = subprocess.run

    def run(command, **kwargs):
        if command[:3] == ["npm", "run", "build"]:
            assert kwargs["cwd"] == root / "packages/frontend"
            destination = Path(command[command.index("--outDir") + 1])
            destination.mkdir()
            (destination / "index.html").write_text("<html>Shipping UI</html>")
            return subprocess.CompletedProcess(command, 0)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(native_workstation_build, "install", install_algorithms)
    monkeypatch.setattr(build_agent_service, "install", forbidden_agent_install)
    monkeypatch.setattr(native_workstation_build.subprocess, "run", run)
    destination = tmp_path / "workstation"
    manifest = native_workstation_build.build(destination)
    assert "agent" not in manifest
    assert not (destination / "agent").exists()
    assert (destination / "bin/onlyalpha-backend").read_bytes() == (original / "bin/onlyalpha-backend").read_bytes()
    assert manifest["default_pair"]["backend_version"] == "0.12.0"
    assert manifest["default_pair"]["frontend_version"] == "0.13.0"
    assert verify_artifacts(destination, inputs, "0.12.0", frontend_version="0.13.0") == manifest


def test_native_build_checks_selected_inputs_before_creating_any_artifact(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "Cargo.lock").write_text("locked")
    (root / CUT_METADATA).write_text(json.dumps({"operation_id": "test", "inputs": source_inputs(root)}))
    monkeypatch.setattr(native_workstation_build, "ROOT", root)
    monkeypatch.setenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "test")
    destination = tmp_path / "artifact"
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        native_workstation_build.build(
            destination, release_input_path=tmp_path / "missing.json", release_input_sha256="a" * 64
        )
    assert not destination.exists()


def test_native_build_requires_dependency_artifacts_for_a_release_selection(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / CUT_METADATA).write_text(json.dumps({"operation_id": "test", "inputs": {}}))
    monkeypatch.setattr(native_workstation_build, "ROOT", root)
    monkeypatch.setenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "test")
    # A standalone preliminary receipt cannot masquerade as a dependency-locked build.
    monkeypatch.setattr(release_inputs, "verify", lambda *args, **kwargs: {"sha256": "a" * 64})
    destination = tmp_path / "artifact"
    with pytest.raises(ValueError, match="RELEASE_INPUT_SOURCE_SELECTION_REQUIRED"):
        native_workstation_build.build(
            destination, release_input_path=tmp_path / "inputs.json", release_input_sha256="a" * 64
        )
    assert not destination.exists()


def test_native_artifact_retains_and_checks_selected_release_receipt(tmp_path: Path) -> None:
    inputs = _artifact(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    selected = {
        "schema_version": 1,
        "source_inputs": inputs,
        "versions": {"backend": "0.11.0", "libs": "0.10.0", "frontend": "0.10.7"},
        "build": {"profile": "release"},
    }
    manifest["release_inputs"] = {
        "sha256": hashlib.sha256(release_inputs.encode(selected)).hexdigest(),
        "versions": selected["versions"],
        "build": selected["build"],
    }
    path.write_text(json.dumps(manifest))
    assert (
        verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")["release_inputs"]["versions"]["libs"]
        == "0.10.0"
    )
    manifest["release_inputs"]["versions"]["libs"] = "0.10.1"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        verify_artifacts(tmp_path, inputs, "0.11.0", frontend_version="0.10.7")
