"""Pure, non-authoritative projection of exact cut-bound source observations."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast

from onlyalpha.application.product_command_authority import only_verify_product_command_binding
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.search_product import only_search_experiment_work_id
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.command.model import OnlyDerivedResearchSubmitCommandV2, only_derived_research_run_id
from onlyalpha.research.experiment.model import OnlySearchIterationPlanV1
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.parameter.integration import parameter_submission_key
from onlyalpha.research.search.symbolic.controller import symbolic_submission_key
from onlyalpha.research.source_cut import OnlySourceClosedCutV1, OnlySourceCutError, OnlySourceObservationV1
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .source_manifest import (
    MANDATORY_FAMILIES,
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)

PROJECTION_SCHEMA_VERSION = 7
PROJECTOR_ALGORITHM_VERSION = 7


class OnlyMemoryReferenceKind(StrEnum):
    """Finite vocabulary of exact authorities used by the projection."""

    DATASET_SNAPSHOT = "DATASET_SNAPSHOT"
    CATALOG_GENERATION = "CATALOG_GENERATION"
    SEARCH_SPACE = "SEARCH_SPACE"
    EVALUATION_CONTRACT = "EVALUATION_CONTRACT"
    SEARCH_POLICY = "SEARCH_POLICY"
    SEARCH_ALGORITHM = "SEARCH_ALGORITHM"
    ONLY_SYMBOLIC_GRAPH_PROPOSAL = "ONLY_SYMBOLIC_GRAPH_PROPOSAL"
    ONLY_PARAMETER_GRAPH_PROPOSAL = "ONLY_PARAMETER_GRAPH_PROPOSAL"
    CALCULATION_GRAPH = "CALCULATION_GRAPH"
    RESEARCH_SPECIFICATION = "RESEARCH_SPECIFICATION"
    RUNTIME_WORK_BINDING = "RUNTIME_WORK_BINDING"
    AUTHORING_GENERATION = "AUTHORING_GENERATION"
    QUALIFICATION_POLICY = "QUALIFICATION_POLICY"
    QUALIFICATION_EVIDENCE = "QUALIFICATION_EVIDENCE"


def _reference_kind(value: object) -> OnlyMemoryReferenceKind:
    if not isinstance(value, str):
        raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
    try:
        return OnlyMemoryReferenceKind(value)
    except (TypeError, ValueError) as exc:
        raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc


class OnlyMemoryCutReader(Protocol):
    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1: ...

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]: ...


@dataclass(frozen=True, slots=True)
class OnlyMemorySourceRefV1:
    source_family: str
    cut_fingerprint: str
    locator: str
    identity: str
    content_fingerprint: str

    @classmethod
    def from_observation(cls, item: OnlySourceObservationV1) -> OnlyMemorySourceRefV1:
        return cls(item.source_family, item.cut_fingerprint, item.locator, item.identity, item.content_fingerprint)

    def to_dict(self) -> dict[str, str]:
        return {
            "source_family": self.source_family,
            "cut_fingerprint": self.cut_fingerprint,
            "locator": self.locator,
            "identity": self.identity,
            "content_fingerprint": self.content_fingerprint,
        }


@dataclass(frozen=True, slots=True, init=False)
class OnlyMemoryProjectionRecordV1:
    """One of four versioned derived record kinds; source refs remain exact."""

    kind: str
    _facets_json: str
    source_refs: tuple[OnlyMemorySourceRefV1, ...]

    def __init__(self, kind: str, facets: Mapping[str, object], source_refs: tuple[OnlyMemorySourceRefV1, ...]) -> None:
        if (
            kind
            not in {
                "ExperimentProjectionRecord",
                "EvaluationProjectionRecord",
                "ParameterObservationProjectionRecord",
                "FailureEvidenceProjectionRecord",
            }
            or not source_refs
        ):
            raise OnlyMemoryProjectionError("PROJECTION_BUILD_FAILED")
        object.__setattr__(self, "kind", kind)
        try:
            object.__setattr__(self, "_facets_json", only_canonical_json(dict(facets)))
        except (TypeError, ValueError) as exc:
            raise OnlyMemoryProjectionError("PROJECTION_BUILD_FAILED") from exc
        object.__setattr__(self, "source_refs", source_refs)

    @property
    def facets(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._facets_json))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "facets": json.loads(self._facets_json),
            "source_refs": [ref.to_dict() for ref in self.source_refs],
        }


@dataclass(frozen=True, slots=True)
class OnlyExperimentMemoryProjectionV1:
    source_manifest: OnlyExperimentMemorySourceCutManifestV1
    records: tuple[OnlyMemoryProjectionRecordV1, ...]

    @property
    def logical_digest(self) -> str:
        return only_canonical_fingerprint(
            {
                "projection_schema_version": PROJECTION_SCHEMA_VERSION,
                "projector_algorithm_version": PROJECTOR_ALGORITHM_VERSION,
                "records": [record.to_dict() for record in self.records],
            }
        )

    @property
    def revision_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "source_cut_manifest_fingerprint": self.source_manifest.manifest_fingerprint,
                "projection_schema_version": PROJECTION_SCHEMA_VERSION,
                "projector_algorithm_version": PROJECTOR_ALGORITHM_VERSION,
                "logical_digest": self.logical_digest,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "projection_schema_version": PROJECTION_SCHEMA_VERSION,
            "projector_algorithm_version": PROJECTOR_ALGORITHM_VERSION,
            "source_manifest": self.source_manifest.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "logical_digest": self.logical_digest,
            "revision_fingerprint": self.revision_fingerprint,
        }


def only_load_cut_observations(
    manifest: OnlyExperimentMemorySourceCutManifestV1,
    readers: Mapping[str, OnlyMemoryCutReader],
) -> tuple[OnlySourceObservationV1, ...]:
    """IO is confined to owning reader ports; do not admit caller-supplied raw rows."""
    if set(readers) != set(MANDATORY_FAMILIES):
        raise OnlyMemoryProjectionError("SOURCE_CUT_MISSING")
    collected: list[OnlySourceObservationV1] = []
    for ref in manifest.cuts:
        owner = readers[ref.source_family]
        try:
            cut = owner.load_closed_cut_verified(ref.cut_fingerprint)
            if (
                cut.source_family != ref.source_family
                or cut.source_schema_version != ref.source_schema_version
                or cut.enumeration_contract_version != ref.enumeration_contract_version
                or cut.cut_boundary != ref.cut_boundary
                or cut.completeness_proof != ref.completeness_proof
            ):
                raise OnlyMemoryProjectionError("SOURCE_CUT_CORRUPT")
            observations = owner.iter_closed_cut_observations_verified(ref.cut_fingerprint)
            observed = {(o.locator, o.identity, o.content_fingerprint) for o in observations}
            expected = {(e.locator, e.identity, e.content_fingerprint) for e in cut.entries}
            if (
                len(observed) != len(observations)
                or observed != expected
                or any(
                    o.source_family != ref.source_family
                    or o.source_schema_version != ref.source_schema_version
                    or o.cut_fingerprint != ref.cut_fingerprint
                    for o in observations
                )
            ):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            collected.extend(observations)
        except OnlyMemoryProjectionError:
            raise
        except OnlySourceCutError as exc:
            code = str(exc)
            if code in {"SOURCE_CUT_NOT_FOUND", "SOURCE_CUT_FINGERPRINT_INVALID"}:
                raise OnlyMemoryProjectionError("SOURCE_CUT_MISSING") from exc
            if code in {"SOURCE_CUT_SCHEMA_INVALID", "SOURCE_CUT_FAMILY_INVALID"}:
                raise OnlyMemoryProjectionError("SOURCE_CUT_SCHEMA_UNSUPPORTED") from exc
            if code == "SOURCE_CUT_POSTGRES_UNAVAILABLE":
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_UNAVAILABLE") from exc
            if code.startswith("SOURCE_CUT_"):
                raise OnlyMemoryProjectionError("SOURCE_CUT_CORRUPT") from exc
            if code.startswith("SOURCE_OBSERVATION_"):
                raise OnlyMemoryProjectionError(code) from exc
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_UNAVAILABLE") from exc
        except Exception as exc:
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_UNAVAILABLE") from exc
    return tuple(collected)


def only_build_experiment_memory_projection(
    manifest: OnlyExperimentMemorySourceCutManifestV1,
    readers: Mapping[str, OnlyMemoryCutReader],
    verify_exact_reference: Callable[[str, str], Mapping[str, object] | None],
) -> OnlyExperimentMemoryProjectionV1:
    """Formal build: every member is reloaded through its owning source authority."""
    observations = only_load_cut_observations(manifest, readers)
    return only_project_experiment_memory(manifest, observations, verify_exact_reference)


def _payload(item: OnlySourceObservationV1) -> Mapping[str, object]:
    if item.source_family in {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }:
        row = item.canonical_payload.get("source_row")
        if not isinstance(row, Mapping):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        return row
    return item.canonical_payload


def _ref(item: OnlySourceObservationV1) -> tuple[OnlyMemorySourceRefV1, ...]:
    return (OnlyMemorySourceRefV1.from_observation(item),)


def _product_relation_ref(item: OnlySourceObservationV1, command_id: str) -> dict[str, str]:
    row = _payload(item)
    native_locator = item.canonical_payload.get("native_locator")
    if native_locator != row.get("command_id") or native_locator != command_id:
        raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
    return {**_ref(item)[0].to_dict(), "native_locator": command_id}


def _required_member(
    index: Mapping[str, OnlySourceObservationV1],
    identity: object,
    *,
    result_identity: object | None = None,
) -> OnlySourceObservationV1:
    if not isinstance(identity, str) or identity not in index:
        raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
    item = index[identity]
    if result_identity is not None and item.identity != result_identity:
        raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
    return item


def _search_lineages(
    by_family: Mapping[str, list[OnlySourceObservationV1]],
    experiments: Mapping[str, OnlySourceObservationV1],
    result_by_plan: Mapping[str, OnlySourceObservationV1],
) -> dict[str, Mapping[str, object]]:
    """Resolve occurrence ownership only through cut-bound Product facts, never Result equality."""
    admissions: dict[str, tuple[OnlyProductCommandAdmissionV1, OnlySourceObservationV1]] = {}
    receipts: dict[str, tuple[OnlyProductCommandReceipt, OnlySourceObservationV1]] = {}
    runs: dict[str, list[OnlySourceObservationV1]] = defaultdict(list)
    try:
        for item in by_family["RESEARCH_RUN"]:
            runs[str(_payload(item)["run_id"])].append(item)
        for item in by_family["PRODUCT_COMMAND_ADMISSION"]:
            row = _payload(item)
            admission = OnlyProductCommandAdmissionV1(
                OnlyProductCommandId(cast(str, row["command_id"])),
                OnlyProductCommandKind(cast(str, row["command_kind"])),
                cast(str, row["command_fingerprint"]),
                cast(int, row["schema_version"]),
            )
            if admission.command_id.value in admissions:
                raise ValueError("duplicate Product admission")
            admissions[admission.command_id.value] = admission, item
        for item in by_family["PRODUCT_COMMAND_RECEIPT"]:
            row = _payload(item)
            receipt = OnlyProductCommandReceipt(
                OnlyProductCommandId(cast(str, row["command_id"])),
                OnlyProductCommandKind(cast(str, row["command_kind"])),
                cast(str, row["command_fingerprint"]),
                OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind(cast(str, row["outcome_kind"])),
                    cast(str, row["outcome_id"]),
                ),
                datetime.fromisoformat(cast(str, row["accepted_at"])),
                cast(int, row["schema_version"]),
            )
            if receipt.command_id.value in receipts:
                raise ValueError("duplicate Product receipt")
            admission, _ = admissions[receipt.command_id.value]
            only_verify_product_command_binding(admission, receipt)
            if receipt.outcome_ref.kind is OnlyProductCommandOutcomeKind.RESEARCH_RUN:
                if receipt.outcome_ref.outcome_id not in runs:
                    raise ValueError("Product receipt points outside the Run cut")
            receipts[receipt.command_id.value] = receipt, item

        lineages: dict[str, Mapping[str, object]] = {}
        for item in by_family["SEARCH_PROVENANCE"]:
            if not item.locator.startswith("iteration-plans/"):
                continue
            plan = OnlySearchIterationPlanV1.from_dict(_payload(item))
            if plan.iteration_plan_fingerprint != item.identity:
                raise ValueError("Plan identity mismatch")
            experiment = _required_member(experiments, f"experiments/{plan.experiment_fingerprint}")
            if experiment.identity != plan.experiment_fingerprint:
                raise ValueError("Plan Experiment identity mismatch")
            proposal_kind = _reference_kind(plan.proposal_kind)
            if proposal_kind is OnlyMemoryReferenceKind.ONLY_SYMBOLIC_GRAPH_PROPOSAL:
                method, command_id = "SYMBOLIC", symbolic_submission_key(plan)
            elif proposal_kind is OnlyMemoryReferenceKind.ONLY_PARAMETER_GRAPH_PROPOSAL:
                method, command_id = "PARAMETER", parameter_submission_key(plan)
            else:
                raise ValueError("unsupported Search method")
            bound = receipts.get(command_id.value)
            if bound is None:
                if only_derived_research_run_id(command_id).value in runs:
                    raise ValueError("Search-owned Run is missing its Product receipt")
                continue  # A Plan may precede its Product command and terminal Iteration Result.
            receipt, receipt_source = bound
            admission, admission_source = admissions[command_id.value]
            if (
                admission.command_kind is not OnlyProductCommandKind.CREATE_RESEARCH_RUN
                or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
                or receipt.outcome_ref.outcome_id != only_derived_research_run_id(command_id).value
            ):
                raise ValueError("Search Product outcome mismatch")
            run_id = receipt.outcome_ref.outcome_id
            if run_id in lineages:
                raise ValueError("multiple Search owners for one Run")
            for run in runs[run_id]:
                row = _payload(run)
                raw = row["specification_payload"]
                decoded = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(decoded, Mapping):
                    raise ValueError("Run specification is unavailable")
                specification = OnlyResearchSpecification.from_dict(decoded)
                provenance = row.get("authoring_provenance")
                expected = OnlyDerivedResearchSubmitCommandV2(
                    command_id,
                    specification,
                    only_search_experiment_work_id(plan.experiment_fingerprint),
                    OnlyResearchAuthoringProvenance.from_dict(provenance) if isinstance(provenance, Mapping) else None,
                )
                if (
                    row["run_id"] != run_id
                    or row["specification_fingerprint"] != specification.specification_fingerprint
                    or admission.command_fingerprint != expected.command_fingerprint
                ):
                    raise ValueError("Search Product intent does not bind the Run")
            terminal = result_by_plan.get(plan.iteration_plan_fingerprint)
            if terminal is not None and _payload(terminal).get("iteration_plan_fingerprint") != item.identity:
                raise ValueError("Search Iteration Result belongs to another Plan")
            lineages[run_id] = {
                "search_method": method,
                "experiment_fingerprint": experiment.identity,
                "iteration_plan_fingerprint": item.identity,
                "iteration_result_fingerprint": terminal.identity if terminal is not None else None,
                "research_product_command_id": command_id.value,
                "research_product_command_kind": admission.command_kind,
                "research_product_command_fingerprint": admission.command_fingerprint,
                "experiment_source_ref": _ref(experiment)[0].to_dict(),
                "plan_source_ref": _ref(item)[0].to_dict(),
                "admission_source_ref": _product_relation_ref(admission_source, command_id.value),
                "receipt_source_ref": _product_relation_ref(receipt_source, command_id.value),
                "iteration_result_source_ref": _ref(terminal)[0].to_dict() if terminal is not None else None,
            }
        return lineages
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE") from exc


def _build_run_occurrence_closure(
    run: OnlySourceObservationV1,
    exact: Callable[[OnlyMemoryReferenceKind, object], Mapping[str, object] | None],
    search_lineages: Mapping[str, Mapping[str, object]],
    result_identities: frozenset[str],
) -> tuple[dict[str, object], tuple[OnlyMemorySourceRefV1, ...]]:
    """Build one Result-independent, owner-verified Run occurrence context."""
    fact = _payload(run)
    run_id = fact.get("run_id")
    exact(OnlyMemoryReferenceKind.RESEARCH_SPECIFICATION, fact.get("specification_fingerprint"))
    binding = exact(OnlyMemoryReferenceKind.RUNTIME_WORK_BINDING, run_id)
    generation = binding.get("runtime_generation_fingerprint") if isinstance(binding, Mapping) else None
    catalog = binding.get("catalog_generation_fingerprint") if isinstance(binding, Mapping) else None
    if (
        not isinstance(binding, Mapping)
        or binding.get("work_id") != run_id
        or not isinstance(generation, str)
        or not isinstance(catalog, str)
        or len(catalog) != 64
        or any(char not in "0123456789abcdef" for char in catalog)
    ):
        raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")

    state = fact.get("state")
    revision = fact.get("revision")
    result = fact.get("research_result_fingerprint")
    artifact = fact.get("artifact_content_fingerprint")
    evidence = fact.get("calculation_execution_evidence_fingerprints", [])
    provenance = fact.get("authoring_provenance")
    authoring_generation = (
        provenance.get("execution_generation_fingerprint") if isinstance(provenance, Mapping) else None
    )
    if isinstance(authoring_generation, str):
        descriptor = exact(OnlyMemoryReferenceKind.AUTHORING_GENERATION, authoring_generation)
        authoring_payload = descriptor.get("provenance") if isinstance(descriptor, Mapping) else None
        if (
            not isinstance(descriptor, Mapping)
            or not isinstance(authoring_payload, Mapping)
            or descriptor.get("execution_generation_fingerprint") != authoring_generation
            or authoring_payload.get("catalog_generation_fingerprint") != catalog
        ):
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
    if (
        not isinstance(run_id, str)
        or type(revision) is not int
        or revision < 0
        or not isinstance(state, str)
        or state not in OnlyResearchRunState
        or (result is not None and (not isinstance(result, str) or result not in result_identities))
        or (state == OnlyResearchRunState.COMPLETED and (result is None or not isinstance(artifact, str)))
        or (artifact is not None and not isinstance(artifact, str))
        or (provenance is not None and not isinstance(provenance, Mapping))
        or (provenance is not None and not isinstance(authoring_generation, str))
        or not isinstance(evidence, list)
        or any(not isinstance(value, str) for value in evidence)
        or evidence != sorted(set(evidence))
    ):
        raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")

    lineage = search_lineages.get(run_id)
    run_ref = _ref(run)[0]
    refs = [run_ref]
    if lineage is not None:
        for field in ("experiment_source_ref", "plan_source_ref", "admission_source_ref", "receipt_source_ref"):
            relation = cast(Mapping[str, object], lineage[field])
            refs.append(
                OnlyMemorySourceRefV1(
                    cast(str, relation["source_family"]),
                    cast(str, relation["cut_fingerprint"]),
                    cast(str, relation["locator"]),
                    cast(str, relation["identity"]),
                    cast(str, relation["content_fingerprint"]),
                )
            )
        terminal_ref = lineage.get("iteration_result_source_ref")
        if isinstance(terminal_ref, Mapping):
            refs.append(OnlyMemorySourceRefV1(**cast(dict[str, str], terminal_ref)))
    return (
        {
            "run_id": run_id,
            "run_revision": revision,
            "run_state": state,
            "specification_fingerprint": fact.get("specification_fingerprint"),
            "research_result_fingerprint": result,
            "artifact_content_fingerprint": artifact,
            "catalog_generation_fingerprint": catalog,
            "runtime_generation_fingerprint": generation,
            "authoring_generation_fingerprint": authoring_generation,
            "calculation_execution_evidence_fingerprints": evidence,
            "run_source_ref": run_ref.to_dict(),
            "search_lineage": lineage,
        },
        tuple(sorted(set(refs), key=lambda ref: (ref.source_family, ref.locator))),
    )


def only_project_experiment_memory(
    manifest: OnlyExperimentMemorySourceCutManifestV1,
    observations: Iterable[OnlySourceObservationV1],
    verify_exact_reference: Callable[[str, str], Mapping[str, object] | None],
) -> OnlyExperimentMemoryProjectionV1:
    """Caller supplies only owner-returned observations; materialization validates Cut membership."""
    indexed: dict[tuple[str, str], OnlySourceObservationV1] = {}
    for item in observations:
        key = item.source_family, item.locator
        prior = indexed.get(key)
        if prior is not None and prior != item:
            raise OnlyMemoryProjectionError("PROJECTION_SOURCE_CONFLICT")
        indexed[key] = item
    cut_refs = {cut.source_family: cut for cut in manifest.cuts}
    for item in indexed.values():
        cut = cut_refs.get(item.source_family)
        if (
            cut is None
            or item.cut_fingerprint != cut.cut_fingerprint
            or item.source_schema_version != cut.source_schema_version
        ):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")

    by_family: dict[str, list[OnlySourceObservationV1]] = defaultdict(list)
    for item in indexed.values():
        by_family[item.source_family].append(item)
    by_locator = {family: {o.locator: o for o in items} for family, items in by_family.items()}
    by_identity = {family: {o.identity: o for o in items} for family, items in by_family.items()}
    records: list[OnlyMemoryProjectionRecordV1] = []

    def exact(kind: OnlyMemoryReferenceKind, identity: object) -> Mapping[str, object] | None:
        if not isinstance(identity, str) or not identity:
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
        try:
            return verify_exact_reference(kind, identity)
        except Exception as exc:
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE") from exc

    experiments = by_locator.get("SEARCH_PROVENANCE", {})
    results = by_locator.get("RESEARCH_RESULT", {})
    stats: dict[tuple[str, str], OnlySourceObservationV1] = {}
    for family in ("RESEARCH_STATISTICS", "RESEARCH_FACTOR_PAIR_STATISTICS", "RESEARCH_SUMMARY_STATISTICS"):
        for observation in by_family[family]:
            key = (
                str(_payload(observation).get("statistics_fingerprint")),
                str(_payload(observation).get("statistics_result_fingerprint")),
            )
            if key in stats and stats[key] != observation:
                raise OnlyMemoryProjectionError("PROJECTION_SOURCE_CONFLICT")
            stats[key] = observation
    qualifications = by_identity.get("QUALIFICATION_DECISION", {})
    result_by_plan: dict[str, OnlySourceObservationV1] = {}
    for search_result in by_family["SEARCH_PROVENANCE"]:
        if search_result.locator.startswith("iteration-results/"):
            plan_identity = str(_payload(search_result).get("iteration_plan_fingerprint"))
            if plan_identity in result_by_plan:
                raise OnlyMemoryProjectionError("PROJECTION_SOURCE_CONFLICT")
            result_by_plan[plan_identity] = search_result
    search_lineages = _search_lineages(by_family, experiments, result_by_plan)
    result_identities = frozenset(by_identity.get("RESEARCH_RESULT", {}))
    run_occurrences = {
        run.locator: _build_run_occurrence_closure(run, exact, search_lineages, result_identities)
        for run in by_family["RESEARCH_RUN"]
    }
    for item in sorted(by_family["SEARCH_PROVENANCE"], key=lambda o: o.locator):
        payload = _payload(item)
        if item.locator.startswith("experiments/"):
            exact(OnlyMemoryReferenceKind.DATASET_SNAPSHOT, payload.get("dataset_snapshot_fingerprint"))
            exact(OnlyMemoryReferenceKind.CATALOG_GENERATION, payload.get("catalog_generation_fingerprint"))
            algorithm = payload.get("search_algorithm_binding")
            if isinstance(algorithm, Mapping):
                exact(OnlyMemoryReferenceKind.SEARCH_ALGORITHM, algorithm.get("implementation_fingerprint"))
            space = payload.get("search_space_reference")
            if isinstance(space, Mapping):
                exact(OnlyMemoryReferenceKind.SEARCH_SPACE, space.get("search_space_fingerprint"))
            evaluation = payload.get("evaluation_context_reference")
            if isinstance(evaluation, Mapping):
                exact(OnlyMemoryReferenceKind.EVALUATION_CONTRACT, evaluation.get("evaluation_fingerprint"))
            policy = payload.get("search_policy_reference")
            if isinstance(policy, Mapping):
                exact(OnlyMemoryReferenceKind.SEARCH_POLICY, policy.get("policy_fingerprint"))
            hypothesis = payload.get("hypothesis")
            parent = payload.get("parent_experiment_fingerprint")
            if parent is not None:
                _required_member(experiments, f"experiments/{parent}")
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "ExperimentProjectionRecord",
                    {
                        "experiment_fingerprint": item.identity,
                        "parent_experiment_fingerprint": parent,
                        "hypothesis_fingerprint": hypothesis.get("hypothesis_fingerprint")
                        if isinstance(hypothesis, Mapping)
                        else None,
                        "dataset_snapshot_fingerprint": payload["dataset_snapshot_fingerprint"],
                        "catalog_generation_fingerprint": payload["catalog_generation_fingerprint"],
                        "search_space_reference": payload.get("search_space_reference"),
                        "evaluation_context_reference": evaluation,
                        "search_algorithm_binding": payload.get("search_algorithm_binding"),
                        "search_policy_reference": payload.get("search_policy_reference"),
                        "search_budget": payload.get("search_budget"),
                    },
                    _ref(item),
                )
            )
        elif item.locator.startswith("iteration-plans/"):
            experiment = _required_member(experiments, f"experiments/{payload.get('experiment_fingerprint')}")
            parent_result = payload.get("parent_iteration_result_fingerprint")
            if parent_result is not None:
                _required_member(experiments, f"iteration-results/{parent_result}")
            proposal_kind = _reference_kind(payload.get("proposal_kind"))
            if proposal_kind not in {
                OnlyMemoryReferenceKind.ONLY_SYMBOLIC_GRAPH_PROPOSAL,
                OnlyMemoryReferenceKind.ONLY_PARAMETER_GRAPH_PROPOSAL,
            }:
                raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            proposal = exact(proposal_kind, payload.get("proposal_fingerprint"))
            terminal = result_by_plan.get(item.identity)
            terminal_payload = _payload(terminal) if terminal is not None else {}
            source_refs = list(_ref(item) + _ref(experiment))
            result_ref = terminal_payload.get("research_result_reference")
            if terminal is not None:
                source_refs.extend(_ref(terminal))
            if isinstance(result_ref, Mapping):
                source_refs.extend(
                    _ref(
                        _required_member(
                            results,
                            result_ref.get("locator_fingerprint"),
                            result_identity=result_ref.get("result_fingerprint"),
                        )
                    )
                )
            decision = terminal_payload.get("qualification_decision_fingerprint")
            if decision is not None:
                source_refs.extend(_ref(_required_member(qualifications, decision)))
            status = (
                "COMPLETED_EVIDENCE"
                if isinstance(result_ref, Mapping)
                else "OPERATIONAL_FAILURE"
                if terminal_payload.get("research_attempted")
                else "EXPLICITLY_EXCLUDED"
                if terminal_payload.get("disposition") == "SKIPPED"
                else "PLANNED"
            )
            parameter: dict[str, object] = {}
            if proposal_kind is OnlyMemoryReferenceKind.ONLY_PARAMETER_GRAPH_PROPOSAL:
                space = _payload(experiment).get("search_space_reference")
                ordinal = proposal.get("ordinal") if isinstance(proposal, Mapping) else None
                if (
                    not isinstance(proposal, Mapping)
                    or not isinstance(space, Mapping)
                    or proposal.get("proposal_fingerprint") != payload.get("proposal_fingerprint")
                    or proposal.get("search_space_fingerprint") != space.get("search_space_fingerprint")
                    or type(ordinal) is not int
                    or ordinal < 0
                    or not isinstance(proposal.get("assignment"), list)
                ):
                    raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
                parameter = {
                    "search_space_fingerprint": proposal["search_space_fingerprint"],
                    "normalized_assignment": proposal["assignment"],
                    "grid_ordinal": proposal["ordinal"],
                }
            search_method = (
                "PARAMETER" if proposal_kind is OnlyMemoryReferenceKind.ONLY_PARAMETER_GRAPH_PROPOSAL else "SYMBOLIC"
            )
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "ParameterObservationProjectionRecord",
                    {
                        "search_method": search_method,
                        "experiment_fingerprint": payload["experiment_fingerprint"],
                        "dataset_snapshot_fingerprint": _payload(experiment).get("dataset_snapshot_fingerprint"),
                        "catalog_generation_fingerprint": _payload(experiment).get("catalog_generation_fingerprint"),
                        "evaluation_context_reference": _payload(experiment).get("evaluation_context_reference"),
                        "search_algorithm_binding": _payload(experiment).get("search_algorithm_binding"),
                        "search_policy_reference": _payload(experiment).get("search_policy_reference"),
                        "search_budget": _payload(experiment).get("search_budget"),
                        "iteration_plan_fingerprint": item.identity,
                        "iteration_index": payload.get("iteration_index"),
                        "proposal_fingerprint": payload.get("proposal_fingerprint"),
                        "iteration_result_fingerprint": terminal.identity if terminal is not None else None,
                        "research_result_reference": result_ref,
                        "qualification_decision_fingerprint": decision,
                        "status": status,
                        **parameter,
                    },
                    tuple(sorted(set(source_refs), key=lambda r: (r.source_family, r.locator))),
                )
            )
        elif item.locator.startswith("iteration-results/"):
            _required_member(experiments, f"iteration-plans/{payload.get('iteration_plan_fingerprint')}")
            if payload.get("failure_code") is not None:
                records.append(
                    OnlyMemoryProjectionRecordV1(
                        "FailureEvidenceProjectionRecord",
                        {
                            "owner_kind": "SEARCH_OCCURRENCE",
                            "classification": "OPERATIONAL_FAILURE"
                            if payload.get("research_attempted")
                            else "SEARCH_OR_BUDGET_STOP",
                            "failure_code": payload["failure_code"],
                            "iteration_result_fingerprint": item.identity,
                        },
                        _ref(item),
                    )
                )

    for item in by_family["AGENT_PROVENANCE"]:
        payload = _payload(item)
        if item.locator.startswith("launch-records/") and payload.get("child_search_experiment_fingerprint"):
            experiment = _required_member(experiments, f"experiments/{payload['child_search_experiment_fingerprint']}")
            agent_facts = by_identity["AGENT_PROVENANCE"]
            session = _required_member(agent_facts, payload.get("agent_session_fingerprint"))
            decision = _required_member(agent_facts, payload.get("agent_decision_fingerprint"))
            tool_result = _required_member(agent_facts, payload.get("tool_call_result_fingerprint"))
            if (
                not session.locator.startswith("sessions/")
                or not decision.locator.startswith("decisions/")
                or not tool_result.locator.startswith("tool-calls/results/")
            ):
                raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "ExperimentProjectionRecord",
                    {
                        "experiment_fingerprint": experiment.identity,
                        "agent_session_ref": payload.get("agent_session_fingerprint"),
                        "agent_launch_ref": item.identity,
                    },
                    _ref(item) + _ref(experiment) + _ref(session) + _ref(decision) + _ref(tool_result),
                )
            )
        if item.locator in {
            "model-calls/results/" + item.identity,
            "tool-calls/results/" + item.identity,
        } and payload.get("failure_code"):
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "FailureEvidenceProjectionRecord",
                    {
                        "owner_kind": "AGENT_OCCURRENCE",
                        "classification": "OPERATIONAL_FAILURE",
                        "failure_code": payload["failure_code"],
                        "outcome": payload.get("outcome"),
                    },
                    _ref(item),
                )
            )

    for item in by_family["RESEARCH_RESULT"]:
        payload = _payload(item)
        exact(OnlyMemoryReferenceKind.DATASET_SNAPSHOT, payload.get("dataset_snapshot_fingerprint"))
        references = list(_ref(item))
        statistics_refs = payload.get("statistics_results", [])
        if not isinstance(statistics_refs, list):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        for ref in statistics_refs:
            if not isinstance(ref, Mapping):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            key = str(ref.get("statistics_fingerprint")), str(ref.get("statistics_result_fingerprint"))
            if key not in stats:
                raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
        plan = payload.get("plan")
        if not isinstance(plan, Mapping):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        candidates = plan.get("candidates", [])
        if not isinstance(candidates, list):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        linked_runs = tuple(
            run
            for run in by_family["RESEARCH_RUN"]
            if _payload(run).get("research_result_fingerprint") == item.identity
        )
        linked_search = tuple(
            search
            for search in by_family["SEARCH_PROVENANCE"]
            if search.locator.startswith("iteration-results/")
            and isinstance((reference := _payload(search).get("research_result_reference")), Mapping)
            and reference.get("result_fingerprint") == item.identity
        )
        for run in linked_runs:
            references.extend(run_occurrences[run.locator][1])
        search_experiments: list[OnlySourceObservationV1] = []
        for search in linked_search:
            references.extend(_ref(search))
            search_plan = _required_member(
                experiments, f"iteration-plans/{_payload(search).get('iteration_plan_fingerprint')}"
            )
            search_experiment = _required_member(
                experiments, f"experiments/{_payload(search_plan).get('experiment_fingerprint')}"
            )
            references.extend(_ref(search_plan) + _ref(search_experiment))
            search_experiments.append(search_experiment)
        authoring = [
            _payload(run).get("authoring_provenance")
            for run in linked_runs
            if isinstance(_payload(run).get("authoring_provenance"), Mapping)
        ]
        run_closures = [run_occurrences[run.locator][0] for run in linked_runs]
        run_closures.sort(
            key=lambda closure: (
                str(closure["run_id"]),
                cast(int, closure["run_revision"]),
                cast(Mapping[str, str], closure["run_source_ref"])["locator"],
            )
        )
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            membership = candidate.get("statistics_fingerprints", [])
            if not isinstance(membership, list):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            candidate_statistics = [
                reference
                for reference in statistics_refs
                if isinstance(reference, Mapping) and reference.get("statistics_fingerprint") in membership
            ]
            if len(candidate_statistics) != len(membership):
                raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
            candidate_refs = list(references)
            for reference in candidate_statistics:
                key = str(reference["statistics_fingerprint"]), str(reference["statistics_result_fingerprint"])
                candidate_refs.extend(_ref(stats[key]))
            graph = candidate.get("graph_fingerprint")
            exact(OnlyMemoryReferenceKind.CALCULATION_GRAPH, graph)
            series = [
                s
                for s in (*plan.get("published_series", []), *plan.get("signals", []))
                if isinstance(s, Mapping) and s.get("candidate_fingerprint") == candidate.get("candidate_fingerprint")
            ]
            if not series:
                raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            seen_outputs: set[tuple[object, object]] = set()
            for output in series:
                output_key = output.get("node_fingerprint"), output.get("output_name")
                if output_key in seen_outputs:
                    continue
                seen_outputs.add(output_key)
                records.append(
                    OnlyMemoryProjectionRecordV1(
                        "EvaluationProjectionRecord",
                        {
                            "candidate_fingerprint": candidate.get("candidate_fingerprint"),
                            "graph_fingerprint": graph,
                            "candidate_node_fingerprint": output.get("node_fingerprint"),
                            "output_name": output.get("output_name"),
                            "dataset_snapshot_fingerprint": payload["dataset_snapshot_fingerprint"],
                            "research_run_refs": sorted({str(_payload(run).get("run_id")) for run in linked_runs}),
                            "run_evaluation_closures": run_closures,
                            "specification_refs": sorted(
                                {str(_payload(run).get("specification_fingerprint")) for run in linked_runs}
                            ),
                            "search_experiment_refs": sorted({search.identity for search in search_experiments}),
                            "catalog_generation_refs": sorted(
                                {
                                    str(_payload(search).get("catalog_generation_fingerprint"))
                                    for search in search_experiments
                                }
                                | {
                                    str(value.get("catalog_generation_fingerprint"))
                                    for value in authoring
                                    if isinstance(value, Mapping)
                                }
                            ),
                            "authoring_generation_refs": sorted(
                                {
                                    str(value.get("execution_generation_fingerprint"))
                                    for value in authoring
                                    if isinstance(value, Mapping)
                                }
                            ),
                            "runtime_generation_refs": sorted(
                                {str(closure["runtime_generation_fingerprint"]) for closure in run_closures}
                            ),
                            "research_result_locator": item.locator,
                            "research_result_fingerprint": item.identity,
                            "statistics_references": candidate_statistics,
                        },
                        tuple(sorted(set(candidate_refs), key=lambda r: (r.source_family, r.locator))),
                    )
                )

    for item in by_family["RESEARCH_SUMMARY_STATISTICS"]:
        payload = _payload(item)
        upstream = payload.get("upstream_statistics_references")
        if upstream is not None:
            if (
                not isinstance(upstream, Mapping)
                or not isinstance(upstream.get("focal"), Mapping)
                or not isinstance(upstream.get("neighbors"), list)
            ):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            dependencies = [upstream["focal"], *upstream["neighbors"]]
        else:
            dependencies = [
                {
                    "statistics_fingerprint": payload.get("source_statistics_fingerprint"),
                    "statistics_result_fingerprint": payload.get("source_statistics_result_fingerprint"),
                }
            ]
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            key = str(dependency.get("statistics_fingerprint")), str(dependency.get("statistics_result_fingerprint"))
            source = stats.get(key)
            if source is None or source == item:
                raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")

    for item in by_family["RESEARCH_RUN"]:
        payload = _payload(item)
        if payload.get("state") in {"FAILED", "CANCELLED"}:
            run_context, failure_source_refs = run_occurrences[item.locator]
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "FailureEvidenceProjectionRecord",
                    {
                        "owner_kind": "RESEARCH_RUN",
                        "classification": "OPERATIONAL_FAILURE",
                        "run_context": run_context,
                        "failure_phase": payload.get("failure_phase"),
                        "failure_code": payload.get("failure_code"),
                        "failure_detail": payload.get("failure_detail"),
                    },
                    failure_source_refs,
                )
            )

    run_ids = {str(_payload(run).get("run_id")) for run in by_family["RESEARCH_RUN"]}
    for item in by_family["RESEARCH_ATTEMPT"]:
        if _payload(item).get("run_id") not in run_ids:
            raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")

    for item in by_family["QUALIFICATION_DECISION"]:
        payload = _payload(item)
        policy = exact(
            OnlyMemoryReferenceKind.QUALIFICATION_POLICY,
            str(payload.get("policy_id")) + ":" + str(payload.get("policy_version")),
        )
        if isinstance(policy, Mapping) and policy.get("policy_fingerprint") != payload.get("policy_fingerprint"):
            raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
        refs = list(_ref(item))
        for proof in evidence:
            if not isinstance(proof, Mapping):
                raise OnlyMemoryProjectionError("SOURCE_OBSERVATION_MISMATCH")
            if proof.get("kind") == "RESEARCH_RESULT":
                result = _required_member(
                    results, proof.get("locator_fingerprint"), result_identity=proof.get("evidence_fingerprint")
                )
                refs.extend(_ref(result))
            else:
                exact(OnlyMemoryReferenceKind.QUALIFICATION_EVIDENCE, proof.get("evidence_fingerprint"))
        if payload.get("outcome") == "REJECTED":
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "FailureEvidenceProjectionRecord",
                    {
                        "owner_kind": "QUALIFICATION_DECISION",
                        "classification": "QUALIFICATION_REJECT",
                        "subject_strategy_fingerprint": payload.get("subject_strategy_fingerprint"),
                        "policy_id": payload.get("policy_id"),
                        "policy_version": payload.get("policy_version"),
                        "policy_fingerprint": payload.get("policy_fingerprint"),
                        "evidence_refs": evidence,
                    },
                    tuple(sorted(set(refs), key=lambda r: (r.source_family, r.locator))),
                )
            )

    ordered = tuple(sorted(records, key=lambda r: only_canonical_json(r.to_dict())))
    return OnlyExperimentMemoryProjectionV1(manifest, ordered)
