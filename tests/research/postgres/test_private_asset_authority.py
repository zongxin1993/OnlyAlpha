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
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaAsset,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaIsolatedProgramHost,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetExampleImporterV1,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetParentMismatchError,
    OnlyPrivateAssetPutDisposition,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateAssetStaleBaseError,
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


def _alpha(alpha_id: str = "private.alpha.momentum", **changes: object) -> OnlyPrivateAlphaDraft:
    values: dict[str, object] = {
        "alpha_id": alpha_id,
        "semantic_version": "1",
        "source_text": 'def calculate(api, inputs, parameters):\n    return {"value": inputs["close"]}\n',
        "alpha_api_version": 1,
        "alpha_api_contract_fingerprint": ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("trend",),
    }
    values.update(changes)
    return OnlyPrivateAlphaDraft(**values)  # type: ignore[arg-type]


def _strategy(**changes: object) -> OnlyPrivateStrategyDraft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.momentum",
        "semantic_version": "1",
        "definition": {"schema_version": 1, "entry": {"factor": "private.alpha.momentum@1"}},
        "description": "Momentum strategy",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateStrategyDraft(**values)  # type: ignore[arg-type]


def _provenance() -> OnlyResearchAuthoringProvenance:
    values = {
        "experiment_id": "exp-" + "b" * 32,
        "private_asset_kind": OnlyPrivateAssetKind.ALPHA,
        "private_asset_id": "private.alpha.momentum",
        "private_asset_revision_fingerprint": "5" * 64,
        "private_asset_content_fingerprint": "6" * 64,
        "candidate_provider_id": "candidate.private.alpha",
        "candidate_provider_version": "7",
        "candidate_provider_content_fingerprint": "8" * 64,
        "catalog_generation_fingerprint": "9" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        schema_version=1,
        **values,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**values),
    )


def test_private_alpha_strategy_authoring_round_trip_publish_and_history(postgres_dsn: str) -> None:
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate()[-1] == "0028_private_alpha_strategy_vocabulary"
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)

    alpha_asset = OnlyPrivateAlphaAsset("private.alpha.momentum")
    assert store.put_alpha_asset(alpha_asset) is OnlyPrivateAssetPutDisposition.CREATED
    assert store.put_alpha_asset(alpha_asset) is OnlyPrivateAssetPutDisposition.REUSED
    assert store.load_alpha_asset(alpha_asset.alpha_id) == alpha_asset
    store.save_alpha_draft(_alpha())
    assert store.load_alpha_draft(alpha_asset.alpha_id) == _alpha()
    updated_alpha = _alpha(description="Edited")
    store.save_alpha_draft(updated_alpha)
    assert store.load_alpha_draft(alpha_asset.alpha_id) == updated_alpha
    store.save_alpha_draft(_alpha())
    disposition, alpha_r1 = store.publish_alpha_revision(alpha_asset.alpha_id)
    assert disposition is OnlyPrivateAssetPutDisposition.CREATED
    assert store.publish_alpha_revision(alpha_asset.alpha_id) == (OnlyPrivateAssetPutDisposition.REUSED, alpha_r1)
    assert store.load_alpha_revision(alpha_asset.alpha_id, alpha_r1.revision_fingerprint) == alpha_r1

    alpha_r2_draft = _alpha(
        base_revision_fingerprint=alpha_r1.revision_fingerprint,
        source_text=_alpha().source_text + "# revision 2\n",
    )
    store.save_alpha_draft(alpha_r2_draft)
    _, alpha_r2 = store.publish_alpha_revision(alpha_asset.alpha_id)
    assert store.list_alpha_revision_history(alpha_asset.alpha_id) == (alpha_r1, alpha_r2)

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


def test_private_example_seed_import_is_idempotent_and_binds_exact_alpha_revision(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    importer = OnlyPrivateAssetExampleImporterV1(OnlyPostgresPrivateAssetStore(postgres_dsn))
    bundles = (
        only_load_private_asset_example_bundle(Path("examples/private-assets/alpha/simple_momentum")),
        only_load_private_asset_example_bundle(Path("examples/private-assets/strategy/simple_momentum")),
    )

    first = importer.import_bundles(bundles)
    second = importer.import_bundles(reversed(bundles))

    assert first == second
    alpha = first["alpha.simple_momentum"]
    strategy = OnlyPostgresPrivateAssetStore(postgres_dsn).load_strategy_revision(
        first["strategy.simple_momentum"].private_asset_id,
        first["strategy.simple_momentum"].private_asset_revision_fingerprint,
    )
    assert strategy.definition["alpha_revision_dependencies"] == (
        {
            "example_id": "alpha.simple_momentum",
            "alpha_id": alpha.private_asset_id,
            "revision_fingerprint": alpha.private_asset_revision_fingerprint,
        },
    )


def test_alpha_seed_reaches_native_runtime_and_historical_rebuild_without_database(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresPrivateAssetStore(postgres_dsn)
    imported = OnlyPrivateAssetExampleImporterV1(authority).import_bundles(
        (
            only_load_private_asset_example_bundle(Path("examples/private-assets/alpha/simple_momentum")),
            only_load_private_asset_example_bundle(Path("examples/private-assets/strategy/simple_momentum")),
        )
    )
    alpha_ref = imported["alpha.simple_momentum"]
    alpha = authority.load_alpha_revision(
        alpha_ref.private_asset_id,
        alpha_ref.private_asset_revision_fingerprint,
    )
    strategy_ref = imported["strategy.simple_momentum"]
    strategy = authority.load_strategy_revision(
        strategy_ref.private_asset_id,
        strategy_ref.private_asset_revision_fingerprint,
    )
    assert strategy.revision_fingerprint == strategy_ref.private_asset_revision_fingerprint

    closure = OnlyPrivateAlphaExecutableClosureV1.create(
        alpha,
        ({"close": Decimal("2"), "previous_close": Decimal("1")},),
        {},
        host=OnlyPrivateAlphaIsolatedProgramHost(3),
    )
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.example.alpha",
            alpha.revision_fingerprint,
            OnlyQuantAssetKind.ALPHA,
            OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_alpha_snapshot=closure.provider_snapshot,
    )

    def execute(candidate: OnlyQuantAssetProvider) -> None:
        calculation_registry = OnlyQuantAssetCatalogGeneration((candidate,)).calculation_registry()
        research = calculation_registry.resolve(
            OnlyCalculationKind.FACTOR,
            alpha.alpha_id,
            alpha.semantic_version,
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
            alpha.alpha_id,
            alpha.semantic_version,
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
    runtime_manifest = builder.bind_private_alpha_closure(
        base_manifest=base_manifest,
        expected_catalog=catalog,
        closure=closure,
    )
    assert authority.clear_alpha_draft(alpha.alpha_id)

    def database_forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("HISTORICAL_RUNTIME_DATABASE_LOOKUP_FORBIDDEN")

    monkeypatch.setattr(OnlyPostgresPrivateAssetStore, "load_alpha_revision", database_forbidden)
    rebuilt = builder.rebuild_private_alpha_providers(runtime_manifest)[0]
    assert OnlyQuantAssetCatalogGeneration((base_provider, rebuilt)).descriptor() == catalog.descriptor()
    execute(rebuilt)


def test_publication_fails_closed_on_stale_parent_and_asset_mismatch(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    for alpha_id in ("private.alpha.one", "private.alpha.two"):
        store.put_alpha_asset(OnlyPrivateAlphaAsset(alpha_id))
        store.save_alpha_draft(_alpha(alpha_id))
    _, one_r1 = store.publish_alpha_revision("private.alpha.one")
    _, two_r1 = store.publish_alpha_revision("private.alpha.two")

    with pytest.raises(OnlyPrivateAssetNotFoundError):
        store.load_alpha_revision("private.alpha.two", one_r1.revision_fingerprint)
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_alpha_draft(_alpha("private.alpha.one", base_revision_fingerprint=two_r1.revision_fingerprint))
    with pytest.raises(OnlyPrivateAssetParentMismatchError):
        store.save_alpha_draft(_alpha("private.alpha.one", base_revision_fingerprint="f" * 64))

    stale = _alpha(
        "private.alpha.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_alpha().source_text + "# stale\n",
    )
    current = _alpha(
        "private.alpha.one",
        base_revision_fingerprint=one_r1.revision_fingerprint,
        source_text=_alpha().source_text + "# current\n",
    )
    store.save_alpha_draft(current)
    store.publish_alpha_revision("private.alpha.one")
    store.save_alpha_draft(stale)
    with pytest.raises(OnlyPrivateAssetStaleBaseError):
        store.publish_alpha_revision("private.alpha.one")


def test_exact_load_detects_column_and_payload_corruption(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresPrivateAssetStore(postgres_dsn)
    store.put_alpha_asset(OnlyPrivateAlphaAsset("private.alpha.momentum"))
    store.save_alpha_draft(_alpha())
    _, revision = store.publish_alpha_revision("private.alpha.momentum")

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE private_alpha_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute("TRUNCATE private_alpha_revision CASCADE")

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_alpha_revision DISABLE TRIGGER private_alpha_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_alpha_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
        connection.execute("ALTER TABLE private_alpha_revision ENABLE TRIGGER private_alpha_revision_immutable_trigger")
    with pytest.raises(OnlyPrivateAssetCorruptError):
        store.load_alpha_revision("private.alpha.momentum", revision.revision_fingerprint)

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
    private_assets.put_alpha_asset(OnlyPrivateAlphaAsset("private.alpha.momentum"))
    private_assets.save_alpha_draft(_alpha())
    _, revision = private_assets.publish_alpha_revision("private.alpha.momentum")
    catalog = only_discover_quant_asset_providers()
    bindings = OnlyPrivateAssetRevisionBindingResolver(private_assets)
    generation = OnlyAuthoringExecutionGeneration.create_verified(
        experiment_id="exp-" + "d" * 32,
        private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.ALPHA, revision.alpha_id, revision.revision_fingerprint
        ),
        private_asset_revisions=bindings,
        private_alpha_executable_closure=OnlyPrivateAlphaExecutableClosureV1.create(
            revision, ({"close": Decimal("1")},), {"window": 1}
        ),
        candidate_provider_id="candidate.private.alpha",
        base_catalog=catalog,
    )
    descriptor_store = OnlyAuthoringExecutionGenerationStore(tmp_path / "authoring-generations")
    descriptor_store.commit(generation)
    reader = OnlyVerifiedAuthoringGenerationReader(descriptor_store, bindings)
    assert reader.load_verified(generation.fingerprint) == generation.provenance

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_alpha_revision DISABLE TRIGGER private_alpha_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_alpha_revision SET source_sha256 = %s WHERE revision_fingerprint = %s",
            ("f" * 64, revision.revision_fingerprint),
        )
        connection.execute("ALTER TABLE private_alpha_revision ENABLE TRIGGER private_alpha_revision_immutable_trigger")

    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_CORRUPT"):
        reader.load_verified(generation.fingerprint)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE private_alpha_asset SET current_revision_fingerprint = NULL WHERE alpha_id = %s",
            (revision.alpha_id,),
        )
        connection.execute(
            "ALTER TABLE private_alpha_revision DISABLE TRIGGER private_alpha_revision_immutable_trigger"
        )
        connection.execute(
            "DELETE FROM private_alpha_revision WHERE revision_fingerprint = %s",
            (revision.revision_fingerprint,),
        )
        connection.execute("ALTER TABLE private_alpha_revision ENABLE TRIGGER private_alpha_revision_immutable_trigger")

    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"):
        reader.load_verified(generation.fingerprint)
