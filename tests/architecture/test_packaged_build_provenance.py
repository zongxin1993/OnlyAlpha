from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

import onlyalpha.build_provenance as runtime_provenance
from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1, only_packaged_build_provenance
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from scripts.embed_build_provenance import (
    build_provenance_bytes,
    load_carried_build_provenance,
    read_git_build_source_revision,
    resolve_build_provenance_bytes,
)

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]


def _run_build(source: Path, outdir: Path, target: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("ONLYALPHA_BUILD_SOURCE_REVISION", None)
    return subprocess.run(
        [sys.executable, "-m", "build", f"--{target}", "--no-isolation", "--outdir", str(outdir), str(source)],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


@pytest.fixture(scope="module")
def built_sdist(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, bytes, bytes, str]]:
    temporary = tmp_path_factory.mktemp("packaged-provenance")
    output = temporary / "sdist"
    output.mkdir()
    completed = _run_build(ROOT, output, "sdist")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    archive = next(output.glob("onlyalpha-*.tar.gz"))
    extracted = temporary / "extracted"
    extracted.mkdir()
    with tarfile.open(archive) as bundle:
        provenance_member = next(
            member for member in bundle.getmembers() if member.name.endswith("src/onlyalpha/_build_provenance.json")
        )
        digest_member = next(
            member for member in bundle.getmembers() if member.name.endswith("src/onlyalpha/_build_provenance.sha256")
        )
        provenance_handle = bundle.extractfile(provenance_member)
        digest_handle = bundle.extractfile(digest_member)
        assert provenance_handle is not None and digest_handle is not None
        provenance = provenance_handle.read()
        digest = digest_handle.read()
        bundle.extractall(extracted, filter="data")
    source = next(extracted.iterdir())
    assert not (source / ".git").exists()
    yield source, provenance, digest, read_git_build_source_revision(ROOT)


def test_source_checkout_has_one_git_origin_and_no_tracked_carrier() -> None:
    assert not (ROOT / "src/onlyalpha/_build_provenance.json").exists()
    assert not (ROOT / "src/onlyalpha/_build_provenance.sha256").exists()
    revision = read_git_build_source_revision(ROOT)
    assert resolve_build_provenance_bytes(ROOT) == build_provenance_bytes(ROOT, revision)


def test_sdist_builds_wheel_without_git_and_preserves_exact_provenance(
    built_sdist: tuple[Path, bytes, bytes, str], tmp_path: Path
) -> None:
    source, sdist_provenance, _, original_revision = built_sdist
    wheel_output = tmp_path / "wheel"
    wheel_output.mkdir()
    completed = _run_build(source, wheel_output, "wheel")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    wheel = next(wheel_output.glob("onlyalpha-*.whl"))
    with zipfile.ZipFile(wheel) as bundle:
        wheel_provenance = bundle.read("onlyalpha/_build_provenance.json")
    assert wheel_provenance == sdist_provenance
    assert json.loads(wheel_provenance)["source_revision"] == original_revision


@pytest.mark.parametrize("tamper", ["semantic", "noncanonical"])
def test_tampered_sdist_carrier_fails_closed(
    built_sdist: tuple[Path, bytes, bytes, str], tmp_path: Path, tamper: str
) -> None:
    source, _, _, _ = built_sdist
    tampered = tmp_path / tamper
    shutil.copytree(source, tampered)
    carrier = tampered / "src/onlyalpha/_build_provenance.json"
    payload = json.loads(carrier.read_bytes())
    if tamper == "semantic":
        payload["source_revision"] = "2" * 40
        carrier.write_bytes((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode())
    else:
        carrier.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    output = tmp_path / f"{tamper}-wheel"
    output.mkdir()
    completed = _run_build(tampered, output, "wheel")
    assert completed.returncode != 0
    assert "ONLYALPHA_BUILD_PROVENANCE_INVALID" in completed.stdout + completed.stderr


def test_git_and_carried_provenance_disagreement_fails_closed(monkeypatch, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "src/onlyalpha").mkdir(parents=True)
    shutil.copy2(ROOT / "pyproject.toml", repository / "pyproject.toml")
    (repository / ".git").mkdir()
    carried = build_provenance_bytes(repository, "2" * 40)
    carrier = repository / "src/onlyalpha/_build_provenance.json"
    carrier.write_bytes(carried)
    carrier.with_name("_build_provenance.sha256").write_text(hashlib.sha256(carried).hexdigest() + "\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "1" * 40 + "\n", ""),
    )
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_PROVENANCE_CONFLICT"):
        resolve_build_provenance_bytes(repository)


def test_missing_git_and_missing_carrier_fails_closed(tmp_path: Path) -> None:
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_SOURCE_REVISION_UNAVAILABLE"):
        resolve_build_provenance_bytes(tmp_path)


def test_runtime_reader_requires_canonical_bytes_and_installed_version(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "onlyalpha"
    package.mkdir()
    revision = "1" * 40
    canonical = build_provenance_bytes(ROOT, revision)
    (package / "_build_provenance.json").write_bytes(canonical)
    monkeypatch.setattr(runtime_provenance.resources, "files", lambda _: package)
    monkeypatch.setattr(runtime_provenance.metadata, "version", lambda _: "0.9.9")
    value = only_packaged_build_provenance()
    assert value.source_revision == revision
    (package / "_build_provenance.json").write_text(json.dumps(json.loads(canonical), indent=2) + "\n")
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_PROVENANCE_INVALID"):
        only_packaged_build_provenance()


def test_build_api_separates_git_origin_from_carrier_and_has_no_ambient_override() -> None:
    from scripts import embed_build_provenance

    assert not hasattr(embed_build_provenance, "resolve_build_source_revision")
    assert "os.environ" not in inspect.getsource(embed_build_provenance)
    assert set(inspect.signature(read_git_build_source_revision).parameters) == {"repository_root"}


@pytest.mark.parametrize(
    "relative_path",
    (
        "tests/research/postgres/test_parameter_search_recovery.py",
        "tests/research/postgres/test_search_product_cross_authority_recovery.py",
    ),
)
def test_real_postgres_recovery_does_not_bind_source_checkout_provenance_stub(relative_path: str) -> None:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "source_checkout_parameter_build_provenance_stub" not in source
    assert "packaged_build_provenance_reader" not in source


def test_malformed_packaged_build_provenance_fails_closed() -> None:
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_PROVENANCE_INVALID"):
        OnlyPackagedBuildProvenanceV1(
            OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            "OnlyAlpha",
            "unknown",
            "onlyalpha",
            "0.9.9",
        )


def test_carrier_digest_is_verified(built_sdist: tuple[Path, bytes, bytes, str], tmp_path: Path) -> None:
    source, _, _, _ = built_sdist
    copied = tmp_path / "digest-tamper"
    shutil.copytree(source, copied)
    digest = copied / "src/onlyalpha/_build_provenance.sha256"
    digest.write_text("0" * 64 + "\n")
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_PROVENANCE_INVALID"):
        load_carried_build_provenance(copied)
