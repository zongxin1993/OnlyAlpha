from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OnlyRunArtifactTarget:
    run_root: Path


@dataclass(frozen=True, slots=True)
class OnlyArtifactDescriptor:
    artifact_type: str
    relative_path: str
    format: str
    schema_version: int
    row_count: int | None
    sha256: str
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyBacktestArtifactManifest:
    schema_version: int
    result_fingerprint: str
    analysis_fingerprint: str
    artifact_content_fingerprint: str
    artifacts: tuple[OnlyArtifactDescriptor, ...]
