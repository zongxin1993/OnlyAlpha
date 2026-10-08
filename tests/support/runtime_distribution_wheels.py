"""Deterministic wheel and provenance assembly for real isolated Runtime tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)


def build_wheel(project: Path, output: Path) -> Path:
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def installed_distribution_wheel(name: str, output: Path) -> Path:
    distribution = metadata.distribution(name)
    wheel_metadata = distribution.read_text("WHEEL")
    assert wheel_metadata is not None
    tags = tuple(line.removeprefix("Tag: ") for line in wheel_metadata.splitlines() if line.startswith("Tag: "))
    tag = next((item for item in tags if item.startswith(("py3-", "py2.py3-"))), tags[0])
    normalized = name.replace("-", "_")
    target = output / f"{normalized}-{distribution.version}-{tag}.whl"
    output.mkdir(parents=True, exist_ok=True)
    files = distribution.files
    assert files is not None
    included = tuple(item for item in files if item.parts and item.parts[0] != "..")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(included, key=str):
            source = distribution.locate_file(relative)
            assert isinstance(source, Path), "installed wheel fixture requires filesystem-backed distribution files"
            content = source.read_bytes()
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return target


def plain_artifact(
    wheel: Path,
    *,
    role: OnlyDistributionArtifactRole,
    authority: OnlyArtifactSourceProvenanceAuthority,
    repository: str,
    revision: str,
) -> OnlyDistributionArtifactManifest:
    content = wheel.read_bytes()
    distribution = metadata.distribution(wheel_distribution_name(wheel))
    return OnlyDistributionArtifactManifest(
        role=role,
        source_provenance_authority=authority,
        source_repository=repository,
        source_revision=revision,
        distribution_name=distribution.metadata["Name"],
        distribution_version=distribution.version,
        artifact_logical_name=wheel.name,
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


def wheel_distribution_name(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        content = archive.read(metadata_name).decode("utf-8")
    return next(line[6:] for line in content.splitlines() if line.startswith("Name: "))
