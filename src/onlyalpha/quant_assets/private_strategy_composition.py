"""Exact lowering from DB-native Private Strategy revisions into Research."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, Protocol, cast

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetProvider
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetError,
    OnlyPrivateAssetExactRevisionAuthority,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyRevision,
)
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.definition.model import (
    OnlyResearchDatasetSelection,
    OnlyResearchDefinition,
    OnlyResearchUniverseKind,
)
from onlyalpha.research.definition.resolver import (
    OnlyResearchDefinitionResolution,
    OnlyResearchDefinitionResolver,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run import OnlyResearchRun
from onlyalpha.research.run.generation import OnlyResearchDefinitionRuntimeResolutionV1
from onlyalpha.runtime.generation import OnlyRuntimeGenerationManifest

from .private_factor_execution import OnlyPrivateFactorProviderSnapshotEntryV1
from .private_strategy import (
    OnlyPrivateStrategyDefinitionV1,
    OnlyPrivateStrategyFactorRevisionDependencyV1,
    OnlyPrivateStrategyResearchContextV1,
)

_SHA256 = "0123456789abcdef"
PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION = 1


class OnlyPrivateStrategyResearchCompositionError(OnlyPrivateAssetError):
    code = "PRIVATE_STRATEGY_COMPOSITION_INVALID"

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchCompositionV1:
    schema_version: int
    private_strategy_id: str
    private_strategy_revision_fingerprint: str
    private_strategy_definition_fingerprint: str
    research_context_fingerprint: str
    factor_revision_bindings: tuple[OnlyPrivateStrategyFactorRevisionDependencyV1, ...]
    catalog_generation_fingerprint: str
    research_definition_fingerprint: str
    composition_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION:
            raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_SCHEMA_UNSUPPORTED")
        reference = OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.STRATEGY,
            self.private_strategy_id,
            self.private_strategy_revision_fingerprint,
        )
        del reference
        for value in (
            self.private_strategy_definition_fingerprint,
            self.research_context_fingerprint,
            self.catalog_generation_fingerprint,
            self.research_definition_fingerprint,
            self.composition_fingerprint,
        ):
            if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA256 for char in value):
                raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_INVALID")
        bindings = tuple(sorted(self.factor_revision_bindings))
        if bindings != self.factor_revision_bindings or len(bindings) != len(set(bindings)):
            raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_FACTOR_BINDINGS_INVALID")
        if self.composition_fingerprint != self._expected_fingerprint():
            raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_FINGERPRINT_MISMATCH")

    def _descriptor(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "private_strategy_id": self.private_strategy_id,
            "private_strategy_revision_fingerprint": self.private_strategy_revision_fingerprint,
            "private_strategy_definition_fingerprint": self.private_strategy_definition_fingerprint,
            "research_context_fingerprint": self.research_context_fingerprint,
            "factor_revision_bindings": [item.to_dict() for item in self.factor_revision_bindings],
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "research_definition_fingerprint": self.research_definition_fingerprint,
        }

    def _expected_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1", **self._descriptor()}
        )

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            only_canonical_payload({**self._descriptor(), "composition_fingerprint": self.composition_fingerprint}),
        )

    @classmethod
    def create(
        cls,
        *,
        private_strategy_id: str,
        private_strategy_revision_fingerprint: str,
        private_strategy_definition_fingerprint: str,
        research_context_fingerprint: str,
        factor_revision_bindings: tuple[OnlyPrivateStrategyFactorRevisionDependencyV1, ...],
        catalog_generation_fingerprint: str,
        research_definition_fingerprint: str,
    ) -> OnlyPrivateStrategyResearchCompositionV1:
        descriptor = {
            "schema_version": PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION,
            "private_strategy_id": private_strategy_id,
            "private_strategy_revision_fingerprint": private_strategy_revision_fingerprint,
            "private_strategy_definition_fingerprint": private_strategy_definition_fingerprint,
            "research_context_fingerprint": research_context_fingerprint,
            "factor_revision_bindings": [item.to_dict() for item in factor_revision_bindings],
            "catalog_generation_fingerprint": catalog_generation_fingerprint,
            "research_definition_fingerprint": research_definition_fingerprint,
        }
        return cls(
            schema_version=PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION,
            private_strategy_id=private_strategy_id,
            private_strategy_revision_fingerprint=private_strategy_revision_fingerprint,
            private_strategy_definition_fingerprint=private_strategy_definition_fingerprint,
            research_context_fingerprint=research_context_fingerprint,
            factor_revision_bindings=factor_revision_bindings,
            catalog_generation_fingerprint=catalog_generation_fingerprint,
            research_definition_fingerprint=research_definition_fingerprint,
            composition_fingerprint=only_canonical_fingerprint(
                {"contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_COMPOSITION_V1", **descriptor}
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyResearchCompositionV1:
        expected = {
            "schema_version",
            "private_strategy_id",
            "private_strategy_revision_fingerprint",
            "private_strategy_definition_fingerprint",
            "research_context_fingerprint",
            "factor_revision_bindings",
            "catalog_generation_fingerprint",
            "research_definition_fingerprint",
            "composition_fingerprint",
        }
        if set(payload) != expected or not isinstance(payload["factor_revision_bindings"], list):
            raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_INVALID")
        bindings = tuple(
            OnlyPrivateStrategyFactorRevisionDependencyV1.from_dict(_mapping(item, "factor dependency"))
            for item in cast(list[object], payload["factor_revision_bindings"])
        )
        return cls(
            _integer(payload["schema_version"]),
            _string(payload["private_strategy_id"]),
            _string(payload["private_strategy_revision_fingerprint"]),
            _string(payload["private_strategy_definition_fingerprint"]),
            _string(payload["research_context_fingerprint"]),
            bindings,
            _string(payload["catalog_generation_fingerprint"]),
            _string(payload["research_definition_fingerprint"]),
            _string(payload["composition_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchCompositionResult:
    composition: OnlyPrivateStrategyResearchCompositionV1
    research_definition: OnlyResearchDefinition

    @property
    def composition_fingerprint(self) -> str:
        return self.composition.composition_fingerprint

    @property
    def research_definition_fingerprint(self) -> str:
        return self.composition.research_definition_fingerprint


class _ExactAuthoringGeneration(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchAuthoringProvenance: ...

    def load_catalog_verified(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...

    def load_calculation_registry_verified(self, fingerprint: str) -> OnlyCalculationRegistry: ...


class _ExactRuntimeGeneration(Protocol):
    def require_work_binding(self, work_id: str) -> object: ...

    def require_runtime_generation(self, fingerprint: str) -> OnlyRuntimeGenerationManifest: ...


class _ExactRuntimeDefinitionResolver(Protocol):
    def resolve_definition(
        self, runtime_generation_fingerprint: str, definition: OnlyResearchDefinition
    ) -> OnlyResearchDefinitionRuntimeResolutionV1: ...


class OnlyPrivateStrategyResearchCompositionVerifier:
    """Re-derive a persisted Composition before a Strategy Freeze can use it."""

    def __init__(
        self,
        composer: OnlyPrivateStrategyResearchComposer,
        store: OnlyPrivateStrategyResearchCompositionStore,
        definition_resolver: OnlyResearchDefinitionResolver,
        authoring_generations: _ExactAuthoringGeneration | None = None,
        execution_evidence: OnlyResearchCalculationExecutionEvidenceStore | None = None,
        runtime_generations: _ExactRuntimeGeneration | None = None,
        runtime_definition_resolver: _ExactRuntimeDefinitionResolver | None = None,
        calculations: OnlyCalculationRegistry | None = None,
    ) -> None:
        self._composer = composer
        self._store = store
        self._definition_resolver = definition_resolver
        self._authoring_generations = authoring_generations
        self._execution_evidence = execution_evidence
        self._runtime_generations = runtime_generations
        self._runtime_definition_resolver = runtime_definition_resolver
        self._calculations = calculations

    def verify(self, run: OnlyResearchRun) -> OnlyResearchDefinitionRuntimeResolutionV1 | None:
        fingerprint = run.strategy_research_composition_fingerprint
        if not isinstance(fingerprint, str):
            _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", "Strategy-authored Run has no Composition reference")
        try:
            composition = self._store.load(fingerprint)
            context = self._store.load_context(fingerprint)
            composer = self._composer
            definitions = self._definition_resolver
            exact_calculations: OnlyCalculationRegistry | None = None
            authoring_generation: str | None = None
            runtime_manifest: OnlyRuntimeGenerationManifest | None = None
            runtime_generation: str | None = None
            if self._runtime_generations is not None:
                binding = self._runtime_generations.require_work_binding(run.run_id.value)
                runtime_generation = getattr(binding, "runtime_generation_fingerprint", None)
                if not isinstance(runtime_generation, str):
                    _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", "Strategy Run has no exact Runtime binding")
                runtime_manifest = self._runtime_generations.require_runtime_generation(runtime_generation)
                if composition.catalog_generation_fingerprint != runtime_manifest.catalog_generation_fingerprint:
                    _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Composition Catalog differs from Runtime Catalog")
                composer_result = composer.verify(
                    composition,
                    OnlyPrivateAssetRevisionReferenceV1(
                        OnlyPrivateAssetKind.STRATEGY,
                        composition.private_strategy_id,
                        composition.private_strategy_revision_fingerprint,
                    ),
                    context,
                    runtime_manifest=runtime_manifest,
                )
                if self._runtime_definition_resolver is None:
                    _fail(
                        "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", "exact Runtime Definition resolver is unavailable"
                    )
                exact = self._runtime_definition_resolver.resolve_definition(
                    runtime_generation,
                    composer_result.research_definition,
                )
                if (
                    exact.research_definition_fingerprint != composition.research_definition_fingerprint
                    or exact.specification_fingerprint != getattr(run, "specification_fingerprint", None)
                    or exact.admission_evidence.fingerprint != getattr(run, "admission_resolution_fingerprint", None)
                    or exact.private_factor_bindings
                    != tuple(item.to_dict() for item in runtime_manifest.private_factor_bindings)
                ):
                    _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "exact Runtime Definition resolution differs")
                self._verify_runtime_implementations(exact, runtime_manifest)
                evidence_refs = getattr(run, "calculation_execution_evidence_fingerprints", ())
                if evidence_refs:
                    self._verify_execution_evidence(evidence_refs, exact, runtime_manifest)
                return exact
            if self._authoring_generations is not None:
                authoring_generation = getattr(run, "authoring_generation_fingerprint", None)
                if not isinstance(authoring_generation, str):
                    _fail(
                        "PRIVATE_STRATEGY_COMPOSITION_MISMATCH",
                        "Strategy-authored Run has no exact execution generation",
                    )
                provenance = self._authoring_generations.load_verified(authoring_generation)
                catalog = self._authoring_generations.load_catalog_verified(authoring_generation)
                if (
                    catalog.generation_fingerprint != provenance.catalog_generation_fingerprint
                    or composition.catalog_generation_fingerprint != provenance.catalog_generation_fingerprint
                ):
                    _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Composition execution context differs from Run")
                composer = composer.for_catalog(catalog)
                exact_calculations = self._authoring_generations.load_calculation_registry_verified(
                    authoring_generation
                )
                definitions = definitions.for_calculation_registry(exact_calculations)
            reference = OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.STRATEGY,
                composition.private_strategy_id,
                composition.private_strategy_revision_fingerprint,
            )
            result = composer.verify(composition, reference, context)
            resolved = definitions.resolve(result.research_definition)
            evidence_refs = getattr(run, "calculation_execution_evidence_fingerprints", ())
            if evidence_refs:
                if self._execution_evidence is None or exact_calculations is None:
                    _fail(
                        "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE",
                        "exact Strategy Research execution evidence authority is unavailable",
                    )
                assert authoring_generation is not None
                self._verify_execution_evidence(
                    evidence_refs,
                    resolved,
                    exact_calculations,
                    authoring_generation,
                )
            run_specification_fingerprint = getattr(run, "specification_fingerprint", None)
            if resolved.specification.specification_fingerprint != run_specification_fingerprint:
                _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Run Specification differs from Composition")
        except OnlyPrivateStrategyResearchCompositionError:
            raise
        except Exception as exc:
            _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", str(exc), exc)
        return None

    def _verify_runtime_implementations(
        self,
        resolved: OnlyResearchDefinitionResolution | OnlyResearchDefinitionRuntimeResolutionV1,
        manifest: OnlyRuntimeGenerationManifest,
    ) -> None:
        candidates = (
            resolved.candidates
            if isinstance(resolved, OnlyResearchDefinitionRuntimeResolutionV1)
            else resolved.specification_resolution.candidates
        )
        for lineage in candidates:
            for node in lineage.graph.ordered_nodes:
                backends = (
                    (OnlyCalculationBackendKind.RESEARCH.value,)
                    if node.definition.kind is OnlyCalculationKind.TARGET
                    else (OnlyCalculationBackendKind.RESEARCH.value, OnlyCalculationBackendKind.TRADING.value)
                )
                for backend in backends:
                    matches = tuple(
                        item
                        for item in manifest.implementations
                        if item.kind == node.definition.kind.value
                        and item.type_id == node.definition.type_id
                        and item.semantic_version == node.definition.semantic_version
                        and item.backend == backend
                    )
                    if len(matches) != 1:
                        _fail(
                            "PRIVATE_STRATEGY_COMPOSITION_MISMATCH",
                            "Runtime implementation binding is incomplete: "
                            f"{node.definition.kind.value}:{node.definition.type_id}@"
                            f"{node.definition.semantic_version}/{backend}",
                        )

    def _verify_execution_evidence(
        self,
        evidence_refs: object,
        resolved: OnlyResearchDefinitionResolution | OnlyResearchDefinitionRuntimeResolutionV1,
        exact_runtime: OnlyRuntimeGenerationManifest | OnlyCalculationRegistry,
        authoring_generation_fingerprint: str | None = None,
    ) -> None:
        if not isinstance(evidence_refs, tuple) or not all(isinstance(item, str) for item in evidence_refs):
            _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research Execution Evidence references are invalid")
        for evidence_ref in evidence_refs:
            assert self._execution_evidence is not None
            try:
                evidence = self._execution_evidence.load_verified(evidence_ref)
            except Exception as exc:
                _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", str(exc), exc)
            if isinstance(exact_runtime, OnlyRuntimeGenerationManifest):
                if evidence.authoring_generation_fingerprint is not None:
                    _fail(
                        "PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Strategy Evidence names Factor authoring generation"
                    )
            elif evidence.authoring_generation_fingerprint != authoring_generation_fingerprint:
                _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Execution Evidence names another generation")
            candidates = (
                resolved.candidates
                if isinstance(resolved, OnlyResearchDefinitionRuntimeResolutionV1)
                else resolved.specification_resolution.candidates
            )
            lineage = next(
                (
                    item
                    for item in candidates
                    if item.calculation_fingerprint == evidence.calculation_fingerprint
                    and item.graph_fingerprint == evidence.calculation_graph_fingerprint
                ),
                None,
            )
            if lineage is None:
                _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Execution Evidence names another Calculation Graph")
            expected: dict[str, str] = {}
            for node in lineage.graph.ordered_nodes:
                if isinstance(exact_runtime, OnlyRuntimeGenerationManifest):
                    matches = tuple(
                        item
                        for item in exact_runtime.implementations
                        if item.kind == node.definition.kind.value
                        and item.type_id == node.definition.type_id
                        and item.semantic_version == node.definition.semantic_version
                        and item.backend == OnlyCalculationBackendKind.RESEARCH.value
                    )
                    if len(matches) != 1:
                        _fail(
                            "PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research implementation identity is unavailable"
                        )
                    expected[node.fingerprint] = matches[0].implementation_fingerprint
                else:
                    try:
                        registration = exact_runtime.resolve(
                            node.definition.kind,
                            node.definition.type_id,
                            node.definition.semantic_version,
                            OnlyCalculationBackendKind.RESEARCH,
                        )
                    except (TypeError, ValueError) as exc:
                        _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", str(exc), exc)
                    implementation = registration.implementation_manifest
                    if implementation is None:
                        _fail(
                            "PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research implementation identity is unavailable"
                        )
                    expected[node.fingerprint] = implementation.implementation_fingerprint
            actual = {
                item.node_fingerprint: item.research_implementation_fingerprint
                for item in evidence.research_implementation_bindings
            }
            if actual != expected:
                _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Execution Evidence generation differs from Run")


class OnlyPrivateStrategyResearchComposer:
    """The single non-executing Strategy-to-Research lowering authority."""

    def __init__(
        self,
        assets: OnlyPrivateAssetExactRevisionAuthority,
        catalog: OnlyQuantAssetCatalogGeneration,
    ) -> None:
        if not isinstance(catalog, OnlyQuantAssetCatalogGeneration):
            raise TypeError("exact Catalog Generation is required")
        self._assets = assets
        self._catalog = catalog

    @property
    def catalog(self) -> OnlyQuantAssetCatalogGeneration:
        return self._catalog

    def for_catalog(self, catalog: OnlyQuantAssetCatalogGeneration) -> OnlyPrivateStrategyResearchComposer:
        return OnlyPrivateStrategyResearchComposer(self._assets, catalog)

    def compose(
        self,
        strategy_reference: OnlyPrivateAssetRevisionReferenceV1,
        context: OnlyPrivateStrategyResearchContextV1,
        *,
        runtime_manifest: OnlyRuntimeGenerationManifest | None = None,
    ) -> OnlyPrivateStrategyResearchCompositionResult:
        if (
            not isinstance(strategy_reference, OnlyPrivateAssetRevisionReferenceV1)
            or strategy_reference.private_asset_kind is not OnlyPrivateAssetKind.STRATEGY
        ):
            _fail("PRIVATE_STRATEGY_REVISION_INVALID", "exact Strategy Revision reference is required")
        try:
            context = OnlyPrivateStrategyResearchContextV1.from_dict(context.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            _fail("PRIVATE_STRATEGY_RESEARCH_CONTEXT_INVALID", str(exc), exc)
        try:
            revision = self._assets.load_strategy_revision(
                strategy_reference.private_asset_id,
                strategy_reference.private_asset_revision_fingerprint,
            )
        except Exception as exc:
            _fail("PRIVATE_STRATEGY_REVISION_UNAVAILABLE", str(exc), exc)
        if (
            not isinstance(revision, OnlyPrivateStrategyRevision)
            or revision.strategy_id != strategy_reference.private_asset_id
            or revision.revision_fingerprint != strategy_reference.private_asset_revision_fingerprint
        ):
            _fail("PRIVATE_STRATEGY_REVISION_CORRUPT", "exact Strategy Revision re-anchor failed")
        try:
            definition = OnlyPrivateStrategyDefinitionV1.from_dict(
                cast(Mapping[str, object], _thaw_json(revision.definition))
            )
        except (TypeError, ValueError) as exc:
            _fail("PRIVATE_STRATEGY_REVISION_CORRUPT", str(exc), exc)
        if runtime_manifest is None:
            if self._catalog is None:
                _fail("PRIVATE_STRATEGY_CATALOG_UNAVAILABLE", "exact Catalog Generation is required")
            registry = self._catalog.calculation_registry()
            self._verify_calculations(definition, registry)
        else:
            self._verify_runtime_calculations(definition, runtime_manifest)
        research_definition = OnlyResearchDefinition(
            _dataset(definition, context),
            definition.calculations,
            definition.eligibility,
            definition.signals,
            context.targets,
            context.statistics,
            display_metadata=context.display_metadata,
        )
        research_definition = OnlyResearchDefinition.from_dict(research_definition.to_dict())
        composition = OnlyPrivateStrategyResearchCompositionV1.create(
            private_strategy_id=revision.strategy_id,
            private_strategy_revision_fingerprint=revision.revision_fingerprint,
            private_strategy_definition_fingerprint=revision.definition_fingerprint,
            research_context_fingerprint=context.research_context_fingerprint,
            factor_revision_bindings=definition.factor_revision_dependencies,
            catalog_generation_fingerprint=(
                runtime_manifest.catalog_generation_fingerprint
                if runtime_manifest is not None
                else self._catalog.generation_fingerprint
            ),
            research_definition_fingerprint=research_definition.definition_fingerprint,
        )
        return OnlyPrivateStrategyResearchCompositionResult(composition, research_definition)

    def verify(
        self,
        expected: OnlyPrivateStrategyResearchCompositionV1,
        strategy_reference: OnlyPrivateAssetRevisionReferenceV1,
        context: OnlyPrivateStrategyResearchContextV1,
        *,
        runtime_manifest: OnlyRuntimeGenerationManifest | None = None,
    ) -> OnlyPrivateStrategyResearchCompositionResult:
        actual = self.compose(strategy_reference, context, runtime_manifest=runtime_manifest)
        if actual.composition != expected:
            _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "independent composition differs")
        return actual

    def _verify_runtime_calculations(
        self,
        definition: OnlyPrivateStrategyDefinitionV1,
        manifest: OnlyRuntimeGenerationManifest,
    ) -> None:
        private = {item.entry.factor_id: item.entry for item in manifest.private_factor_bindings}
        declared = {item.factor_id: item for item in definition.factor_revision_dependencies}
        used = {
            item.type_reference.type_id
            for item in definition.calculations
            if item.type_reference.kind is OnlyCalculationKind.FACTOR
            and item.type_reference.type_id.startswith("private.factor.")
        }
        if used != set(declared):
            _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", "Factor usage/dependency closure is not exact")
        for dependency in definition.factor_revision_dependencies:
            entry = private.get(dependency.factor_id)
            if entry is None:
                _fail("PRIVATE_STRATEGY_FACTOR_CATALOG_UNAVAILABLE", dependency.factor_id)
            factor = self._load_factor(dependency)
            if (
                entry.revision_fingerprint != factor.revision_fingerprint
                or entry.semantic_version != factor.semantic_version
                or entry.source_sha256 != factor.source_sha256
                or entry.factor_api_contract_fingerprint != factor.factor_api_contract_fingerprint
            ):
                _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", dependency.factor_id)

    def _verify_calculations(
        self, definition: OnlyPrivateStrategyDefinitionV1, registry: OnlyCalculationRegistry
    ) -> None:
        private_refs = {
            item.type_reference.type_id: item
            for item in definition.calculations
            if item.type_reference.kind is OnlyCalculationKind.FACTOR
            and item.type_reference.type_id.startswith("private.factor.")
        }
        declared = {item.factor_id: item for item in definition.factor_revision_dependencies}
        if set(private_refs) != set(declared):
            _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", "Factor usage/dependency closure is not exact")
        entries: dict[str, tuple[OnlyPrivateFactorProviderSnapshotEntryV1, OnlyQuantAssetProvider]] = {}
        for provider in self._catalog.providers:
            snapshot = provider.private_factor_snapshot
            if snapshot is None:
                continue
            for entry in snapshot.entries:
                if entry.factor_id in entries:
                    _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", "Factor is present in multiple snapshots")
                entries[entry.factor_id] = (entry, provider)
        for instance in definition.calculations:
            reference = instance.type_reference
            if reference.kind not in {OnlyCalculationKind.INDICATOR, OnlyCalculationKind.FACTOR}:
                _fail("PRIVATE_STRATEGY_CALCULATION_UNAVAILABLE", f"unsupported Strategy kind: {reference.kind}")
            try:
                registration = registry.resolve(
                    reference.kind,
                    reference.type_id,
                    reference.semantic_version,
                    OnlyCalculationBackendKind.RESEARCH,
                )
            except (TypeError, ValueError) as exc:
                _fail("PRIVATE_STRATEGY_CALCULATION_UNAVAILABLE", str(exc), exc)
            if registration.implementation_manifest is None:
                _fail("PRIVATE_STRATEGY_CALCULATION_UNAVAILABLE", reference.type_id)
            if reference.type_id not in private_refs:
                continue
            dependency = declared[reference.type_id]
            if reference.semantic_version != self._load_factor(dependency).semantic_version:
                _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", dependency.factor_id)
            try:
                entry, provider = entries[dependency.factor_id]
            except KeyError as exc:
                _fail("PRIVATE_STRATEGY_FACTOR_CATALOG_UNAVAILABLE", dependency.factor_id, exc)
            factor = self._load_factor(dependency)
            if (
                entry.revision_fingerprint != factor.revision_fingerprint
                or entry.semantic_version != factor.semantic_version
                or entry.source_sha256 != factor.source_sha256
                or registration not in provider.calculation_registrations
            ):
                _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", dependency.factor_id)

    def _load_factor(self, dependency: OnlyPrivateStrategyFactorRevisionDependencyV1) -> OnlyPrivateFactorRevision:
        try:
            factor = self._assets.load_factor_revision(dependency.factor_id, dependency.revision_fingerprint)
        except Exception as exc:
            _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISSING", dependency.factor_id, exc)
        if (
            not isinstance(factor, OnlyPrivateFactorRevision)
            or factor.factor_id != dependency.factor_id
            or factor.revision_fingerprint != dependency.revision_fingerprint
        ):
            _fail("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_MISMATCH", dependency.factor_id)
        return factor


class OnlyPrivateStrategyResearchCompositionStore(Protocol):
    def put(
        self,
        composition: OnlyPrivateStrategyResearchCompositionV1,
        context: OnlyPrivateStrategyResearchContextV1,
    ) -> None: ...

    def load(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchCompositionV1: ...

    def load_context(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchContextV1: ...


class OnlyInMemoryPrivateStrategyResearchCompositionStore:
    def __init__(self) -> None:
        self._values: dict[str, OnlyPrivateStrategyResearchCompositionV1] = {}
        self._contexts: dict[str, OnlyPrivateStrategyResearchContextV1] = {}

    def put(
        self,
        composition: OnlyPrivateStrategyResearchCompositionV1,
        context: OnlyPrivateStrategyResearchContextV1,
    ) -> None:
        existing = self._values.get(composition.composition_fingerprint)
        if existing is not None and existing != composition:
            _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", composition.composition_fingerprint)
        context = OnlyPrivateStrategyResearchContextV1.from_dict(context.to_dict())
        if context.research_context_fingerprint != composition.research_context_fingerprint:
            _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research Context fingerprint differs")
        old_context = self._contexts.get(composition.composition_fingerprint)
        if old_context is not None and old_context != context:
            _fail("PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research Context differs")
        self._contexts.setdefault(composition.composition_fingerprint, context)
        self._values.setdefault(composition.composition_fingerprint, composition)

    def load(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchCompositionV1:
        try:
            return self._values[composition_fingerprint]
        except KeyError as exc:
            _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", composition_fingerprint, exc)

    def load_context(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchContextV1:
        try:
            return self._contexts[composition_fingerprint]
        except KeyError as exc:
            _fail("PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", composition_fingerprint, exc)


def _dataset(
    definition: OnlyPrivateStrategyDefinitionV1,
    context: OnlyPrivateStrategyResearchContextV1,
) -> OnlyResearchDatasetSelection:
    universe = definition.universe
    kind = (
        OnlyResearchUniverseKind.SINGLE_INSTRUMENT
        if len(universe.instruments) == 1
        else OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET
    )
    from onlyalpha.research.definition.model import OnlyResearchUniverseSelection

    return OnlyResearchDatasetSelection(
        OnlyResearchUniverseSelection(kind, tuple(str(item) for item in universe.instruments)),
        definition.market_input.bar_specification,
        definition.market_input.aggregation_source,
        context.start,
        context.end,
        definition.market_input.adjustment_type,
        definition.market_input.adjustment_reference,
    )


def _fail(code: str, detail: str = "", cause: Exception | None = None) -> NoReturn:
    error = OnlyPrivateStrategyResearchCompositionError(code, detail)
    if cause is None:
        raise error
    raise error from cause


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_INVALID", context)
    return cast(Mapping[str, object], value)


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_INVALID")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_INVALID")
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "PRIVATE_"))]
