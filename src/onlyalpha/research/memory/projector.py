"""Pure, non-authoritative projection of exact cut-bound source observations."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.source_cut import OnlySourceClosedCutV1, OnlySourceCutError, OnlySourceObservationV1

from .source_manifest import (
    MANDATORY_FAMILIES,
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)

PROJECTION_SCHEMA_VERSION = 1
PROJECTOR_ALGORITHM_VERSION = 1


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

    def exact(kind: str, identity: object) -> Mapping[str, object] | None:
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
    for item in sorted(by_family["SEARCH_PROVENANCE"], key=lambda o: o.locator):
        payload = _payload(item)
        if item.locator.startswith("experiments/"):
            exact("DATASET_SNAPSHOT", payload.get("dataset_snapshot_fingerprint"))
            exact("CATALOG_GENERATION", payload.get("catalog_generation_fingerprint"))
            algorithm = payload.get("search_algorithm_binding")
            if isinstance(algorithm, Mapping):
                exact("SEARCH_ALGORITHM", algorithm.get("implementation_fingerprint"))
            space = payload.get("search_space_reference")
            if isinstance(space, Mapping):
                exact("SEARCH_SPACE", space.get("search_space_fingerprint"))
            evaluation = payload.get("evaluation_context_reference")
            if isinstance(evaluation, Mapping):
                exact("EVALUATION_CONTRACT", evaluation.get("evaluation_fingerprint"))
            policy = payload.get("search_policy_reference")
            if isinstance(policy, Mapping):
                exact("SEARCH_POLICY", policy.get("policy_fingerprint"))
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
            proposal_kind = payload.get("proposal_kind")
            proposal = exact(str(proposal_kind), payload.get("proposal_fingerprint"))
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
            if proposal_kind == "ONLY_PARAMETER_GRAPH_PROPOSAL":
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
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "ParameterObservationProjectionRecord",
                    {
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
                        "classification": "OPERATIONAL_FAILURE",
                        "failure_code": payload["failure_code"],
                        "outcome": payload.get("outcome"),
                    },
                    _ref(item),
                )
            )

    for item in by_family["RESEARCH_RESULT"]:
        payload = _payload(item)
        exact("DATASET_SNAPSHOT", payload.get("dataset_snapshot_fingerprint"))
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
            references.extend(_ref(run))
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
        work_bindings: list[str] = []
        for run in linked_runs:
            binding = exact("RUNTIME_WORK_BINDING", _payload(run).get("run_id"))
            generation = binding.get("runtime_generation_fingerprint") if isinstance(binding, Mapping) else None
            if not isinstance(generation, str):
                raise OnlyMemoryProjectionError("REFERENCE_AUTHORITY_UNAVAILABLE")
            work_bindings.append(generation)
        for provenance in authoring:
            if isinstance(provenance, Mapping):
                exact("AUTHORING_GENERATION", provenance.get("execution_generation_fingerprint"))
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
            exact("CALCULATION_GRAPH", graph)
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
                            "runtime_generation_refs": sorted(set(work_bindings)),
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
        exact("RESEARCH_SPECIFICATION", payload.get("specification_fingerprint"))
        result_identity = payload.get("research_result_fingerprint")
        if result_identity is not None and result_identity not in by_identity.get("RESEARCH_RESULT", {}):
            raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
        if payload.get("state") in {"FAILED", "CANCELLED"}:
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "FailureEvidenceProjectionRecord",
                    {
                        "classification": "OPERATIONAL_FAILURE",
                        "run_id": payload.get("run_id"),
                        "revision": payload.get("revision"),
                        "failure_phase": payload.get("failure_phase"),
                        "failure_code": payload.get("failure_code"),
                    },
                    _ref(item),
                )
            )

    run_ids = {str(_payload(run).get("run_id")) for run in by_family["RESEARCH_RUN"]}
    for item in by_family["RESEARCH_ATTEMPT"]:
        if _payload(item).get("run_id") not in run_ids:
            raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")

    admissions = {str(_payload(item).get("command_id")): item for item in by_family["PRODUCT_COMMAND_ADMISSION"]}

    for item in by_family["PRODUCT_COMMAND_RECEIPT"]:
        payload = _payload(item)
        admission = admissions.get(str(payload.get("command_id")))
        if admission is None or _payload(admission).get("command_fingerprint") != payload.get("command_fingerprint"):
            raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")
        if payload.get("outcome_kind") == "RESEARCH_RUN":
            run_id = payload.get("outcome_id")
            if run_id not in run_ids:
                raise OnlyMemoryProjectionError("CROSS_SOURCE_CLOSURE_INCOMPLETE")

    for item in by_family["QUALIFICATION_DECISION"]:
        payload = _payload(item)
        policy = exact("QUALIFICATION_POLICY", str(payload.get("policy_id")) + ":" + str(payload.get("policy_version")))
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
                exact("QUALIFICATION_EVIDENCE", proof.get("evidence_fingerprint"))
        if payload.get("outcome") == "REJECTED":
            records.append(
                OnlyMemoryProjectionRecordV1(
                    "FailureEvidenceProjectionRecord",
                    {
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
