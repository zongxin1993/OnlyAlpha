from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
)
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationBuilder

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind, OnlyCalculationReference
from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres import OnlyPostgresPrivateAssetStore, OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_FACTOR_API_V1,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetExampleImporterV1,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetParentMismatchError,
    OnlyPrivateAssetPutDisposition,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateAssetStaleBaseError,
    OnlyPrivateFactorAsset,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDraft,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_discover_quant_asset_providers,
    only_load_private_asset_example_bundle,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeProviderBinding,
)
from tests.research.specification.support import registry, specification
from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _factor(factor_id: str = "private.factor.momentum", **changes: object) -> OnlyPrivateFactorDraft:
    values: dict[str, object] = {
        "factor_id": factor_id,
        "semantic_version": "1",
        "source_text": 'def calculate(api, inputs, parameters):\n    return {"value": inputs["close"]}\n',
        "factor_api_version": 1,
        "factor_api_contract_fingerprint": ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("trend",),
    }
    values.update(changes)
    return OnlyPrivateFactorDraft(**values)  # type: ignore[arg-type]


def _strategy(**changes: object) -> OnlyPrivateStrategyDraft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.momentum",
        "semantic_version": "1",
        "definition": {"schema_version": 1, "entry": {"factor": "private.factor.momentum@1"}},
        "description": "Momentum strategy",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateStrategyDraft(**values)  # type: ignore[arg-type]


def _provenance() -> OnlyResearchAuthoringProvenance:
    values = {
        "experiment_id": "exp-" + "b" * 32,
        "private_asset_kind": OnlyPrivateAssetKind.FACTOR,
        "private_asset_id": "private.factor.momentum",
        "private_asset_revision_fingerprint": "5" * 64,
        "private_asset_content_fingerprint": "6" * 64,
        "candidate_provider_id": "candidate.private.factor",
        "candidate_provider_version": "7",
        "candidate_provider_content_fingerprint": "8" * 64,
        "catalog_generation_fingerprint": "9" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        schema_version=1,
        **values,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**values),
    )


def test_private_factor_strategy_authoring_round_trip_publish_and_history(postgres_dsn: str) -> None:
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate()[-1] == "0029_private_factor_strategy_vocabulary"
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)

    factor_asset = OnlyPrivateFactorAsset("private.factor.momentum")
    assert store.put_factor_asset(factor_asset) is OnlyPrivateAssetPutDisposition.CREATED
    assert store.put_factor_asset(factor_asset) is OnlyPrivateAssetPutDisposition.REUSED
    assert store.load_factor_asset(factor_asset.factor_id) == factor_asset
    store.save_factor_draft(_factor())
    assert store.load_factor_draft(factor_asset.factor_id) == _factor()
    updated_factor = _factor(description="Edited")
    store.save_factor_draft(updated_factor)
    assert store.load_factor_draft(factor_asset.factor_id) == updated_factor
    store.save_factor_draft(_factor())
    disposition, factor_r1 = store.publish_factor_revision(factor_asset.factor_id)
    assert disposition is OnlyPrivateAssetPutDisposition.CREATED
    assert store.publish_factor_revision(factor_asset.factor_id) == (OnlyPrivateAssetPutDisposition.REUSED, factor_r1)
    assert store.load_factor_revision(factor_asset.factor_id, factor_r1.revision_fingerprint) == factor_r1

    factor_r2_draft = _factor(
        base_revision_fingerprint=factor_r1.revision_fingerprint,
        source_text=_factor().source_text + "# revision 2\n",
    )
    store.save_factor_draft(factor_r2_draft)
    _, factor_r2 = store.publish_factor_revision(factor_asset.factor_id)
    assert store.list_factor_revision_history(factor_asset.factor_id) == (factor_r1, factor_r2)

    strategy_asset = OnlyPrivateStrategyAsset("private.strategy.momentum")
    store.put_strategy_asset(strategy_asset)
    store.save_strategy_draft(_strategy())
    assert store.clear_strategy_draft(strategy_asset.strategy_id)
    assert not store.clear_strategy_draft(strategy_asset.strategy_id)
    assert store.load_strategy_draft(strategy_asset.strategy_id) is None
    store.save_strategy_draft(_strategy())
    _, strategy_r1 = store.publish_strategy_revision(strategy_asset.strategy_id)
    assert store.load_strategy_draft(strategy_asset.strategy_id) == _strategy()
    assert store.load_strategy_revision(strategy_asset.strategy_id, strategy_r1.revision_fingerprint) == strategy_r1
    assert store.list_strategy_revision_history(strategy_asset.strategy_id) == (strategy_r1,)


def test_private_example_seed_import_is_idempotent_and_binds_exact_factor_revision(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    importer = OnlyPrivateAssetExampleImporterV1(OnlyPostgresPrivateAssetStore(postgres_dsn))
    bundles = (
        only_load_private_asset_example_bundle(Path("examples/private-assets/factor/simple_momentum")),
        only_load_private_asset_example_bundle(Path("examples/private-assets/strategy/simple_momentum")),
    )

    first = importer.import_bundles(bundles)
    second = importer.import_bundles(reversed(bundles))

    assert first == second
    factor = first["factor.simple_momentum"]
    strategy = OnlyPostgresPrivateAssetStore(postgres_dsn).load_strategy_revision(
        first["strategy.simple_momentum"].private_asset_id,
        first["strategy.simple_momentum"].private_asset_revision_fingerprint,
    )
    assert strategy.definition["factor_revision_dependencies"] == (
        {
            "example_id": "factor.simple_momentum",
            "factor_id": factor.private_asset_id,
            "revision_fingerprint": factor.private_asset_revision_fingerprint,
        },
    )


def test_factor_seed_reaches_native_runtime_and_historical_rebuild_without_database(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresPrivateAssetStore(postgres_dsn)
    imported = OnlyPrivateAssetExampleImporterV1(authority).import_bundles(
        (
            only_load_private_asset_example_bundle(Path("examples/private-assets/factor/simple_momentum")),
            only_load_private_asset_example_bundle(Path("examples/private-assets/strategy/simple_momentum")),
        )
    )
    factor_ref = imported["factor.simple_momentum"]
    factor = authority.load_factor_revision(
        factor_ref.private_asset_id,
        factor_ref.private_asset_revision_fingerprint,
    )
    strategy_ref = imported["strategy.simple_momentum"]
    strategy = authority.load_strategy_revision(
        strategy_ref.private_asset_id,
        strategy_ref.private_asset_revision_fingerprint,
    )
    assert strategy.revision_fingerprint == strategy_ref.private_asset_revision_fingerprint

    closure = OnlyPrivateFactorExecutableClosureV1.create(
        factor,
        ({"close": Decimal("2"), "previous_close": Decimal("1")},),
        {},
        host=OnlyPrivateFactorIsolatedProgramHost(3),
    )
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.example.factor",
            factor.revision_fingerprint,
            OnlyQuantAssetKind.FACTOR,
            OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_factor_snapshot=closure.provider_snapshot,
    )

    def execute(candidate: OnlyQuantAssetProvider) -> None:
        calculation_registry = OnlyQuantAssetCatalogGeneration((candidate,)).calculation_registry()
        research = calculation_registry.resolve(
            OnlyCalculationKind.FACTOR,
            factor.factor_id,
            factor.semantic_version,
            OnlyCalculationBackendKind.RESEARCH,
        )
        assert research.definition_resolver is not None
        definition = research.definition_resolver.resolve(
            {},
            {
                "close": OnlyCalculationReference(None, "close", "close"),
                "previous_close": OnlyCalculationReference(None, "previous_close", "previous_close"),
            },
        )
        assert research.provider.execute(
            definition,
            {
                "close": pa.array([Decimal("2")], type=pa.decimal128(38, 12)),
                "previous_close": pa.array([Decimal("1")], type=pa.decimal128(38, 12)),
            },
        )["value"].to_pylist() == [Decimal("1.000000000000")]
        trading = calculation_registry.resolve(
            OnlyCalculationKind.FACTOR,
            factor.factor_id,
            factor.semantic_version,
            OnlyCalculationBackendKind.TRADING,
        )
        assert trading.provider.create(definition, object()).update(
            {"close": Decimal("2"), "previous_close": Decimal("1")}
        ) == {"value": Decimal("1")}

    execute(provider)
    core_bytes = b"exact-core-artifact"
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name="onlyalpha-0.9.9-py3-none-any.whl",
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", core_artifact.artifact_sha256)
    base_provider = only_discover_quant_asset_providers().providers[0]
    provider_bytes = b"exact-provider-artifact"
    provider_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-test-provider",
        source_revision="2" * 40,
        artifact_logical_name=(
            f"{base_provider.manifest.distribution_name.replace('-', '_')}-"
            f"{base_provider.manifest.distribution_version}-py3-none-any.whl"
        ),
        artifact_bytes=provider_bytes,
        tested_core_execution_fingerprint=core_identity.fingerprint,
        provider=base_provider,
    )
    artifact_store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    artifact_store.put_once(core_artifact, core_bytes)
    artifact_store.put_once(provider_artifact, provider_bytes)
    base_catalog = OnlyQuantAssetCatalogGeneration((base_provider,))
    base_manifest = OnlyRuntimeGenerationManifest(
        core_identity,
        (core_artifact.manifest_fingerprint, provider_artifact.manifest_fingerprint),
        (core_artifact.artifact_sha256, provider_artifact.artifact_sha256),
        (
            OnlyRuntimeProviderBinding(
                base_provider.manifest.provider_id,
                base_provider.manifest.provider_version,
                base_provider.content_fingerprint,
                provider_artifact.artifact_sha256,
            ),
        ),
        base_catalog.generation_fingerprint,
        provider_artifact.implementations,
    )
    builder = OnlyRuntimeGenerationBuilder(artifact_store, Path(sys.executable))
    catalog = OnlyQuantAssetCatalogGeneration((base_provider, provider))
    runtime_manifest = builder.bind_private_factor_closure(
        base_manifest=base_manifest,
        expected_catalog=catalog,
        closure=closure,
    )
    assert authority.clear_factor_draft(factor.factor_id)

    def database_forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("HISTORICAL_RUNTIME_DATABASE_LOOKUP_FORBIDDEN")

    monkeypatch.setattr(OnlyPostgresPrivateAssetStore, "load_factor_revision", database_forbidden)
    rebuilt = builder.rebuild_private_factor_providers(runtime_manifest)[0]
    assert OnlyQuantAssetCatalogGeneration((base_provider, rebuilt)).descriptor() == catalog.descriptor()
    execute(rebuilt)


def test_publication_fails_closed_on_stale_parent_and_asset_mismatch(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    for factor_id in ("private.factor.one", "private.factor.two"):
        store.put_factor_asset(OnlyPrivateFactorAsset(factor_id))
        store.save_factor_draft(_factor(factor_id))
    _, one_r1 = store.publish_factor_revision("private.factor.one")
    _, two_r1 = store.publish_factor_revision("private.factor.two")

    with pytest.raises(OnlyPrivateAssetNotFoundError):
        store.load_factor_revision("private.factor.two", one_r1.revision_fingerprint)
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_factor_draft(_factor("private.factor.one", base_revision_fingerprint=two_r1.revision_fingerprint))
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_factor_draft(_factor("private.factor.one", base_revision_fingerprint="f" * 64))

    stale = _factor(
        "private.factor.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_factor().source_text + "# stale\n",
    )
    current = _factor(
        "private.factor.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_factor().source_text + "# current\n",
    )
    store.save_factor_draft(current)
    store.publish_factor_revision("private.factor.one")
    store.save_factor_draft(stale)
    with pytest.raises(OnlyPrivateAssetStaleBaseError):
        store.publish_factor_revision("private.factor.one")


def test_exact_load_detects_column_and_payload_corruption(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    store.put_factor_asset(OnlyPrivateFactorAsset("private.factor.momentum"))
    store.save_factor_draft(_factor())
    _, revision = store.publish_factor_revision("private.factor.momentum")

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE private_factor_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute("TRUNCATE private_factor_revision CASCADE")

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_factor_revision DISABLE TRIGGER private_factor_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_factor_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
        connection.execute(
            "ALTER TABLE private_factor_revision ENABLE TRIGGER private_factor_revision_immutable_trigger"
        )
    with pytest.raises(OnlyPrivateAssetCorruptError):
        store.load_factor_revision("private.factor.momentum", revision.revision_fingerprint)

    store.put_strategy_asset(OnlyPrivateStrategyAsset("private.strategy.momentum"))
    store.save_strategy_draft(_strategy())
    _, strategy_revision = store.publish_strategy_revision("private.strategy.momentum")
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE private_strategy_revision SET definition_fingerprint = %s WHERE revision_fingerprint = %s",
            ("d" * 64, strategy_revision.revision_fingerprint),
        )

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_strategy_revision DISABLE TRIGGER private_strategy_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_strategy_revision SET definition_fingerprint = %s WHERE revision_fingerprint = %s",
            ("d" * 64, strategy_revision.revision_fingerprint),
        )
        connection.execute(
            "ALTER TABLE private_strategy_revision ENABLE TRIGGER private_strategy_revision_immutable_trigger"
        )
    with pytest.raises(OnlyPrivateAssetCorruptError):
        store.load_strategy_revision("private.strategy.momentum", strategy_revision.revision_fingerprint)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "DELETE FROM private_strategy_revision WHERE revision_fingerprint = %s",
            (strategy_revision.revision_fingerprint,),
        )


def test_research_run_db_native_provenance_survives_postgres_round_trip(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    spec = specification()
    run = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000427"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(
            OnlyResearchSpecificationResolver(registry()).resolve(spec)
        ),
        queued_at=datetime(2026, 9, 17, tzinfo=UTC),
        authoring_provenance=_provenance(),
    )
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)

    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run


def test_generation_descriptor_reanchors_to_revision_and_fails_after_authority_removal(
    postgres_dsn: str, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    private_assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
    private_assets.put_factor_asset(OnlyPrivateFactorAsset("private.factor.momentum"))
    private_assets.save_factor_draft(_factor())
    _, revision = private_assets.publish_factor_revision("private.factor.momentum")
    catalog = only_discover_quant_asset_providers()
    bindings = OnlyPrivateAssetRevisionBindingResolver(private_assets)
    generation = OnlyAuthoringExecutionGeneration.create_verified(
        experiment_id="exp-" + "d" * 32,
        private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.FACTOR, revision.factor_id, revision.revision_fingerprint
        ),
        private_asset_revisions=bindings,
        private_factor_executable_closure=OnlyPrivateFactorExecutableClosureV1.create(
            revision, ({"close": Decimal("1")},), {"window": 1}
        ),
        candidate_provider_id="candidate.private.factor",
        base_catalog=catalog,
    )
    descriptor_store = OnlyAuthoringExecutionGenerationStore(tmp_path / "authoring-generations")
    descriptor_store.commit(generation)
    reader = OnlyVerifiedAuthoringGenerationReader(descriptor_store, bindings)
    assert reader.load_verified(generation.fingerprint) == generation.provenance

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_factor_revision DISABLE TRIGGER private_factor_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_factor_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
        connection.execute(
            "ALTER TABLE private_factor_revision ENABLE TRIGGER private_factor_revision_immutable_trigger"
        )

    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_CORRUPT"):
        reader.load_verified(generation.fingerprint)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE private_factor_asset SET current_revision_fingerprint = NULL WHERE factor_id = %s",
            (revision.factor_id,),
        )
        connection.execute(
            "ALTER TABLE private_factor_revision DISABLE TRIGGER private_factor_revision_immutable_trigger"
        )
        connection.execute(
            "DELETE FROM private_factor_revision WHERE revision_fingerprint = %s",
            (revision.revision_fingerprint,),
        )
        connection.execute(
            "ALTER TABLE private_factor_revision ENABLE TRIGGER private_factor_revision_immutable_trigger"
        )

    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"):
        reader.load_verified(generation.fingerprint)
