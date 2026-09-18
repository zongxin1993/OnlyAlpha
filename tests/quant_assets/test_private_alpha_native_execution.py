from __future__ import annotations

import hashlib
import inspect
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationBuilder
from onlyalpha_runtime_generation_manager import builder as runtime_builder_module
from onlyalpha_test_alpha_provider.provider import quant_asset_provider as example_factor_provider

from onlyalpha.application.catalog_context import OnlyExactCatalogContextV1, only_project_exact_catalog_context
from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCanonicalValueSemanticsV1,
)
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaAdapterV1,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaIsolatedProgramHost,
    OnlyPrivateAlphaProviderSnapshotEntryV1,
    OnlyPrivateAlphaProviderSnapshotV1,
    OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyPrivateAlphaSourceArtifactManifestV1,
    OnlyPrivateAlphaValidationDisposition,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_private_alpha_backend_registrations,
    only_private_alpha_type_definition,
    only_quant_asset_distribution_artifact_manifest,
    only_validate_private_alpha_revision,
)
from onlyalpha.quant_assets.private_alpha_execution import ONLY_PRIVATE_ALPHA_NUMERIC_V1
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeProviderBinding,
)


def _revision(
    source: str = "def calculate(api, inputs, parameters):\n    return {'value': api.sub(inputs['close'], parameters['offset'])}\n",
    **draft_changes: object,
) -> OnlyPrivateAlphaRevision:
    return OnlyPrivateAlphaRevision.from_draft(
        replace(
            OnlyPrivateAlphaDraft(
                alpha_id="private.alpha.native",
                semantic_version="1",
                source_text=source,
                alpha_api_version=1,
                alpha_api_contract_fingerprint=ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
                input_contract={"close": {"type": "DECIMAL", "missing": True}},
                parameter_contract={"offset": {"type": "DECIMAL"}},
                output_contract={"value": {"type": "DECIMAL", "missing": True}},
                description="Native factor",
                economic_rationale="Test",
                category="test",
            ),
            **draft_changes,
        )
    )


def _artifact() -> tuple[OnlyPrivateAlphaRevision, OnlyPrivateAlphaSourceArtifactManifestV1, bytes]:
    revision = _revision()
    evidence = only_validate_private_alpha_revision(revision)
    assert evidence.validation_disposition is OnlyPrivateAlphaValidationDisposition.PASS
    manifest, source = OnlyPrivateAlphaSourceArtifactManifestV1.materialize(revision, evidence)
    return revision, manifest, source


def _forged_closure(
    source: OnlyPrivateAlphaExecutableClosureV1, **changes: object
) -> OnlyPrivateAlphaExecutableClosureV1:
    forged = object.__new__(OnlyPrivateAlphaExecutableClosureV1)
    for name in source.__dataclass_fields__:
        object.__setattr__(forged, name, changes.get(name, getattr(source, name)))
    return forged


def test_executable_closure_requires_canonical_producer() -> None:
    revision, artifact, source = _artifact()
    with pytest.raises(TypeError, match="PRIVATE_ALPHA_EXECUTABLE_CLOSURE_CANONICAL_PRODUCER_REQUIRED"):
        OnlyPrivateAlphaExecutableClosureV1()
    with pytest.raises(TypeError):
        OnlyPrivateAlphaExecutableClosureV1(  # type: ignore[call-arg]
            revision,
            only_validate_private_alpha_revision(revision),
            artifact,
            source,
            (),
            object(),
            object(),
        )

    closure = OnlyPrivateAlphaExecutableClosureV1.create(
        revision,
        ({"close": Decimal("1")},),
        {"offset": Decimal("0")},
        host=OnlyPrivateAlphaIsolatedProgramHost(3),
    )
    assert closure.revision == revision
    forged = _forged_closure(
        closure,
        equivalence_evidence=replace(
            closure.equivalence_evidence,
            research_output_fingerprint="f" * 64,
            trading_output_fingerprint="f" * 64,
        ),
    )
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EXECUTABLE_CLOSURE_MISMATCH"):
        forged.verify_canonical()
    host = OnlyPrivateAlphaIsolatedProgramHost(3)
    forged_registrations = only_private_alpha_backend_registrations(
        closure.revision,
        closure.source_artifact,
        closure.source,
        OnlyPrivateAlphaAdapterV1("RESEARCH", "e" * 64, host),
        OnlyPrivateAlphaAdapterV1("TRADING", "d" * 64, host),
    )
    forged_equivalence = OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1.certify(
        closure.source_artifact,
        closure.source,
        forged_registrations,
        closure.certification_vectors,
        closure.certification_parameters,
    )
    forged_snapshot = OnlyPrivateAlphaProviderSnapshotV1(
        (OnlyPrivateAlphaProviderSnapshotEntryV1.derive(closure.source_artifact, forged_equivalence),)
    )
    coherent_forgery = _forged_closure(
        closure,
        registrations=forged_registrations,
        equivalence_evidence=forged_equivalence,
        provider_snapshot=forged_snapshot,
    )
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EXECUTABLE_CLOSURE_MISMATCH"):
        coherent_forgery.verify_canonical()


@pytest.mark.parametrize(
    "source",
    [
        "x = 1\n",
        "def calculate(api, inputs, parameters):\n    return inputs\ndef calculate(api, inputs, parameters):\n    return inputs\n",
        "def calculate(api, inputs):\n    return inputs\n",
        "async def calculate(api, inputs, parameters):\n    return inputs\n",
        "import os\ndef calculate(api, inputs, parameters):\n    return inputs\n",
        "def calculate(api, inputs, parameters):\n    return eval('1')\n",
        "def calculate(api, inputs, parameters):\n    return open('/tmp/x', 'w')\n",
        "def calculate(api, inputs, parameters):\n    return inputs.get('x')\n",
        "def calculate(api, inputs, parameters):\n    return {'value': inputs['a'] + inputs['b']}\n",
        "def calculate(api, inputs, parameters):\n    return {'value': inputs['a'] > inputs['b']}\n",
        "def calculate(api, inputs, parameters):\n    return {'value': inputs['a'] and inputs['b']}\n",
    ],
)
def test_validation_fails_closed_for_non_v1_source(source: str) -> None:
    evidence = only_validate_private_alpha_revision(_revision(source))
    assert evidence.validation_disposition is OnlyPrivateAlphaValidationDisposition.FAIL
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_VALIDATION_EVIDENCE_MISMATCH"):
        OnlyPrivateAlphaSourceArtifactManifestV1.materialize(_revision(source), evidence)


def test_validation_and_artifact_identities_are_deterministic_and_tamper_closed() -> None:
    revision, manifest, source = _artifact()
    assert only_validate_private_alpha_revision(revision) == only_validate_private_alpha_revision(revision)
    assert manifest.source_sha256 != manifest.source_artifact_fingerprint
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_SOURCE_ARTIFACT_MISMATCH"):
        manifest.verify(source + b"# tamper")
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_VALIDATION_EVIDENCE_MISMATCH"):
        OnlyPrivateAlphaSourceArtifactManifestV1.materialize(
            revision, replace(only_validate_private_alpha_revision(revision), revision_fingerprint="a" * 64)
        )
    forbidden = _revision("import os\ndef calculate(api, inputs, parameters):\n    return inputs\n")
    failed = only_validate_private_alpha_revision(forbidden)
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_VALIDATION_EVIDENCE_MISMATCH"):
        OnlyPrivateAlphaSourceArtifactManifestV1.materialize(
            forbidden,
            replace(
                failed,
                validation_disposition=OnlyPrivateAlphaValidationDisposition.PASS,
                errors=(),
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"input_contract": {"close": {"type": "DECIMAL", "nullable": "false"}}},
        {"input_contract": {"close": {"type": "DECIMAL", "unknown": False}}},
        {"output_contract": {"value": {"type": "DECIMAL", "semantic_type": 1}}},
        {"parameter_contract": {"offset": {"type": "DECIMAL", "required": "false"}}},
        {"parameter_contract": {"offset": {"type": "DECIMAL", "unknown": 1}}},
    ],
)
def test_alpha_contracts_reject_type_coercion_and_unknown_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        only_private_alpha_type_definition(_revision(**changes))


def test_isolated_research_trading_equivalence_and_snapshot_are_exact() -> None:
    revision, manifest, source = _artifact()
    host = OnlyPrivateAlphaIsolatedProgramHost(timeout_seconds=3)
    research = OnlyPrivateAlphaAdapterV1("RESEARCH", "a" * 64, host)
    trading = OnlyPrivateAlphaAdapterV1("TRADING", "b" * 64, host)
    vectors = (
        {"close": Decimal("2")},
        {"close": Decimal("-2")},
        {"close": Decimal("0")},
        {"close": None},
    )
    registrations = only_private_alpha_backend_registrations(revision, manifest, source, research, trading)
    evidence = OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1.certify(
        manifest, source, registrations, vectors, {"offset": Decimal("1")}
    )
    snapshot_entry = OnlyPrivateAlphaProviderSnapshotEntryV1.derive(manifest, evidence)
    snapshot = OnlyPrivateAlphaProviderSnapshotV1((snapshot_entry,))
    assert evidence.research_output_fingerprint == evidence.trading_output_fingerprint
    assert snapshot.entries[0].revision_fingerprint == revision.revision_fingerprint
    assert snapshot.snapshot_fingerprint != manifest.source_artifact_fingerprint
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EQUIVALENCE_ADAPTER_MISMATCH"):
        OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1.certify(
            manifest, source, registrations, (), {"offset": Decimal("1")}
        )
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EQUIVALENCE_EVIDENCE_MISMATCH"):
        replace(evidence, trading_output_fingerprint="f" * 64)


def test_infinite_loop_is_terminated() -> None:
    revision = _revision("def calculate(api, inputs, parameters):\n    while True:\n        inputs = inputs\n")
    evidence = only_validate_private_alpha_revision(revision)
    assert evidence.validation_disposition is OnlyPrivateAlphaValidationDisposition.PASS
    manifest, source = OnlyPrivateAlphaSourceArtifactManifestV1.materialize(revision, evidence)
    with pytest.raises(TimeoutError, match="PRIVATE_ALPHA_EXECUTION_TIMEOUT"):
        OnlyPrivateAlphaIsolatedProgramHost(timeout_seconds=0.1).execute(manifest, source, {}, {})


def test_api_operations_equal_canonical_value_semantics() -> None:
    source_text = """def calculate(api, inputs, parameters):
    return {
        'add': api.add(inputs['a'], inputs['b']), 'sub': api.sub(inputs['a'], inputs['b']),
        'mul': api.mul(inputs['a'], inputs['b']), 'div': api.div(inputs['a'], inputs['zero']),
        'negate': api.negate(inputs['a']), 'min': api.min(inputs['a'], inputs['b']),
        'max': api.max(inputs['a'], inputs['b']), 'eq': api.eq(inputs['a'], inputs['b']),
        'ne': api.ne(inputs['a'], inputs['b']), 'lt': api.lt(inputs['a'], inputs['b']),
        'le': api.le(inputs['a'], inputs['b']), 'gt': api.gt(inputs['a'], inputs['b']),
        'ge': api.ge(inputs['a'], inputs['b']), 'and': api.and_(inputs['truth'], inputs['missing']),
        'or': api.or_(inputs['truth'], inputs['missing']), 'not': api.not_(inputs['truth']),
        'where': api.where(inputs['truth'], inputs['a'], inputs['b']),
        'is_missing': api.is_missing(inputs['missing']),
        'coalesce': api.coalesce(inputs['missing'], inputs['b'])}
"""
    revision = _revision(source_text)
    evidence = only_validate_private_alpha_revision(revision)
    manifest, source = OnlyPrivateAlphaSourceArtifactManifestV1.materialize(revision, evidence)
    inputs = {
        "a": Decimal("2"),
        "b": Decimal("-1"),
        "zero": Decimal("0"),
        "truth": True,
        "missing": None,
    }
    actual = OnlyPrivateAlphaIsolatedProgramHost(3).execute(manifest, source, inputs, {})
    canonical = OnlyCanonicalValueSemanticsV1(ONLY_PRIVATE_ALPHA_NUMERIC_V1)
    assert actual == {
        "add": canonical.add(inputs["a"], inputs["b"]),
        "sub": canonical.sub(inputs["a"], inputs["b"]),
        "mul": canonical.mul(inputs["a"], inputs["b"]),
        "div": canonical.div(inputs["a"], inputs["zero"]),
        "negate": canonical.negate(inputs["a"]),
        "min": canonical.min(inputs["a"], inputs["b"]),
        "max": canonical.max(inputs["a"], inputs["b"]),
        "eq": canonical.eq(inputs["a"], inputs["b"]),
        "ne": canonical.ne(inputs["a"], inputs["b"]),
        "lt": canonical.lt(inputs["a"], inputs["b"]),
        "le": canonical.le(inputs["a"], inputs["b"]),
        "gt": canonical.gt(inputs["a"], inputs["b"]),
        "ge": canonical.ge(inputs["a"], inputs["b"]),
        "and": canonical.and_(inputs["truth"], inputs["missing"]),
        "or": canonical.or_(inputs["truth"], inputs["missing"]),
        "not": canonical.not_(inputs["truth"]),
        "where": canonical.where(inputs["truth"], inputs["a"], inputs["b"]),
        "is_missing": canonical.is_missing(inputs["missing"]),
        "coalesce": canonical.coalesce(inputs["missing"], inputs["b"]),
    }


def test_private_alpha_catalog_provider_is_snapshot_backed_not_distribution_backed() -> None:
    closure = OnlyPrivateAlphaExecutableClosureV1.create(
        _revision(),
        ({"close": Decimal("1")},),
        {"offset": Decimal("0")},
        host=OnlyPrivateAlphaIsolatedProgramHost(3),
    )
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.native.factor",
            "1",
            OnlyQuantAssetKind.ALPHA,
            OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_alpha_snapshot=closure.provider_snapshot,
    )
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    research = catalog.calculation_registry().resolve(
        OnlyCalculationKind.FACTOR,
        closure.revision.alpha_id,
        closure.revision.semantic_version,
        OnlyCalculationBackendKind.RESEARCH,
    )
    trading = catalog.calculation_registry().resolve(
        OnlyCalculationKind.FACTOR,
        closure.revision.alpha_id,
        closure.revision.semantic_version,
        OnlyCalculationBackendKind.TRADING,
    )
    assert research.definition_resolver is not None
    definition = research.definition_resolver.resolve(
        {"offset": Decimal("0")},
        {"close": OnlyCalculationReference(None, "close", "close")},
    )
    research_output = research.provider.execute(
        definition, {"close": pa.array([Decimal("2")], type=pa.decimal128(38, 12))}
    )
    trading_output = trading.provider.create(definition, object()).update({"close": Decimal("2")})
    assert research_output["value"].to_pylist() == [Decimal("2.000000000000")]
    assert trading_output == {"value": Decimal("2")}
    assert catalog.providers[0].private_alpha_snapshot == closure.provider_snapshot
    exact = only_project_exact_catalog_context(
        catalog.generation_fingerprint,
        catalog.descriptor(),
        dataset_field_contracts=(),
        registered_universes=(),
        statistics_capabilities=(),
    )
    assert {item.backend for item in exact.ordered_calculation_capabilities} == {
        OnlyCalculationBackendKind.RESEARCH,
        OnlyCalculationBackendKind.TRADING,
    }
    assert OnlyExactCatalogContextV1.from_dict(exact.to_dict()) == exact
    with pytest.raises(ValueError, match="QUANT_ASSET_PROVIDER_NOT_DISTRIBUTION_BACKED"):
        _ = provider.manifest.distribution_name


def test_runtime_artifacts_rebuild_native_registry_without_authoring_authority(tmp_path: Path) -> None:
    closure = OnlyPrivateAlphaExecutableClosureV1.create(
        _revision(),
        ({"close": Decimal("1")},),
        {"offset": Decimal("0")},
        host=OnlyPrivateAlphaIsolatedProgramHost(3),
    )
    native = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.native.factor",
            closure.revision.revision_fingerprint,
            OnlyQuantAssetKind.ALPHA,
            OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_alpha_snapshot=closure.provider_snapshot,
    )
    base = example_factor_provider()
    core_bytes = b"core"
    core_artifact = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.CORE,
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        "1" * 40,
        "onlyalpha",
        "0.9.9",
        "onlyalpha-0.9.9-py3-none-any.whl",
        hashlib.sha256(core_bytes).hexdigest(),
        len(core_bytes),
    )
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", core_artifact.artifact_sha256)
    provider_bytes = b"provider"
    provider_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="2" * 40,
        artifact_logical_name="onlyalpha_test_alpha_provider-0.9.9-py3-none-any.whl",
        artifact_bytes=provider_bytes,
        tested_core_execution_fingerprint=core.fingerprint,
        provider=base,
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(provider_artifact, provider_bytes)
    base_catalog = OnlyQuantAssetCatalogGeneration((base,))
    base_manifest = OnlyRuntimeGenerationManifest(
        core,
        (core_artifact.manifest_fingerprint, provider_artifact.manifest_fingerprint),
        (core_artifact.artifact_sha256, provider_artifact.artifact_sha256),
        (
            OnlyRuntimeProviderBinding(
                base.manifest.provider_id,
                base.manifest.provider_version,
                base.content_fingerprint,
                provider_artifact.artifact_sha256,
            ),
        ),
        base_catalog.generation_fingerprint,
        provider_artifact.implementations,
    )
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    catalog = OnlyQuantAssetCatalogGeneration((base, native))
    forged = _forged_closure(
        closure,
        equivalence_evidence=replace(
            closure.equivalence_evidence,
            research_output_fingerprint="f" * 64,
            trading_output_fingerprint="f" * 64,
        ),
    )
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EXECUTABLE_CLOSURE_MISMATCH"):
        store.put_private_alpha_runtime(forged, native)
    manifest = builder.bind_private_alpha_closure(
        base_manifest=base_manifest,
        expected_catalog=catalog,
        closure=closure,
    )

    binding = manifest.private_alpha_bindings[0]
    mutations = (
        replace(binding, provider_snapshot_fingerprint="f" * 64),
        replace(binding, entry=replace(binding.entry, revision_fingerprint="f" * 64)),
        replace(binding, entry=replace(binding.entry, source_artifact_fingerprint="f" * 64)),
    )
    for index, mutation in enumerate(mutations):
        mismatched = replace(manifest, private_alpha_bindings=(mutation,))
        with pytest.raises(ValueError, match="RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH"):
            builder.verify_exact_artifacts(mismatched)
        with pytest.raises(ValueError, match="RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH"):
            builder.rebuild_private_alpha_providers(mismatched)
        with pytest.raises(ValueError, match="RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH"):
            builder.rebuild_validated(
                expected_manifest=mismatched,
                environment_root=tmp_path / f"mismatched-{index}",
            )
    manifest_rejections = (
        replace(binding, entry=replace(binding.entry, semantic_version="2")),
        replace(binding, entry=replace(binding.entry, alpha_id="private.strategy.wrong_family")),
        replace(
            binding,
            provider_snapshot_fingerprint="e" * 64,
            runtime_artifact_fingerprint="e" * 64,
            entry=replace(
                binding.entry,
                alpha_id="private.alpha.complete_different",
                semantic_version="9",
                revision_fingerprint="e" * 64,
                source_sha256="e" * 64,
                source_artifact_fingerprint="e" * 64,
                alpha_api_contract_fingerprint="e" * 64,
                research_adapter_fingerprint="e" * 64,
                trading_adapter_fingerprint="e" * 64,
                research_implementation_fingerprint="e" * 64,
                trading_implementation_fingerprint="e" * 64,
                equivalence_evidence_fingerprint="e" * 64,
            ),
        ),
    )
    for mutation in manifest_rejections:
        with pytest.raises(ValueError, match="RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH"):
            replace(manifest, private_alpha_bindings=(mutation,))
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH"):
        replace(manifest, private_alpha_bindings=(binding, binding))

    del closure
    rebuilt = builder.rebuild_private_alpha_providers(manifest)[0]
    assert rebuilt.descriptor() == native.descriptor()
    registry = OnlyQuantAssetCatalogGeneration((rebuilt,)).calculation_registry()
    research = registry.resolve(
        OnlyCalculationKind.FACTOR,
        "private.alpha.native",
        "1",
        OnlyCalculationBackendKind.RESEARCH,
    )
    assert research.definition_resolver is not None
    definition = research.definition_resolver.resolve(
        {"offset": Decimal("0")},
        {"close": OnlyCalculationReference(None, "close", "close")},
    )
    assert research.provider.execute(
        definition,
        {"close": pa.array([Decimal("2")], type=pa.decimal128(38, 12))},
    )["value"].to_pylist() == [Decimal("2.000000000000")]
    trading = registry.resolve(
        OnlyCalculationKind.FACTOR,
        "private.alpha.native",
        "1",
        OnlyCalculationBackendKind.TRADING,
    )
    assert trading.provider.create(definition, object()).update({"close": Decimal("2")}) == {"value": Decimal("2")}
    store._private_alpha_runtime_path(manifest.private_alpha_bindings[0].runtime_artifact_fingerprint).unlink()
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_RUNTIME_ARTIFACT_MISMATCH"):
        builder.rebuild_private_alpha_providers(manifest)


def test_historical_native_builder_has_no_current_private_asset_resolution_path() -> None:
    source = inspect.getsource(runtime_builder_module)
    assert "OnlyPostgresPrivateAssetStore" not in source
    assert "load_alpha_revision" not in source
    assert "latest_revision" not in source
