from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationRegistry,
    OnlyAuthoringExecutionGenerationStore,
    only_compose_authoring_research_worker,
)
from onlyalpha_example_alpha.provider import quant_asset_provider

from onlyalpha.quant_assets import (
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


def _generation() -> OnlyAuthoringExecutionGeneration:
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
    identity = {
        "experiment_id": experiment_id,
        "source_repository": "OnlyAlpha-example-alpha",
        "source_revision": revision,
        "source_tree": "2" * 40,
        "candidate_provider_id": candidate.manifest.provider_id,
        "candidate_provider_version": candidate.manifest.provider_version,
        "candidate_provider_content_fingerprint": candidate.content_fingerprint,
        "catalog_generation_fingerprint": catalog.generation_fingerprint,
    }
    provenance = OnlyResearchAuthoringProvenance(
        schema_version=1,
        **identity,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**identity),
    )
    return OnlyAuthoringExecutionGeneration(provenance, catalog)


def test_generation_owns_exact_catalog_and_process_composition(tmp_path: Path) -> None:
    generation = _generation()
    services = generation.engine_services()
    definitions = services.assembler.components.calculations.type_definitions()
    assert any(item.type_id == "example.factor.momentum" for item in definitions)
    assert any(item.type_id == "onlyalpha.target.forward_return" for item in definitions)
    resolution = OnlyAuthoringExecutionGenerationRegistry((generation,)).resolve(
        generation.provenance,
        specification(),
    )
    assert resolution.specification_fingerprint == specification().specification_fingerprint
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    assert store.commit(generation) == store.commit(generation)
    assert store.verify(generation).is_file()


def test_generation_fails_closed_on_catalog_or_durable_descriptor_drift(tmp_path: Path) -> None:
    generation = _generation()
    with pytest.raises(ValueError, match="AUTHORING_CATALOG_GENERATION_MISMATCH"):
        OnlyAuthoringExecutionGeneration(
            generation.provenance,
            OnlyQuantAssetCatalogGeneration(()),
        )
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    path = store.commit(generation)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_MISMATCH"):
        store.verify(generation)
    with pytest.raises(ValueError, match="AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION"):
        OnlyAuthoringExecutionGenerationRegistry(())
    with pytest.raises(ValueError, match="AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION"):
        OnlyAuthoringExecutionGenerationRegistry((generation, generation))


def test_worker_composition_verifies_descriptor_before_postgres_claim_capability(tmp_path: Path) -> None:
    generation = _generation()
    store = OnlyAuthoringExecutionGenerationStore(tmp_path / "generations")
    path = store.commit(generation)
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_MISMATCH"):
        only_compose_authoring_research_worker(
            generation=generation,
            generation_store=store,
            user_data_root=tmp_path / "data",
            postgres_dsn="postgresql://must-not-be-opened.invalid/onlyalpha",
            policy=OnlyResearchExecutionPolicy(
                lease_duration=timedelta(seconds=2),
                heartbeat_interval=timedelta(seconds=1),
            ),
            now_utc=lambda: datetime(2026, 9, 4, tzinfo=UTC),
        )
