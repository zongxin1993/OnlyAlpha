"""Exact unit source artifacts never substitute mutable workspace contents."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import release_inputs, release_sources


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def source_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "Cargo.toml": '[workspace]\nmembers=["crates/example", "packages/backend", "plugs/onlyalpha-plugin-test"]\nresolver="3"\n[workspace.package]\nversion="0.11.1"\nedition="2024"\n',
        "Cargo.lock": "version=4\n",
        "rust-toolchain.toml": '[toolchain]\nchannel="1.99.1"\n',
        "pyproject.toml": '[tool.uv.workspace]\nmembers=["plugs/onlyalpha-plugin-math"]\n',
        "uv.lock": "version=1\n",
        "LICENSE": "fixture license",
        "crates/example/Cargo.toml": '[package]\nname="onlyalpha-example"\nversion.workspace=true\n',
        "crates/example/src/lib.rs": 'pub const VALUE: &str = include_str!("../../../test-data/example/value.txt");',
        "test-data/example/value.txt": "independent value",
        "packages/backend/Cargo.toml": '[package]\nname="onlyalpha-backend"\nversion="0.12.0"\n[dependencies]\nonlyalpha-example={path="../../crates/example"}\nonlyalpha-plugin-test={path="../../plugs/onlyalpha-plugin-test"}\n',
        "packages/backend/src/main.rs": "fn main() {}",
        "packages/backend/python/algorithms/pyproject.toml": '[project]\nname="onlyalpha-backend-algorithms"\nversion="0.12.0"\ndependencies=["onlyalpha-plugin-math==0.5.0"]\n',
        "plugs/onlyalpha-plugin-test/Cargo.toml": '[package]\nname="onlyalpha-plugin-test"\nversion="0.4.0"\n',
        "plugs/onlyalpha-plugin-test/rust/lib.rs": "pub fn plugin() {}",
        "plugs/onlyalpha-plugin-math/pyproject.toml": '[project]\nname="onlyalpha-plugin-math"\nversion="0.5.0"\n',
        "plugs/onlyalpha-plugin-math/src/math.py": "VALUE = 1",
        "packages/frontend/package.json": '{"version":"0.13.0"}',
        "packages/frontend/package-lock.json": '{"version":"0.13.0"}',
    }
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
    git(root, "init")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "source")
    return root, git(root, "rev-parse", "HEAD")


def test_unit_bundle_is_deterministic_from_exact_commit_and_keeps_external_resources(source_repo, tmp_path):
    root, revision = source_repo
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    digest = release_sources.export(root, "libs", revision, first)
    release_sources.export(root, "libs", revision, second)
    assert first.read_bytes() == second.read_bytes()
    manifest = release_sources.verify(root, "libs", first, digest)
    assert manifest["version"] == "0.11.1"
    assert manifest["revision"] == revision
    assert "test-data/example/value.txt" in manifest["files"]
    assert not any(name.startswith("packages/") for name in manifest["files"])
    (root / "packages/backend/src/main.rs").write_text("fn main() { /* new backend */ }")
    release_sources.verify(root, "libs", first, digest)


@pytest.mark.parametrize(
    "name,mutation",
    [
        ("crates/example/src/lib.rs", "change"),
        ("test-data/example/value.txt", "remove"),
        ("crates/example/src/new.rs", "add"),
        ("crates/example/src/lib.rs", "mode"),
    ],
)
def test_same_version_unit_drift_is_rejected(source_repo, tmp_path, name, mutation):
    root, revision = source_repo
    bundle = tmp_path / "libs.zip"
    digest = release_sources.export(root, "libs", revision, bundle)
    path = root / name
    if mutation == "remove":
        path.unlink()
    elif mutation == "mode":
        path.chmod(0o755)
    else:
        path.write_text("changed")
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_sources.verify(root, "libs", bundle, digest)


def test_required_dependencies_come_from_backend_and_executor_metadata(source_repo):
    root, _ = source_repo
    assert release_sources.required_units(root) == {"libs", "plugin-test", "plugin-math"}


def test_python_plugin_and_frontend_are_independent_of_rust_workspace_configuration(source_repo, tmp_path):
    root, revision = source_repo
    references = []
    for unit in ("frontend", "plugin-math"):
        path = tmp_path / (unit + ".zip")
        references.append((unit, path, release_sources.export(root, unit, revision, path)))
    cargo = root / "Cargo.toml"
    cargo.write_text(cargo.read_text().replace('edition="2024"', 'edition="2027"'))
    for unit, path, digest in references:
        release_sources.verify(root, unit, path, digest)


def test_undeclared_local_dependency_cannot_escape_source_selection(source_repo):
    root, _ = source_repo
    path = root / "packages/backend/Cargo.toml"
    path.write_text(path.read_text() + 'hidden-plugin={path="../../hidden"}\n')
    with pytest.raises(ValueError, match="RELEASE_SOURCE_UNDECLARED_DEPENDENCY"):
        release_sources.required_units(root)


@pytest.mark.parametrize("unit", ["libs", "frontend"])
def test_exact_tree_ignores_export_ignore_and_export_subst_attributes(source_repo, tmp_path, unit):
    root, _ = source_repo
    (root / "packages/frontend/.gitignore").write_text("node_modules/\n")
    (root / ".gitattributes").write_text(".gitignore export-ignore\ncrates/example/src/lib.rs export-subst\n")
    source = root / "crates/example/src/lib.rs"
    source.write_text(source.read_text() + "\n// $Format:%H$\n")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "archive attributes")
    revision = git(root, "rev-parse", "HEAD")
    path = tmp_path / "source.zip"
    digest = release_sources.export(root, unit, revision, path)
    manifest = release_sources.verify(root, unit, path, digest)
    if unit == "frontend":
        assert "packages/frontend/.gitignore" in manifest["files"]


def test_local_archive_attributes_cannot_change_exact_commit_source_bytes(source_repo, tmp_path):
    root, revision = source_repo
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    release_sources.export(root, "libs", revision, first)
    (root / ".git/info/attributes").write_text("crates/example/src/lib.rs export-ignore\n")
    release_sources.export(root, "libs", revision, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("mutation", ["missing", "extra", "traversal", "duplicate", "symlink", "schema", "origin"])
def test_reselected_malformed_archive_is_still_rejected(source_repo, tmp_path, mutation):
    root, revision = source_repo
    path = tmp_path / "libs.zip"
    release_sources.export(root, "libs", revision, path)
    with zipfile.ZipFile(path) as archive:
        entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
    name = "source/crates/example/src/lib.rs"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for entry, raw in entries:
            if entry.filename == name:
                if mutation == "missing":
                    continue
                if mutation == "traversal":
                    entry.filename = "source/../outside"
                if mutation == "symlink":
                    entry.external_attr = 0o120777 << 16
            if entry.filename == "manifest.json" and mutation in {"schema", "origin"}:
                value = json.loads(raw)
                value["schema_version" if mutation == "schema" else "revision"] = (
                    True if mutation == "schema" else "0" * 40
                )
                raw = release_inputs.encode(value)
            archive.writestr(entry, raw)
        if mutation == "extra":
            archive.writestr("unrecorded", b"unexpected")
        if mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(name, b"duplicate")
    path.write_bytes(output.getvalue())
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_sources.verify(root, "libs", path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_export_refuses_implicit_revision_overwrite_and_conflicting_tag(source_repo, tmp_path):
    root, revision = source_repo
    bundle = tmp_path / "libs.zip"
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_sources.export(root, "libs", "HEAD", bundle)
    git(root, "tag", "libs-v0.11.1")
    digest = release_sources.export(root, "libs", revision, bundle, tag="libs-v0.11.1")
    assert release_sources.verify(root, "libs", bundle, digest)["tag"] == "libs-v0.11.1"
    with pytest.raises(FileExistsError):
        release_sources.export(root, "libs", revision, bundle)
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_sources.export(root, "libs", revision, tmp_path / "wrong.zip", tag="libs-v9.0.0")


@pytest.mark.parametrize("mutation", ["bytes", "digest", "unit", "symlink"])
def test_bundle_substitution_is_rejected(source_repo, tmp_path, mutation):
    root, revision = source_repo
    bundle = tmp_path / "libs.zip"
    digest = release_sources.export(root, "libs", revision, bundle)
    unit = "libs"
    if mutation == "bytes":
        bundle.write_bytes(bundle.read_bytes() + b"tampered")
    elif mutation == "digest":
        digest = "0" * 64
    elif mutation == "unit":
        unit = "plugin-test"
    else:
        bundle.rename(tmp_path / "original.zip")
        bundle.symlink_to(tmp_path / "original.zip")
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_sources.verify(root, unit, bundle, digest)


def selections(root: Path, revision: str, directory: Path) -> Path:
    refs = {}
    for unit in sorted(release_sources.required_units(root)):
        path = directory / (unit + ".zip")
        refs[unit] = {"path": path.name, "sha256": release_sources.export(root, unit, revision, path)}
    path = directory / "sources.json"
    path.write_text(json.dumps(refs))
    return path


def test_build_selection_reuses_original_dependency_artifacts_after_backend_changes(source_repo, tmp_path):
    root, revision = source_repo
    refs = selections(root, revision, tmp_path)
    (root / "packages/backend/src/main.rs").write_text("fn main() { /* backend change */ }")
    value = release_inputs.candidate(root, source_bundles=refs)
    path = tmp_path / "inputs.json"
    path.write_bytes(release_inputs.encode(value))
    receipt = release_inputs.verify(root, path, hashlib.sha256(path.read_bytes()).hexdigest(), source_bundles=refs)
    assert receipt["sources"]["libs"]["revision"] == revision
    assert receipt["sources"]["plugin-test"]["version"] == "0.4.0"
    release_inputs.verify_receipt(receipt, value["source_inputs"])
    (root / "crates/example/src/lib.rs").write_text("changed library, same version")
    with pytest.raises(ValueError, match="RELEASE_SOURCE"):
        release_inputs.candidate(root, source_bundles=refs)


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed-path", "missing-bundle", "substitute"])
def test_build_selection_rejects_incomplete_or_substituted_dependencies(source_repo, tmp_path, mutation):
    root, revision = source_repo
    refs = selections(root, revision, tmp_path)
    value = release_inputs.candidate(root, source_bundles=refs)
    path = tmp_path / "inputs.json"
    path.write_bytes(release_inputs.encode(value))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    selected = json.loads(refs.read_text())
    if mutation == "missing":
        del selected["libs"]
    elif mutation == "extra":
        selected["frontend"] = selected["libs"]
    elif mutation == "changed-path":
        selected["libs"]["path"] = "plugin-test.zip"
    elif mutation == "missing-bundle":
        (tmp_path / "libs.zip").unlink()
    else:
        # Even a new valid artifact at the same version needs an explicit selection.
        (root / "packages/backend/src/main.rs").write_text("fn main() { /* change */ }")
        git(root, "add", ".")
        git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "backend")
        new_revision = git(root, "rev-parse", "HEAD")
        new_path = tmp_path / "other.zip"
        selected["libs"] = {
            "path": new_path.name,
            "sha256": release_sources.export(root, "libs", new_revision, new_path),
        }
    refs.write_text(json.dumps(selected))
    with pytest.raises(ValueError, match="RELEASE_(SOURCE|INPUT)"):
        release_inputs.verify(root, path, digest, source_bundles=refs)
