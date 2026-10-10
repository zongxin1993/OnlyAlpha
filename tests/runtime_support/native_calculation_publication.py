"""Installed native Result publication script shared by exact-host tests."""

from pathlib import Path


def provision_native_publication_roots(root: Path) -> None:
    """Fixture deployment, never producer fallback after an unavailable owner."""
    for name in ("artifacts", "research-results", "semantic", "calculation-results"):
        owner = root / name
        owner.mkdir(exist_ok=True)
        (owner / ".source-cut.lock").touch(exist_ok=True)


PUBLISH = """
import json, sys
from pathlib import Path
from datetime import UTC, datetime
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.artifact_store import OnlyLocalImmutableArtifactStore
from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_result
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor

root = Path(sys.argv[1])
frozen = OnlyResearchCalculationRuntimeResolutionV1.from_dict(json.loads((root / 'frozen.json').read_text()))
if sys.argv[2] == 'no_reexecute':
    def forbidden(*args, **kwargs):
        raise AssertionError('exact publication reuse reexecuted numeric backend')
    OnlyResearchCalculationExecutor._execute_verified_v2 = forbidden
result, evidence = only_publish_native_calculation_result(
    generations=OnlyRuntimeGenerationRegistry(root / 'registry'), frozen=frozen,
    distribution_artifact_store=OnlyLocalImmutableArtifactStore(Path((root / 'artifact-store-root.txt').read_text())),
    dataset_store_root=root / 'chart-input' / 'dataset',
    calculation_result_root=root / 'calculation-results',
    execution_evidence_root=root / 'semantic', research_result_root=root / 'research-results',
    research_artifact_root=root / 'artifacts',
    audit_time=lambda: datetime(2026, 10, 9, tzinfo=UTC),
)
print(json.dumps({'result': result.manifest.to_dict(), 'evidence': evidence.to_dict()}))
"""
