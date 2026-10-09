"""Published subset must never reduce complete Calculation proof obligations."""

import hashlib
from dataclasses import replace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.canonical import only_canonical_json
from onlyalpha.distribution import OnlyDistributionArtifactRole
from onlyalpha.generation_identity import (
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.quant_assets import (
    OnlyDistributionProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from tests.quant_assets.test_retained_generation_proof import _core_inventory, retained_proof_case
from tests.research.artifact.test_calculation_v2 import _publication, _root
from tests.research.calculation.test_execution_readiness_v2 import SMA, _AtomicBackend, _graph, _registry

pytestmark = pytest.mark.contract


def _complete_output_case(tmp_path, mutate=None):
    definition = replace(
        SMA,
        type_id="fixture.indicator.complete_outputs",
        outputs=(SMA.outputs[0], replace(SMA.outputs[0], name="unselected")),
    )
    registry = _registry(_AtomicBackend(mutate), type_definition=definition)
    registration = registry.resolve(
        definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.RESEARCH
    )
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "fixture.indicator.library",
            "1",
            OnlyQuantAssetKind.INDICATOR,
            OnlyDistributionProviderSource("onlyalpha-test-portable-indicator", "1"),
        ),
        calculation_registrations=(registration,),
    )
    original, _, _ = retained_proof_case()
    core = next(item for item in original.distributions if item.role is OnlyDistributionArtifactRole.CORE)
    distribution = only_quant_asset_distribution_artifact_manifest(
        source_repository="hermetic-portable-indicator-fixture",
        source_revision="1" * 40,
        artifact_logical_name="onlyalpha_test_portable_indicator-1-py3-none-any.whl",
        artifact_bytes=b"copied-attestation-fixture-not-installed-bytes",
        tested_core_execution_fingerprint=original.generation.core_execution.fingerprint,
        provider=provider,
    )
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    distributions = tuple(sorted((core, distribution), key=lambda item: item.manifest_fingerprint))
    generation = OnlyRuntimeGenerationManifest(
        original.generation.core_execution,
        tuple(item.manifest_fingerprint for item in distributions),
        tuple(sorted(item.artifact_sha256 for item in distributions)),
        (
            OnlyRuntimeProviderBinding(
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
                distribution.artifact_sha256,
            ),
        ),
        catalog.generation_fingerprint,
        (*distribution.implementations, *_core_inventory()),
    )
    selected = registration.implementation_manifest
    proof = OnlyRetainedRuntimeGenerationProofV1(
        generation,
        OnlyRuntimeGenerationValidationEvidence.from_manifest(generation),
        distributions,
        (selected,),
        only_canonical_json(catalog.descriptor()),
    )
    graph = _graph(type_definition=definition)
    return _publication(
        tmp_path,
        registry=registry,
        proof_case=lambda: (proof, graph, ((graph.nodes[0].fingerprint, selected.implementation_fingerprint),)),
    )


@pytest.mark.parametrize("family", ("values", "readiness"))
def test_unselected_outputs_and_every_instrument_remain_retained_and_verified(tmp_path, family):
    publish, store, _, _, _, _ = _complete_output_case(tmp_path)
    artifact = publish()
    calculation = next(iter(artifact.calculations.values()))
    assert {series.output_name for series in artifact.manifest.result.plan.published_series} == {"value"}
    assert len(calculation.outputs) == len(calculation.readiness) == 2
    assert {item.instrument_id for item in calculation.outputs} == {"A.XNAS", "B.XNAS"}
    assert all(set(item.table.column_names) == {"ts_event_ns", "value", "unselected"} for item in calculation.outputs)
    assert all(set(item.table["output_name"].to_pylist()) == {"value", "unselected"} for item in calculation.readiness)
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    payload = artifact.manifest.to_dict()
    partition = payload["calculations"][0]["value_partitions" if family == "values" else "readiness_partitions"][1]
    descriptor = next(item for item in payload["files"] if item["relative_path"].endswith(partition["relative_path"]))
    path = root / descriptor["relative_path"]
    table = pq.read_table(path)
    if family == "values":
        values = table["unselected"].to_pylist()
        values[0] += 1
        table = table.set_column(
            table.schema.get_field_index("unselected"),
            table.schema.field("unselected"),
            pa.array(values, type=table["unselected"].type),
        )
    else:
        states = table["readiness"].to_pylist()
        index = table["output_name"].to_pylist().index("unselected")
        states[index] = "UNAVAILABLE"
        table = table.set_column(
            table.schema.get_field_index("readiness"), table.schema.field("readiness"), pa.array(states)
        )
    pq.write_table(table, path)
    raw = path.read_bytes()
    partition["byte_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor.update(byte_sha256=partition["byte_sha256"], byte_size=len(raw))
    (root / "artifact_manifest.json").write_text(only_canonical_json(payload))
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_verified(
            artifact.manifest.artifact_content_fingerprint,
            research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
        )


@pytest.mark.parametrize("null_states", (False, True))
def test_complete_selected_and_unselected_readiness_states_survive_portable_roundtrip(tmp_path, null_states):
    from onlyalpha.research.calculation.readiness import OnlyResearchOutputReadiness

    def mutate(outputs, readiness, calls):
        for name in outputs:
            if null_states:
                outputs[name] = pa.array([None] * 4, type=outputs[name].type)
                readiness[name] = OnlyResearchOutputReadiness(
                    pa.array(["PARTIAL", "READY", "UNAVAILABLE", "UNAVAILABLE"]),
                    pa.array(["WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"]),
                )
            else:
                outputs[name] = pa.array([0] * 4, type=outputs[name].type)
                readiness[name] = OnlyResearchOutputReadiness(
                    pa.array(["PARTIAL", "PARTIAL", "READY", "READY"]),
                    pa.array(["WARMUP_INCOMPLETE", "WARMUP_INCOMPLETE", "NONE", "NONE"]),
                )

    publish, store, _, _, _, _ = _complete_output_case(tmp_path, mutate)
    artifact = publish()
    loaded = store.load_verified(
        artifact.manifest.artifact_content_fingerprint,
        research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
    )
    for calculation in loaded.calculations.values():
        for output in calculation.outputs:
            for name in ("value", "unselected"):
                assert output.table[name].to_pylist() == ([None] * 4 if null_states else [0] * 4)
        for output in calculation.readiness:
            assert set(output.table["output_name"].to_pylist()) == {"value", "unselected"}
            expected = (
                {"WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"}
                if null_states
                else {"WARMUP_INCOMPLETE", "NONE"}
            )
            assert set(output.table["reason"].to_pylist()) == expected
