"""Actual installed-generation portable publication, not Chart Work dispatch."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.distribution import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactRole,
)
from onlyalpha.research.artifact import OnlyParquetResearchCalculationArtifactStoreV2
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment
from tests.support.runtime_distribution_wheels import installed_distribution_wheel, plain_artifact

from .test_native_publication import _PUBLISH
from .test_native_publication import native_publication_case as native_publication_case

pytestmark = pytest.mark.contract

_ARTIFACT = r"""
import json, sys
from pathlib import Path
from datetime import UTC, datetime
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.artifact_store import OnlyLocalImmutableArtifactStore
from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_artifact
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
def forbidden(*args, **kwargs):
    raise AssertionError('Artifact projection reexecuted numeric backend')
OnlyResearchCalculationExecutor._execute_verified_v2 = forbidden
root = Path(sys.argv[1])
frozen = OnlyResearchCalculationRuntimeResolutionV1.from_dict(json.loads((root / 'frozen.json').read_text()))
artifact = only_publish_native_calculation_artifact(
    generations=OnlyRuntimeGenerationRegistry(root / 'registry'), frozen=frozen,
    distribution_artifact_store=OnlyLocalImmutableArtifactStore(Path((root / 'artifact-store-root.txt').read_text())),
    dataset_store_root=root / 'chart-input' / 'dataset', calculation_result_root=root / 'calculation-results',
    execution_evidence_root=root / 'semantic', research_result_root=root / 'research-results',
    research_artifact_root=root / 'artifacts', audit_time=lambda: datetime(2026, 10, 9, tzinfo=UTC),
)
print(json.dumps(artifact.manifest.to_dict()))
"""


def test_two_installed_generations_publish_same_result_and_distinct_portable_artifacts(
    native_publication_case,
    exact_host_environment,
    tmp_path,
):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration

    chart, compilation, registry, first_python, _ = native_publication_case
    builder, built, _ = exact_host_environment
    original_registry = {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}
    original_dataset = {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    (tmp_path / "artifacts").mkdir()
    first_result = json.loads(
        subprocess.check_output([str(first_python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    first_artifact = json.loads(
        subprocess.check_output([str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True)
    )
    assert (
        json.loads(subprocess.check_output([str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True))
        == first_artifact
    )

    # Different SUPPORT bytes create an independent installed generation, with no
    # change to scientific inputs or the selected Calculation implementation.
    wheel = installed_distribution_wheel("packaging", tmp_path / "independent-support-wheel")
    raw = wheel.read_bytes()
    support = plain_artifact(
        wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="PyPA-packaging",
        revision="release-" + metadata.version("packaging"),
    )
    builder.artifact_store.put_once(support, raw)
    artifacts = tuple(builder.artifact_store.fetch_exact(identity)[0] for identity in built.manifest.artifact_sha256s)
    second = builder.build_validated(
        artifacts=(*artifacts, support),
        expected_catalog=OnlyQuantAssetCatalogGeneration((quant_asset_provider(),)),
        environment_root=tmp_path / "independent-generation",
    )
    assert second.manifest.runtime_generation_fingerprint != built.manifest.runtime_generation_fingerprint
    other = tmp_path / "independent-publication"
    other.mkdir()
    other_registry = OnlyRuntimeGenerationRegistry(other / "registry")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    other_registry.prepare(second.manifest, actor="fixture", occurred_at=now)
    other_registry.admit_ready(second.validation_evidence, actor="fixture", occurred_at=now)
    shutil.copytree(tmp_path / "chart-input", other / "chart-input")
    (other / "semantic").mkdir()
    (other / "artifacts").mkdir()
    (other / "artifact-store-root.txt").write_text(str(builder.artifact_store.root))
    second_python = builder._environment_python(tmp_path / "independent-generation")
    # Compile in the second sealed process; the original E1 Work and frozen
    # compilation are never upgraded/rebound. This is a new foundation request.
    compiler = r"""
import json, sys
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.hosted import only_load_hosted_quant_asset_catalog, only_verify_hosted_runtime_generation
from onlyalpha_runtime_generation_manager.search_worker import _resolve_calculation_publication
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from pathlib import Path
root = Path(sys.argv[1])
original = OnlyResearchCalculationRuntimeResolutionV1.from_dict(json.loads(Path(sys.argv[2]).read_text()))
validation = OnlyRuntimeGenerationRegistry(root / 'registry').load_validation_evidence(sys.argv[3])
only_verify_hosted_runtime_generation(validation)
catalog = only_load_hosted_quant_asset_catalog(validation)
print(json.dumps(_resolve_calculation_publication(original.specification, catalog, validation)))
"""
    frozen = subprocess.check_output(
        [
            str(second_python),
            "-I",
            "-c",
            compiler,
            str(other),
            str(tmp_path / "frozen.json"),
            second.manifest.runtime_generation_fingerprint,
        ],
        text=True,
    )
    (other / "frozen.json").write_text(frozen)
    second_result = json.loads(
        subprocess.check_output([str(second_python), "-I", "-c", _PUBLISH, str(other), "execute"], text=True)
    )
    second_artifact = json.loads(
        subprocess.check_output([str(second_python), "-I", "-c", _ARTIFACT, str(other)], text=True)
    )
    assert first_result["result"] == second_result["result"]
    assert first_artifact["artifact_content_fingerprint"] != second_artifact["artifact_content_fingerprint"]
    assert first_artifact["selected_evidence"] != second_artifact["selected_evidence"]
    assert original_registry == {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}
    assert original_dataset == {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    assert (
        json.loads((tmp_path / "frozen.json").read_text())["runtime_generation_fingerprint"]
        == compilation.resolution.runtime_generation_fingerprint
    )

    portable = tmp_path / "portable"
    shutil.copytree(tmp_path / "artifacts", portable)
    shutil.copytree(other / "artifacts", portable, dirs_exist_ok=True)
    for artifact in (first_artifact, second_artifact):
        loaded = OnlyParquetResearchCalculationArtifactStoreV2(portable).load_verified(
            artifact["artifact_content_fingerprint"],
            research_result_fingerprint=artifact["result"]["research_result_fingerprint"],
        )
        calculation = next(iter(loaded.calculations.values()))
        values = calculation.outputs[0].table["value"].to_pylist()
        readiness = calculation.readiness[0].table.to_pylist()
        assert values == [2] * len(values)  # This recorded market fixture has exact volume 2 on every Bar.
        assert readiness[0]["readiness"] == "PARTIAL"
        assert readiness[1]["reason"] == "WARMUP_INCOMPLETE"
        assert readiness[2]["readiness"] == "READY"
        assert readiness[2]["reason"] == "NONE"
    shutil.rmtree(tmp_path / "calculation-results")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(
            [str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True, stderr=subprocess.PIPE
        )
    assert not (tmp_path / "calculation-results").exists()
    assert OnlyParquetResearchCalculationArtifactStoreV2(portable).load_verified(
        first_artifact["artifact_content_fingerprint"],
        research_result_fingerprint=first_artifact["result"]["research_result_fingerprint"],
    )
    offline = r"""
import importlib.abc, sys
class NoExecutableAuthority(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('onlyalpha.runtime', 'onlyalpha.application', 'onlyalpha_runtime_generation_manager',
                                'onlyalpha.quant_assets.private_factor_execution')):
            raise AssertionError('portable read imported executable Authority: ' + fullname)
sys.meta_path.insert(0, NoExecutableAuthority())
from pathlib import Path
from importlib import metadata
from onlyalpha.research.artifact import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation import execution_provenance
def fail(*args, **kwargs):
    raise AssertionError('portable read attempted upstream access, discovery or execution')
metadata.entry_points = fail
OnlyParquetResearchDatasetSnapshotStore.load_verified_table = fail
OnlyParquetResearchDatasetSnapshotStore.acknowledge_exact = fail
OnlyResearchCalculationExecutor._execute_verified_v2 = fail
execution_provenance._only_issue_research_runtime_execution_context = fail
store = OnlyParquetResearchCalculationArtifactStoreV2(Path(sys.argv[1]))
first, second = (store.load_verified(identity, research_result_fingerprint=sys.argv[2]) for identity in sys.argv[3:])
assert first.manifest.result == second.manifest.result
assert first.manifest.artifact_content_fingerprint != second.manifest.artifact_content_fingerprint
print(first.manifest.artifact_content_fingerprint, second.manifest.artifact_content_fingerprint)
"""
    identities = [item["artifact_content_fingerprint"] for item in (first_artifact, second_artifact)]
    assert (
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                offline,
                str(portable),
                first_artifact["result"]["research_result_fingerprint"],
                *identities,
            ],
            text=True,
        ).split()
        == identities
    )
