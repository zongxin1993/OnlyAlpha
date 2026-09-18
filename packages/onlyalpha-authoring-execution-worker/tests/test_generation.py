from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationRegistry,
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
    only_compose_authoring_research_admission,
    only_compose_authoring_research_worker,
)

from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
    OnlyQuantAssetCatalogGeneration,
    only_discover_quant_asset_providers,
)
from onlyalpha.research import (
    OnlyResearchCalculationSpec,
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsSpec,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from onlyalpha.research.execution import OnlyResearchExecutionPolicy
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run import OnlyResearchRunAdmissionError, OnlyResearchRunId
from tests.research.specification.support import specification


class _Revisions:
    def __init__(self, alpha: OnlyPrivateAlphaRevision, strategy: OnlyPrivateStrategyRevision | None = None) -> None:
        self.alpha = alpha
        self.strategy = strategy

    def load_alpha_revision(self, alpha_id: str, fingerprint: str) -> OnlyPrivateAlphaRevision:
        if (alpha_id, fingerprint) != (self.alpha.alpha_id, self.alpha.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.alpha

    def load_strategy_revision(self, strategy_id: str, fingerprint: str) -> OnlyPrivateStrategyRevision:
        if self.strategy is None or (strategy_id, fingerprint) != (
            self.strategy.strategy_id,
            self.strategy.revision_fingerprint,
        ):
            raise OnlyPrivateAssetNotFoundError()
        return self.strategy


def _alpha_revision(alpha_id: str = "private.alpha.momentum") -> OnlyPrivateAlphaRevision:
    return OnlyPrivateAlphaRevision.from_draft(
        OnlyPrivateAlphaDraft(
            alpha_id=alpha_id,
            semantic_version="1",
            source_text=(
                "def calculate(api, inputs, parameters):\n"
                "    return {'factor_value': api.sub(inputs['value'], parameters['offset'])}\n"
            ),
            alpha_api_version=1,
            alpha_api_contract_fingerprint=ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
            input_contract={"value": {"type": "DECIMAL", "nullable": True}},
            parameter_contract={"offset": {"type": "DECIMAL"}},
            output_contract={"factor_value": {"type": "DECIMAL", "nullable": True}},
            description="Momentum",
            economic_rationale="Trend",
            category="momentum",
        )
    )


def _closure(revision: OnlyPrivateAlphaRevision | None = None) -> OnlyPrivateAlphaExecutableClosureV1:
    return OnlyPrivateAlphaExecutableClosureV1.create(
        revision or _alpha_revision(), ({"value": Decimal("1")},), {"offset": Decimal("0")}
    )


def _forged_closure(source: OnlyPrivateAlphaExecutableClosureV1) -> OnlyPrivateAlphaExecutableClosureV1:
    forged = object.__new__(OnlyPrivateAlphaExecutableClosureV1)
    for name in source.__dataclass_fields__:
        value = getattr(source, name)
        if name == "equivalence_evidence":
            value = replace(
                value,
                research_output_fingerprint="f" * 64,
                trading_output_fingerprint="f" * 64,
            )
        object.__setattr__(forged, name, value)
    return forged


def test_authoring_rejects_reflection_forged_executable_closure() -> None:
    revision = _alpha_revision()
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_EXECUTABLE_CLOSURE_MISMATCH"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id="exp-" + "f" * 32,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.ALPHA, revision.alpha_id, revision.revision_fingerprint
            ),
            private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(_Revisions(revision)),
            private_alpha_executable_closure=_forged_closure(_closure(revision)),
            candidate_provider_id="candidate.private.alpha.forged",
            base_catalog=only_discover_quant_asset_providers(),
        )


def _native_specification() -> OnlyResearchSpecification:
    base = specification()
    factor = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "native",
                OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "private.alpha.momentum", "1"),
                {"offset": Decimal("0")},
                (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(None, "value", "bar.close")),),
            ),
        )
    )
    return OnlyResearchSpecification(
        "a" * 64,
        (OnlyResearchCalculationSpec("feature", factor), base.calculations[1]),
        (
            OnlyResearchStatisticsSpec(
                OnlyResearchSeriesSelector("feature", "native", "factor_value"),
                OnlyResearchSeriesSelector("target", "forward_return", "target_value"),
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
    )


def _generation() -> tuple[OnlyAuthoringExecutionGeneration, OnlyPrivateAssetRevisionBindingResolver]:
    experiment_id = "exp-" + "a" * 32
    revision = _alpha_revision()
    closure = _closure(revision)
    installed = only_discover_quant_asset_providers()
    revisions = OnlyPrivateAssetRevisionBindingResolver(_Revisions(revision))
    return (
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.ALPHA, revision.alpha_id, revision.revision_fingerprint
            ),
            private_asset_revisions=revisions,
            private_alpha_executable_closure=closure,
            candidate_provider_id=f"candidate.private.alpha.{experiment_id.removeprefix('exp-')}",
            base_catalog=installed,
        ),
        revisions,
    )


def test_generation_owns_exact_catalog_and_process_composition(tmp_path: Path) -> None:
    generation, revisions = _generation()
    services = generation.engine_services()
    definitions = services.assembler.components.calculations.type_definitions()
    assert any(item.type_id == "private.alpha.momentum" for item in definitions)
    assert any(item.type_id == "onlyalpha.target.forward_return" for item in definitions)
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    assert store.commit(generation) == store.commit(generation)
    reader = OnlyVerifiedAuthoringGenerationReader(store, revisions)
    resolution = OnlyAuthoringExecutionGenerationRegistry((generation,), reader).resolve(
        generation.fingerprint, _native_specification()
    )
    assert resolution.specification_fingerprint == _native_specification().specification_fingerprint
    assert store.verify(generation).is_file()
    assert only_canonical_json(store.load_descriptor_verified(generation.fingerprint)) == only_canonical_json(
        generation.descriptor()
    )
    assert reader.load_verified(generation.fingerprint) == generation.provenance
    assert only_canonical_json(reader.load_descriptor_verified(generation.fingerprint)) == only_canonical_json(
        generation.descriptor()
    )
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT"):
        store.load_descriptor_verified("0" * 64)


def test_generation_fails_closed_on_catalog_or_durable_descriptor_drift(tmp_path: Path) -> None:
    generation, revisions = _generation()
    with pytest.raises(ValueError, match="AUTHORING_CANDIDATE_PROVIDER_DUPLICATE"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.ALPHA,
                generation.provenance.private_asset_id,
                generation.provenance.private_asset_revision_fingerprint,
            ),
            private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(_Revisions(_alpha_revision())),
            private_alpha_executable_closure=_closure(),
            candidate_provider_id=generation.provenance.candidate_provider_id,
            base_catalog=generation.catalog,
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
    identity["private_asset_kind"] = OnlyPrivateAssetKind.ALPHA
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
    authority = _Revisions(_alpha_revision())
    revisions = OnlyPrivateAssetRevisionBindingResolver(authority)
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    store.commit(generation)
    registry = OnlyAuthoringExecutionGenerationRegistry(
        (generation,), OnlyVerifiedAuthoringGenerationReader(store, revisions)
    )
    assert registry.load_verified(generation.fingerprint) == generation.provenance

    authority.alpha = OnlyPrivateAlphaRevision.from_draft(
        OnlyPrivateAlphaDraft(
            alpha_id="private.alpha.other",
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
            alpha_api_version=1,
            alpha_api_contract_fingerprint="a" * 64,
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
    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"):
        OnlyVerifiedAuthoringGenerationReader(store, revisions).load_descriptor_verified(generation.fingerprint)


def test_authoring_admission_composition_uses_exact_generation_resolver(tmp_path: Path) -> None:
    generation, revisions = _generation()
    store = OnlyAuthoringExecutionGenerationStore(tmp_path)
    store.commit(generation)

    class _DefaultResolverTrap:
        def resolve(self, _specification: object) -> object:
            raise AssertionError("default resolver must not resolve authoring work")

    class _DatasetStore:
        def load_verified_table(self, _fingerprint: str) -> object:
            return object()

    service = only_compose_authoring_research_admission(
        generation=generation,
        generation_store=store,
        private_asset_revisions=revisions,
        default_resolver=_DefaultResolverTrap(),  # type: ignore[arg-type]
        dataset_store=_DatasetStore(),  # type: ignore[arg-type]
        now_utc=lambda: datetime(2026, 9, 18, tzinfo=UTC),
        run_id_factory=lambda: OnlyResearchRunId("00000000-0000-4000-8000-000000000116"),
    )

    run = service.prepare(_native_specification(), authoring_generation_fingerprint=generation.fingerprint)

    assert run.authoring_provenance == generation.provenance
    assert run.authoring_generation_fingerprint == generation.fingerprint

    with pytest.raises(OnlyResearchRunAdmissionError) as caught:
        service.prepare(_native_specification(), authoring_generation_fingerprint="0" * 64)
    assert caught.value.code == "RESEARCH_EXECUTION_GENERATION_UNAVAILABLE"


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


def test_worker_composition_resolves_native_revision_registration(tmp_path: Path) -> None:
    generation, revisions = _generation()
    store = OnlyAuthoringExecutionGenerationStore(tmp_path / "generations")
    store.commit(generation)
    composition = only_compose_authoring_research_worker(
        generation=generation,
        generation_store=store,
        private_asset_revisions=revisions,
        user_data_root=tmp_path / "data",
        postgres_dsn="postgresql://not-opened.invalid/onlyalpha",
        policy=OnlyResearchExecutionPolicy(
            lease_duration=timedelta(seconds=60),
            heartbeat_interval=timedelta(seconds=30),
        ),
        now_utc=lambda: datetime(2026, 9, 18, tzinfo=UTC),
        runtime_generations=object(),  # type: ignore[arg-type]
        process_generation_fingerprint="f" * 64,
    )

    resolution = composition.resolver.resolve(_native_specification())
    assert any(
        node.definition.type_id == "private.alpha.momentum"
        for candidate in resolution.candidates
        for node in candidate.graph.nodes
    )


def test_factory_rejects_duplicate_provider_mismatched_closure_and_strategy_execution() -> None:
    generation, revisions = _generation()
    reference = OnlyPrivateAssetRevisionReferenceV1(
        OnlyPrivateAssetKind.ALPHA,
        generation.provenance.private_asset_id,
        generation.provenance.private_asset_revision_fingerprint,
    )
    with pytest.raises(ValueError, match="AUTHORING_CANDIDATE_PROVIDER_DUPLICATE"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=reference,
            private_asset_revisions=revisions,
            private_alpha_executable_closure=_closure(),
            candidate_provider_id=generation.provenance.candidate_provider_id,
            base_catalog=generation.catalog,
        )

    other = _alpha_revision("private.alpha.other")
    with pytest.raises(ValueError, match="AUTHORING_PRIVATE_ALPHA_EXECUTION_BINDING_MISMATCH"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=reference,
            private_asset_revisions=revisions,
            private_alpha_executable_closure=_closure(other),
            candidate_provider_id="candidate.private.other",
            base_catalog=OnlyQuantAssetCatalogGeneration(()),
        )

    strategy = OnlyPrivateStrategyRevision.from_draft(
        OnlyPrivateStrategyDraft(
            strategy_id="private.strategy.momentum",
            semantic_version="1",
            definition={"schema_version": 1},
        )
    )
    with pytest.raises(ValueError, match="AUTHORING_EXECUTION_PRIVATE_ASSET_KIND_UNSUPPORTED"):
        OnlyAuthoringExecutionGeneration.create_verified(
            experiment_id=generation.provenance.experiment_id,
            private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.STRATEGY, strategy.strategy_id, strategy.revision_fingerprint
            ),
            private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(_Revisions(_alpha_revision(), strategy)),
            private_alpha_executable_closure=_closure(),
            candidate_provider_id=generation.provenance.candidate_provider_id,
            base_catalog=OnlyQuantAssetCatalogGeneration(()),
        )


def test_verified_reader_rejects_self_consistent_descriptor_not_backed_by_revision(tmp_path: Path) -> None:
    generation, revisions = _generation()
    identity = generation.provenance.identity_dict()
    identity["private_asset_content_fingerprint"] = "f" * 64
    identity["private_asset_kind"] = OnlyPrivateAssetKind.ALPHA
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
            OnlyPrivateAlphaRevision.from_draft(
                OnlyPrivateAlphaDraft(
                    alpha_id="private.alpha.other",
                    semantic_version="1",
                    source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
                    alpha_api_version=1,
                    alpha_api_contract_fingerprint="a" * 64,
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
