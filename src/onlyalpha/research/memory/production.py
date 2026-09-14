"""Product-side composition of exact source and reference authorities.

The pure projector deliberately has a callback seam.  This service is the
production entry point: callers supply a manifest, never reference answers.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.backtest.evidence import OnlyBacktestEvidenceManifest
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.research.source_cut import OnlySourceClosedCutV1, OnlySourceObservationV1
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.strategy.qualification import OnlyQualificationPolicyRevision

from .projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryCutReader,
    OnlyMemoryReferenceKind,
    only_load_cut_observations,
    only_project_experiment_memory,
)
from .source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1, OnlyMemoryProjectionError
from .store import OnlyExperimentMemoryRevisionStore


class OnlyExactCatalogDescriptorReader(Protocol):
    def load_verified_catalog_descriptor(self, fingerprint: str) -> Mapping[str, object]: ...


class OnlyExactRuntimeGenerationReader(Protocol):
    def require_work_binding(self, work_id: str) -> _RuntimeBinding: ...

    def require_runtime_generation(self, fingerprint: str) -> _RuntimeManifest: ...


class _RuntimeBinding(Protocol):
    @property
    def work_id(self) -> str: ...

    @property
    def runtime_generation_fingerprint(self) -> str: ...


class _RuntimeManifest(Protocol):
    @property
    def runtime_generation_fingerprint(self) -> str: ...


class OnlyExactAuthoringGenerationReader(Protocol):
    def load_descriptor_verified(self, fingerprint: str) -> Mapping[str, object]: ...


class OnlyExactQualificationPolicyReader(Protocol):
    def load_exact(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision: ...


class OnlyExactBacktestEvidenceReader(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyBacktestEvidenceManifest: ...


class OnlyCapturableMemoryCutReader(OnlyMemoryCutReader, Protocol):
    def capture_closed_cut(self) -> OnlySourceClosedCutV1: ...


SUPPORTED_REFERENCE_KINDS = frozenset(OnlyMemoryReferenceKind)


def _row(observation: OnlySourceObservationV1) -> Mapping[str, object]:
    if observation.source_family in {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }:
        value = observation.canonical_payload.get("source_row")
        if not isinstance(value, Mapping):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        return value
    return observation.canonical_payload


@dataclass(frozen=True, slots=True)
class OnlyExperimentMemoryReferenceReadersV1:
    """Typed ports to existing owners; no caller-provided reference callback."""

    datasets: OnlyParquetResearchDatasetSnapshotStore
    catalogs: OnlyExactCatalogDescriptorReader
    symbolic: OnlyJsonSymbolicSearchStore
    parameter: OnlyJsonParameterSearchStore
    calculations: OnlyParquetResearchCalculationResultStore
    runtime_generations: OnlyExactRuntimeGenerationReader
    authoring_generations: OnlyExactAuthoringGenerationReader
    qualification_policies: OnlyExactQualificationPolicyReader
    backtest_evidence: OnlyExactBacktestEvidenceReader

    def for_observations(self, observations: tuple[OnlySourceObservationV1, ...]) -> _BoundReferenceReader:
        return _BoundReferenceReader(self, observations)


class _BoundReferenceReader:
    def __init__(
        self, owners: OnlyExperimentMemoryReferenceReadersV1, observations: tuple[OnlySourceObservationV1, ...]
    ) -> None:
        self._owners = owners
        calculations: dict[str, set[str]] = defaultdict(set)
        specifications: dict[str, OnlyResearchSpecification] = {}
        for observation in observations:
            payload = _row(observation)
            if observation.source_family == "RESEARCH_RESULT":
                plan = payload.get("plan")
                if not isinstance(plan, Mapping):
                    raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                members = plan.get("calculations", [])
                if not isinstance(members, list):
                    raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                result_graphs: dict[str, str] = {}
                for item in members:
                    if not isinstance(item, Mapping):
                        raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                    graph, calculation = item.get("graph_fingerprint"), item.get("calculation_fingerprint")
                    if not isinstance(graph, str) or not isinstance(calculation, str):
                        raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                    if calculation in result_graphs and result_graphs[calculation] != graph:
                        raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                    result_graphs[calculation] = graph
                    calculations[graph].add(calculation)
                candidates = plan.get("candidates", [])
                if not isinstance(candidates, list):
                    raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                for candidate in candidates:
                    calculation_id = (
                        candidate.get("calculation_fingerprint") if isinstance(candidate, Mapping) else None
                    )
                    if not isinstance(calculation_id, str) or result_graphs.get(calculation_id) != candidate.get(
                        "graph_fingerprint"
                    ):
                        raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
                for category in ("published_series", "signals"):
                    series = plan.get(category, [])
                    if not isinstance(series, list):
                        raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                    for item in series:
                        if not isinstance(item, Mapping):
                            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
                        calculation_id = item.get("calculation_fingerprint")
                        if not isinstance(calculation_id, str) or calculation_id not in result_graphs:
                            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
                        try:
                            result = self._owners.calculations.load_verified(calculation_id)
                        except Exception as exc:
                            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc
                        graph = result.manifest.calculation_graph
                        if result.manifest.calculation_graph_fingerprint != result_graphs[calculation_id] or not any(
                            node.fingerprint == item.get("node_fingerprint")
                            and item.get("output_name") in {output.name for output in node.definition.outputs}
                            for node in graph.ordered_nodes
                        ):
                            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            elif observation.source_family == "RESEARCH_RUN":
                raw = payload.get("specification_payload")
                try:
                    decoded = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(decoded, Mapping):
                        raise ValueError("specification payload")
                    specification = OnlyResearchSpecification.from_dict(decoded)
                except (ValueError, KeyError, TypeError) as exc:
                    raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc
                identity = payload.get("specification_fingerprint")
                if identity != specification.specification_fingerprint:
                    raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
                specifications[specification.specification_fingerprint] = specification
        self._calculations = calculations
        self._specifications = specifications

    def __call__(self, kind: OnlyMemoryReferenceKind | str, identity: str) -> Mapping[str, object]:
        try:
            return self._load(OnlyMemoryReferenceKind(kind), identity)
        except (TypeError, ValueError) as exc:
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc
        except OnlyMemoryProjectionError:
            raise
        except Exception as exc:
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc

    def _load(self, kind: OnlyMemoryReferenceKind, identity: str) -> Mapping[str, object]:
        owners = self._owners
        if kind is OnlyMemoryReferenceKind.DATASET_SNAPSHOT:
            snapshot = owners.datasets.load_verified_table(identity).snapshot
            self._require(snapshot.snapshot_fingerprint == identity)
            return snapshot.to_dict()
        if kind is OnlyMemoryReferenceKind.CATALOG_GENERATION:
            descriptor = owners.catalogs.load_verified_catalog_descriptor(identity)
            self._require(descriptor.get("generation_fingerprint") == identity)
            return descriptor
        if kind is OnlyMemoryReferenceKind.SEARCH_SPACE:
            for reader in (owners.symbolic, owners.parameter):
                try:
                    space = reader.load_search_space_intrinsic_verified(identity)
                except Exception as exc:
                    if getattr(exc, "code", "").endswith("_NOT_FOUND"):
                        continue
                    raise
                self._require(space.search_space_fingerprint == identity)
                return space.to_dict()
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
        if kind is OnlyMemoryReferenceKind.EVALUATION_CONTRACT:
            evaluation = owners.symbolic.load_evaluation_contract_intrinsic_verified(identity)
            self._require(evaluation.evaluation_contract_fingerprint == identity)
            return evaluation.to_dict()
        if kind is OnlyMemoryReferenceKind.SEARCH_POLICY:
            policy = owners.parameter.load_policy_intrinsic_verified(identity)
            self._require(policy.policy_fingerprint == identity)
            return policy.to_dict()
        if kind is OnlyMemoryReferenceKind.SEARCH_ALGORITHM:
            found: list[Mapping[str, object]] = []
            for load in (
                owners.symbolic.load_algorithm_implementation_manifest_intrinsic_verified,
                owners.parameter.load_algorithm_manifest_intrinsic_verified,
            ):
                try:
                    algorithm = load(identity)
                except Exception as exc:
                    if getattr(exc, "code", "").endswith("_NOT_FOUND"):
                        continue
                    raise
                self._require(algorithm.implementation_fingerprint == identity)
                found.append(algorithm.to_dict())
            self._require(len(found) == 1)
            return found[0]
        if kind is OnlyMemoryReferenceKind.ONLY_SYMBOLIC_GRAPH_PROPOSAL:
            proposal = owners.symbolic.load_proposal_intrinsic_verified(identity)
            self._require(proposal.proposal_fingerprint == identity)
            return proposal.to_dict()
        if kind is OnlyMemoryReferenceKind.ONLY_PARAMETER_GRAPH_PROPOSAL:
            parameter_proposal = owners.parameter.load_proposal_intrinsic_verified(identity)
            self._require(parameter_proposal.proposal_fingerprint == identity)
            return parameter_proposal.to_dict()
        if kind is OnlyMemoryReferenceKind.CALCULATION_GRAPH:
            calculation_ids = self._calculations.get(identity)
            if not calculation_ids:
                raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            for calculation_id in sorted(calculation_ids):
                result = owners.calculations.load_verified(calculation_id)
                self._require(
                    result.manifest.calculation_fingerprint == calculation_id
                    and result.manifest.calculation_graph.fingerprint == identity
                    and result.manifest.calculation_graph_fingerprint == identity
                )
            return {"graph_fingerprint": identity}
        if kind is OnlyMemoryReferenceKind.RESEARCH_SPECIFICATION:
            specification = self._specifications.get(identity)
            if specification is None or specification.specification_fingerprint != identity:
                raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            return specification.to_dict()
        if kind is OnlyMemoryReferenceKind.RUNTIME_WORK_BINDING:
            binding = owners.runtime_generations.require_work_binding(identity)
            generation = binding.runtime_generation_fingerprint
            self._require(binding.work_id == identity and isinstance(generation, str))
            manifest = owners.runtime_generations.require_runtime_generation(generation)
            self._require(manifest.runtime_generation_fingerprint == generation)
            return {"work_id": identity, "runtime_generation_fingerprint": generation}
        if kind is OnlyMemoryReferenceKind.AUTHORING_GENERATION:
            descriptor = owners.authoring_generations.load_descriptor_verified(identity)
            self._require(descriptor.get("execution_generation_fingerprint") == identity)
            return descriptor
        if kind is OnlyMemoryReferenceKind.QUALIFICATION_POLICY:
            policy_id, separator, version = identity.partition(":")
            self._require(bool(separator and policy_id and version))
            qualification_policy = owners.qualification_policies.load_exact(policy_id, version)
            self._require(
                qualification_policy.policy_id == policy_id and qualification_policy.policy_version == version
            )
            return qualification_policy.to_dict()
        if kind is OnlyMemoryReferenceKind.QUALIFICATION_EVIDENCE:
            evidence = owners.backtest_evidence.load_verified(identity)
            self._require(evidence.evidence_fingerprint == identity)
            return evidence.to_dict()
        raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")

    @staticmethod
    def _require(condition: bool) -> None:
        if not condition:
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")


class OnlyExperimentMemoryProductionBuilder:
    """Exact Cut/owner verification and publication, never an injected fake callback."""

    def __init__(
        self,
        source_readers: Mapping[str, OnlyCapturableMemoryCutReader],
        reference_readers: OnlyExperimentMemoryReferenceReadersV1,
        revisions: OnlyExperimentMemoryRevisionStore,
    ) -> None:
        if set(source_readers) != set(MANDATORY_FAMILIES):
            raise OnlyMemoryProjectionError("SOURCE_CUT_MISSING")
        self._sources = dict(source_readers)
        self._references = reference_readers
        self._revisions = revisions

    def capture_manifest(self) -> OnlyExperimentMemorySourceCutManifestV1:
        return OnlyExperimentMemorySourceCutManifestV1.from_cuts(
            [self._sources[family].capture_closed_cut() for family in MANDATORY_FAMILIES]
        )

    def build(self, manifest: OnlyExperimentMemorySourceCutManifestV1) -> OnlyExperimentMemoryProjectionV1:
        observations = only_load_cut_observations(manifest, self._sources)
        return only_project_experiment_memory(manifest, observations, self._references.for_observations(observations))

    def publish_and_activate(
        self, manifest: OnlyExperimentMemorySourceCutManifestV1
    ) -> OnlyExperimentMemoryProjectionV1:
        projection = self.build(manifest)
        revision = self._revisions._publish_and_activate(projection)
        verified = self._revisions.load_verified(revision)
        if verified != projection:
            raise OnlyMemoryProjectionError("PROJECTION_SOURCE_CONFLICT")
        return verified
