"""Selected build inputs are checked before constructing a release artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import release_inputs


def _tree(root: Path) -> None:
    files = {
        "Cargo.toml": '[workspace]\nmembers=["packages/backend"]\n[workspace.package]\nversion="0.11.1"\n',
        "packages/backend/Cargo.toml": '[package]\nname="onlyalpha-backend"\nversion="0.12.0"\n',
        "packages/frontend/package.json": '{"version":"0.13.0"}',
        "pyproject.toml": "[tool.uv.workspace]\nmembers=[]\n",
        "Cargo.lock": "exact cargo lock",
        "uv.lock": "exact python lock",
        "packages/frontend/package-lock.json": "exact npm lock",
        "rust-toolchain.toml": '[toolchain]\nchannel="1.99.1"\n',
        "crates/example/rust/lib.rs": "pub fn value() {}",
        ".cargo/config.toml": "[build]\nrustflags=[]\n",
    }
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)


def _selected(root: Path, tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "selection.json"
    path.write_bytes(release_inputs.encode(release_inputs.candidate(root)))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_selection_binds_independent_versions_and_build_inputs(tmp_path: Path) -> None:
    root = tmp_path / "source"
    _tree(root)
    path, digest = _selected(root, tmp_path)
    receipt = release_inputs.verify(root, path, digest)
    assert receipt["sha256"] == digest
    assert receipt["versions"] == {"libs": "0.11.1", "backend": "0.12.0", "frontend": "0.13.0"}
    assert receipt["build"]["profile"] == "release"


@pytest.mark.parametrize("name", ["crates/example/rust/lib.rs", "Cargo.lock", "uv.lock", ".cargo/config.toml"])
@pytest.mark.parametrize("mutation", ["change", "remove"])
def test_same_versions_do_not_authorize_changed_or_missing_source(tmp_path: Path, name: str, mutation: str) -> None:
    root = tmp_path / "source"
    _tree(root)
    path, digest = _selected(root, tmp_path)
    source = root / name
    if mutation == "change":
        source.write_text("different bytes")
    else:
        source.unlink()
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        release_inputs.verify(root, path, digest)


@pytest.mark.parametrize(
    "mutation",
    [
        "tamper",
        "missing",
        "target",
        "feature",
        "version",
        "extra",
        "boolean-schema",
        "float-schema",
        "numeric-features",
    ],
)
def test_release_selection_rejects_unselected_or_unsupported_inputs(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "source"
    _tree(root)
    path, digest = _selected(root, tmp_path)
    selection = json.loads(path.read_text())
    if mutation == "missing":
        path.unlink()
    elif mutation == "tamper":
        path.write_text("{}")
    else:
        if mutation == "target":
            selection["build"]["target"] = "unsupported-target"
        elif mutation == "feature":
            selection["build"]["features"] = ["unselected-feature"]
        elif mutation == "version":
            selection["versions"]["frontend"] = "0.13.1"
        elif mutation == "boolean-schema":
            selection["schema_version"] = True
        elif mutation == "float-schema":
            selection["schema_version"] = 1.0
        elif mutation == "numeric-features":
            selection["build"]["default_features"] = 1
        else:
            selection["ignored"] = True
        path.write_bytes(release_inputs.encode(selection))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="RELEASE_INPUT"):
        release_inputs.verify(root, path, digest)
