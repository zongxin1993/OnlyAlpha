from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationRegistry,
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
    only_compose_authoring_research_worker,
)
from onlyalpha_example_alpha.provider import quant_asset_provider

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import (
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateL3Draft,
    OnlyPrivateL3Revision,
    OnlyPrivateL4Draft,
    OnlyPrivateL4Revision,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_discover_quant_asset_providers,
)
from onlyalpha.research.execution import OnlyResearchExecutionPolicy
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from tests.research.specification.support import specification


class _Revisions:
    def __init__(self, l3: OnlyPrivateL3Revision, l4: OnlyPrivateL4Revision | None = None) -> None:
        self.l3 = l3
        self.l4 = l4

    def load_l3_revision(self, factor_id: str, fingerprint: str) -> OnlyPrivateL3Revision:
        if (factor_id, fingerprint) != (self.l3.factor_id, self.l3.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.l3

    def load_l4_revision(self, strategy_id: str, fingerprint: str) -> OnlyPrivateL4Revision:
        if self.l4 is None or (strategy_id, fingerprint) != (
            self.l4.strategy_id,
            self.l4.revision_fingerprint,
        ):
            raise OnlyPrivateAssetNotFoundError()
        return self.l4


def _l3_revision() -> OnlyPrivateL3Revision:
    return OnlyPrivateL3Revision.from_draft(
        OnlyPrivateL3Draft(
            factor_id="private.factor.momentum",
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
            l3_api_version=1,
            l3_api_contract_fingerprint="a" * 64,
            input_contract={},
            parameter_contract={},
            output_contract={},
            description="Momentum",
            economic_rationale="Trend",
            category="momentum",
        )
    )


def _generation() -> tuple[OnlyAuthoringExecutionGeneration, OnlyPrivateAssetRevisionBindingResolver]:
    formal = quant_asset_provider()
    experiment_id = "exp-" + "a" * 32
    revision = "1" * 40
    candidate = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id=f"candidate.example.alpha.{experiment_id.removeprefix('exp-')}",
            provider_version=revision,
            layer=OnlyQuantAssetLayer.FACTOR,
            distribution_name=formal.manifest.distribution_name,
            distribution_version=formal.manifest.distribution_version,
        ),
        calculation_registrations=formal.calculation_registrations,
    )
    installed = only_discover_quant_asset_providers()
    catalog = OnlyQuantAssetCatalogGeneration(
        tuple(
            candidate if provider.manifest.provider_id == formal.manifest.provider_id else provider
            for provider in installed.providers
        )
    )
    revision = _l3_revision()
    revisions = OnlyPrivateAssetRevisionBindingResolver(_Revisions(revision))
    return (
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.L3_FACTOR, revision.factor_id, revision.revision_fingerprint
            ),
            private_asset_revisions=revisions,
            candidate_provider_id=candidate.manifest.provider_id,
            candidate_provider_version=candidate.manifest.provider_version,
            catalog=catalog,
        ),
        revisions,
    )


def test_generation_owns_exact_catalog_and_process_composition(tmp_path: Path) -> None:
    generation, revisions = _generation()
    services = generation.engine_services()
    definitions = services.assembler.components.calculations.type_definitions()
    assert any(item.type_id == "example.factor.momentum" for item in definitions)
    assert any(item.type_id == "onlyalpha.target.forward_return" for item in definitions)
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    assert store.commit(generation) == store.commit(generation)
    reader = OnlyVerifiedAuthoringGenerationReader(store, revisions)
    resolution = OnlyAuthoringExecutionGenerationRegistry((generation,), reader).resolve(
        generation.fingerprint, specification()
    )
    assert resolution.specification_fingerprint == specification().specification_fingerprint
    assert store.verify(generation).is_file()
    assert only_canonical_json(store.load_descriptor_verified(generation.fingerprint)) == only_canonical_json(
        generation.descriptor()
    )
    assert reader.load_verified(generation.fingerprint) == generation.provenance
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT"):
        store.load_descriptor_verified("0" * 64)


def test_generation_fails_closed_on_catalog_or_durable_descriptor_drift(tmp_path: Path) -> None:
    generation, revisions = _generation()
    with pytest.raises(ValueError, match="AUTHORING_CANDIDATE_PROVIDER_NOT_FOUND"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.L3_FACTOR,
                generation.provenance.private_asset_id,
                generation.provenance.private_asset_revision_fingerprint,
            ),
            private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(_Revisions(_l3_revision())),
            candidate_provider_id=generation.provenance.candidate_provider_id,
            candidate_provider_version=generation.provenance.candidate_provider_version,
            catalog=OnlyQuantAssetCatalogGeneration(()),
        )
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    path = store.commit(generation)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_MISMATCH"):
        store.verify(generation)
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT"):
        store.load_descriptor_verified(generation.fingerprint)
    reader = OnlyVerifiedAuthoringGenerationReader(store, revisions)
    with pytest.raises(ValueError, match="AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION"):
        OnlyAuthoringExecutionGenerationRegistry((), reader)
    with pytest.raises(ValueError, match="AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION"):
        OnlyAuthoringExecutionGenerationRegistry((generation, generation), reader)


def test_descriptor_rejects_candidate_provider_content_mismatch(tmp_path: Path) -> None:
    generation, revisions = _generation()
    descriptor = generation.descriptor()
    identity = generation.provenance.identity_dict()
    identity["candidate_provider_content_fingerprint"] = "f" * 64
    identity["private_asset_kind"] = OnlyPrivateAssetKind.L3_FACTOR
    identity.pop("execution_generation_fingerprint")
    forged = OnlyResearchAuthoringProvenance(
        **identity,  # type: ignore[arg-type]
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(
            **{key: value for key, value in identity.items() if key != "schema_version"}  # type: ignore[arg-type]
        ),
    )
    descriptor["execution_generation_fingerprint"] = forged.execution_generation_fingerprint
    descriptor["provenance"] = forged.to_dict()
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{forged.execution_generation_fingerprint}.json").write_text(
        only_canonical_json(descriptor) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT"):
        OnlyVerifiedAuthoringGenerationReader(OnlyAuthoringExecutionGenerationStore(tmp_path), revisions).load_verified(
            forged.execution_generation_fingerprint
        )


def test_registry_reanchors_revision_authority_on_every_read(tmp_path: Path) -> None:
    generation, _ = _generation()
    authority = _Revisions(_l3_revision())
    revisions = OnlyPrivateAssetRevisionBindingResolver(authority)
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    store.commit(generation)
    registry = OnlyAuthoringExecutionGenerationRegistry(
        (generation,), OnlyVerifiedAuthoringGenerationReader(store, revisions)
    )
    assert registry.load_verified(generation.fingerprint) == generation.provenance

    authority.l3 = OnlyPrivateL3Revision.from_draft(
        OnlyPrivateL3Draft(
            factor_id="private.factor.other",
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
            l3_api_version=1,
            l3_api_contract_fingerprint="a" * 64,
            input_contract={},
            parameter_contract={},
            output_contract={},
            description="",
            economic_rationale="",
            category="other",
        )
    )
    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"):
        registry.load_verified(generation.fingerprint)


def test_generation_descriptor_carries_only_db_native_provenance(tmp_path: Path) -> None:
    generation, _ = _generation()
    assert generation.descriptor()["schema_version"] == 1
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    store.commit(generation)
    loaded = store.load_descriptor_verified(generation.fingerprint)
    assert only_canonical_json(loaded) == only_canonical_json(generation.descriptor())
    assert "source_repository" not in loaded["provenance"]


def test_worker_composition_verifies_descriptor_before_postgres_claim_capability(tmp_path: Path) -> None:
    generation, revisions = _generation()
    store = OnlyAuthoringExecutionGenerationStore(tmp_path / "generations")
    path = store.commit(generation)
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_MISMATCH"):
        only_compose_authoring_research_worker(
            generation=generation,
            generation_store=store,
            private_asset_revisions=revisions,
            user_data_root=tmp_path / "data",
            postgres_dsn="postgresql://must-not-be-opened.invalid/onlyalpha",
            policy=OnlyResearchExecutionPolicy(
                lease_duration=timedelta(seconds=2),
                heartbeat_interval=timedelta(seconds=1),
            ),
            now_utc=lambda: datetime(2026, 9, 4, tzinfo=UTC),
            runtime_generations=object(),  # type: ignore[arg-type]
            process_generation_fingerprint="f" * 64,
        )


def test_factory_rejects_wrong_provider_version_layer_and_l4_execution() -> None:
    generation, revisions = _generation()
    reference = OnlyPrivateAssetRevisionReferenceV1(
        OnlyPrivateAssetKind.L3_FACTOR,
        generation.provenance.private_asset_id,
        generation.provenance.private_asset_revision_fingerprint,
    )
    with pytest.raises(ValueError, match="AUTHORING_CANDIDATE_PROVIDER_VERSION_MISMATCH"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=reference,
            private_asset_revisions=revisions,
            candidate_provider_id=generation.provenance.candidate_provider_id,
            candidate_provider_version="wrong",
            catalog=generation.catalog,
        )

    installed = only_discover_quant_asset_providers()
    non_factor = next(item for item in installed.providers if item.manifest.layer is not OnlyQuantAssetLayer.FACTOR)
    with pytest.raises(ValueError, match="AUTHORING_CANDIDATE_PROVIDER_LAYER_MISMATCH"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=reference,
            private_asset_revisions=revisions,
            candidate_provider_id=non_factor.manifest.provider_id,
            candidate_provider_version=non_factor.manifest.provider_version,
            catalog=installed,
        )

    l4 = OnlyPrivateL4Revision.from_draft(
        OnlyPrivateL4Draft(
            strategy_id="private.strategy.momentum",
            semantic_version="1",
            definition={"schema_version": 1},
        )
    )
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_PRIVATE_ASSET_KIND_UNSUPPORTED"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.L4_STRATEGY, l4.strategy_id, l4.revision_fingerprint
            ),
            private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(_Revisions(_l3_revision(), l4)),
            candidate_provider_id=generation.provenance.candidate_provider_id,
            candidate_provider_version=generation.provenance.candidate_provider_version,
            catalog=generation.catalog,
        )


def test_verified_reader_rejects_self_consistent_descriptor_not_backed_by_revision(tmp_path: Path) -> None:
    generation, revisions = _generation()
    identity = generation.provenance.identity_dict()
    identity["private_asset_content_fingerprint"] = "f" * 64
    identity["private_asset_kind"] = OnlyPrivateAssetKind.L3_FACTOR
    identity.pop("execution_generation_fingerprint")
    forged = OnlyResearchAuthoringProvenance(
        **identity,  # type: ignore[arg-type]
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(
            **{key: value for key, value in identity.items() if key != "schema_version"}  # type: ignore[arg-type]
        ),
    )
    descriptor = generation.descriptor()
    descriptor["execution_generation_fingerprint"] = forged.execution_generation_fingerprint
    descriptor["provenance"] = forged.to_dict()
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{forged.execution_generation_fingerprint}.json"
    path.write_text(only_canonical_json(descriptor) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_BINDING_MISMATCH"):
        OnlyVerifiedAuthoringGenerationReader(store, revisions).load_verified(forged.execution_generation_fingerprint)

    missing = OnlyPrivateAssetRevisionBindingResolver(
        _Revisions(
            OnlyPrivateL3Revision.from_draft(
                OnlyPrivateL3Draft(
                    factor_id="private.factor.other",
                    semantic_version="1",
                    source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
                    l3_api_version=1,
                    l3_api_contract_fingerprint="a" * 64,
                    input_contract={},
                    parameter_contract={},
                    output_contract={},
                    description="",
                    economic_rationale="",
                    category="other",
                )
            )
        )
    )
    original_store = OnlyAuthoringExecutionGenerationStore(tmp_path / "original")
    original_store.commit(generation)
    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"):
        OnlyVerifiedAuthoringGenerationReader(original_store, missing).load_verified(generation.fingerprint)
