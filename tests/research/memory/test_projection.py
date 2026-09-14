"""Hermetic closure, deterministic identity and disposable-revision regression tests."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.memory.projector import (
    only_build_experiment_memory_projection,
    only_project_experiment_memory,
)
from onlyalpha.research.memory.source_manifest import (
    MANDATORY_FAMILIES,
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.source_cut import (
    OnlySourceClosedCutV1,
    OnlySourceCutEntryV1,
    OnlySourceCutError,
    OnlySourceObservationV1,
    _OnlyFileSourceCutAuthority,
)


@dataclass
class _Reader:
    cut: OnlySourceClosedCutV1
    observations: tuple[OnlySourceObservationV1, ...] = ()

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        assert fingerprint == self.cut.cut_fingerprint
        return self.cut

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]:
        assert fingerprint == self.cut.cut_fingerprint
        return self.observations


def _empty_readers() -> dict[str, _Reader]:
    return {family: _Reader(OnlySourceClosedCutV1(family, 1, ())) for family in MANDATORY_FAMILIES}


def _with_fact(reader: _Reader, locator: str, identity: str, payload: dict[str, object]) -> None:
    digest = only_canonical_fingerprint(payload)
    reader.cut = OnlySourceClosedCutV1(reader.cut.source_family, 1, (OnlySourceCutEntryV1(locator, identity, digest),))
    reader.observations = (
        OnlySourceObservationV1(
            reader.cut.source_family, 1, reader.cut.cut_fingerprint, locator, identity, digest, payload
        ),
    )


def _set_facts(reader: _Reader, facts: list[tuple[str, str, dict[str, object]]]) -> None:
    entries = tuple(
        sorted(
            (
                OnlySourceCutEntryV1(locator, identity, only_canonical_fingerprint(payload))
                for locator, identity, payload in facts
            ),
            key=lambda entry: entry.locator,
        )
    )
    reader.cut = OnlySourceClosedCutV1(reader.cut.source_family, 1, entries)
    reader.observations = tuple(
        OnlySourceObservationV1(
            reader.cut.source_family,
            1,
            reader.cut.cut_fingerprint,
            locator,
            identity,
            only_canonical_fingerprint(payload),
            payload,
        )
        for locator, identity, payload in facts
    )


def _build(readers: dict[str, _Reader]):
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    return only_build_experiment_memory_projection(manifest, readers, lambda _kind, _identity: None)


def test_certified_empty_and_missing_family_are_different() -> None:
    readers = _empty_readers()
    projection = _build(readers)
    assert projection.records == ()
    with pytest.raises(OnlyMemoryProjectionError, match="SOURCE_CUT_MISSING"):
        OnlyExperimentMemorySourceCutManifestV1.from_cuts(
            [reader.cut for family, reader in readers.items() if family != "QUALIFICATION_DECISION"]
        )


def test_file_owner_observation_rechecks_exact_member(tmp_path: Path) -> None:
    payload: dict[str, object] = {"value": "first"}
    owner = _OnlyFileSourceCutAuthority(
        tmp_path / "source",
        "SEARCH_PROVENANCE",
        1,
        lambda: ("a" * 64,),
        lambda locator: (locator, payload),
    )
    cut = owner.capture_closed_cut()
    assert owner.iter_closed_cut_observations_verified(cut.cut_fingerprint)[0].canonical_payload == payload
    payload = {"value": "changed"}
    with pytest.raises(OnlySourceCutError, match="SOURCE_CUT_CORRUPT"):
        owner.iter_closed_cut_observations_verified(cut.cut_fingerprint)


@pytest.mark.recovery
def test_same_input_order_rebuild_and_immutable_store(tmp_path: Path) -> None:
    readers = _empty_readers()
    identity = "a" * 64
    _with_fact(
        readers["SEARCH_PROVENANCE"],
        f"experiments/{identity}",
        identity,
        {
            "dataset_snapshot_fingerprint": "b" * 64,
            "catalog_generation_fingerprint": "c" * 64,
            "parent_experiment_fingerprint": None,
        },
    )
    p1 = _build(readers)
    p2 = _build(dict(reversed(list(readers.items()))))
    assert p1.to_dict() == p2.to_dict()
    first = p1.records[0].facets
    first["dataset_snapshot_fingerprint"] = "0" * 64
    assert p1.logical_digest == p2.logical_digest
    manifest = p1.source_manifest
    duplicated = readers["SEARCH_PROVENANCE"].observations * 2
    assert only_project_experiment_memory(manifest, duplicated, lambda *_: None) == p1
    root = tmp_path / "experiment-memory"
    store = OnlyExperimentMemoryRevisionStore(root)
    assert store.publish_and_activate(p1.source_manifest, readers, lambda *_: None) == p1.revision_fingerprint
    assert OnlyExperimentMemoryRevisionStore(root).load_active_verified() == p1
    program = (
        "import sys\n"
        "from pathlib import Path\n"
        "from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore\n"
        "print(OnlyExperimentMemoryRevisionStore(Path(sys.argv[1])).load_active_verified().logical_digest)\n"
    )
    assert subprocess.check_output([sys.executable, "-c", program, str(root)], text=True).strip() == p1.logical_digest
    assert store.publish_and_activate(p1.source_manifest, readers, lambda *_: None) == p1.revision_fingerprint
    source_digest = readers["SEARCH_PROVENANCE"].cut.cut_fingerprint
    # Deletion is confined to the test's derived root; owning readers remain intact.
    import shutil

    shutil.rmtree(root)
    assert _build(readers).logical_digest == p1.logical_digest
    assert _build(readers).revision_fingerprint == p1.revision_fingerprint
    assert readers["SEARCH_PROVENANCE"].load_closed_cut_verified(source_digest).cut_fingerprint == source_digest


def test_conflicting_locator_and_cut_member_omission_fail_closed() -> None:
    readers = _empty_readers()
    identity = "a" * 64
    _with_fact(
        readers["SEARCH_PROVENANCE"],
        f"experiments/{identity}",
        identity,
        {
            "dataset_snapshot_fingerprint": "b" * 64,
            "catalog_generation_fingerprint": "c" * 64,
        },
    )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    item = readers["SEARCH_PROVENANCE"].observations[0]
    conflicting_payload = {**item.canonical_payload, "another": "value"}
    conflict = OnlySourceObservationV1(
        item.source_family,
        1,
        item.cut_fingerprint,
        item.locator,
        item.identity,
        only_canonical_fingerprint(conflicting_payload),
        conflicting_payload,
    )
    with pytest.raises(OnlyMemoryProjectionError, match="PROJECTION_SOURCE_CONFLICT"):
        only_project_experiment_memory(manifest, (item, conflict), lambda *_: None)
    readers["SEARCH_PROVENANCE"].observations = ()
    with pytest.raises(OnlyMemoryProjectionError, match="SOURCE_OBSERVATION_MISMATCH"):
        _build(readers)


@pytest.mark.recovery
def test_crash_before_activation_and_corruption(tmp_path: Path) -> None:
    readers = _empty_readers()
    p1 = _build(readers)
    store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    store.publish_and_activate(p1.source_manifest, readers, lambda *_: None)
    identity = "a" * 64
    _with_fact(
        readers["SEARCH_PROVENANCE"],
        f"experiments/{identity}",
        identity,
        {
            "dataset_snapshot_fingerprint": "b" * 64,
            "catalog_generation_fingerprint": "c" * 64,
        },
    )
    p2 = _build(readers)
    with pytest.raises(OnlyMemoryProjectionError, match="PROJECTION_ACTIVATION_FAILED"):
        store.publish_and_activate(
            p2.source_manifest,
            readers,
            lambda *_: None,
            before_activation=lambda: (_ for _ in ()).throw(RuntimeError("crash")),
        )
    assert OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory").load_active_verified() == p1
    staged = tmp_path / "experiment-memory" / "revisions" / "sha256" / p2.revision_fingerprint[:2] / ".stage-crashed"
    staged.mkdir()
    (staged / "projection.json").write_text("{}", encoding="utf-8")
    assert OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory").load_active_verified() == p1
    target = (
        tmp_path / "experiment-memory" / "revisions" / "sha256" / p1.revision_fingerprint[:2] / p1.revision_fingerprint
    )
    (target / "projection.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OnlyMemoryProjectionError, match="PROJECTION_CORRUPT"):
        store.load_active_verified()
    (target / "projection.json").unlink()
    (target / "projection.json").symlink_to(staged / "projection.json")
    with pytest.raises(OnlyMemoryProjectionError, match="PROJECTION_CORRUPT"):
        store.load_verified(p1.revision_fingerprint)


def test_current_research_result_outside_selected_cut_cannot_close_search_reference() -> None:
    readers = _empty_readers()
    experiment = "a" * 64
    plan = "b" * 64
    result = "c" * 64
    _set_facts(
        readers["SEARCH_PROVENANCE"],
        [
            (
                f"experiments/{experiment}",
                experiment,
                {
                    "dataset_snapshot_fingerprint": "d" * 64,
                    "catalog_generation_fingerprint": "e" * 64,
                },
            ),
            (
                f"iteration-plans/{plan}",
                plan,
                {
                    "experiment_fingerprint": experiment,
                    "proposal_kind": "ONLY_SYMBOLIC_GRAPH_PROPOSAL",
                    "proposal_fingerprint": "f" * 64,
                    "iteration_index": 0,
                },
            ),
            (
                f"iteration-results/{result}",
                result,
                {
                    "iteration_plan_fingerprint": plan,
                    "research_attempted": True,
                    "research_result_reference": {"locator_fingerprint": "1" * 64, "result_fingerprint": "2" * 64},
                },
            ),
        ],
    )
    with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
        _build(readers)


def test_agent_launch_requires_session_decision_and_tool_result_inside_selected_cut() -> None:
    readers = _empty_readers()
    experiment = "a" * 64
    _with_fact(
        readers["SEARCH_PROVENANCE"],
        f"experiments/{experiment}",
        experiment,
        {"dataset_snapshot_fingerprint": "b" * 64, "catalog_generation_fingerprint": "c" * 64},
    )
    launch = "d" * 64
    session, decision, tool = "e" * 64, "f" * 64, "1" * 64
    facts = [
        (
            f"launch-records/{launch}",
            launch,
            {
                "child_search_experiment_fingerprint": experiment,
                "agent_session_fingerprint": session,
                "agent_decision_fingerprint": decision,
                "tool_call_result_fingerprint": tool,
            },
        )
    ]
    _set_facts(readers["AGENT_PROVENANCE"], facts)
    with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
        _build(readers)
    _set_facts(
        readers["AGENT_PROVENANCE"],
        [
            *facts,
            (f"sessions/{session}", session, {}),
            (f"decisions/{decision}", decision, {}),
            (f"tool-calls/results/{tool}", tool, {}),
        ],
    )
    projection = _build(readers)
    launch_record = next(record for record in projection.records if record.facets.get("agent_launch_ref") == launch)
    assert len(launch_record.source_refs) == 5


def test_failure_is_operational_and_exact_reference_failure_blocks() -> None:
    readers = _empty_readers()
    experiment = "a" * 64
    _with_fact(
        readers["SEARCH_PROVENANCE"],
        f"experiments/{experiment}",
        experiment,
        {
            "dataset_snapshot_fingerprint": "d" * 64,
            "catalog_generation_fingerprint": "e" * 64,
        },
    )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        only_build_experiment_memory_projection(manifest, readers, lambda *_: (_ for _ in ()).throw(KeyError()))


def test_same_graph_output_on_two_datasets_keeps_distinct_evaluation_contexts() -> None:
    readers = _empty_readers()
    graph = "a" * 64
    node = "c" * 64
    facts = []
    for digit, dataset in (("1", "d" * 64), ("2", "e" * 64)):
        locator, identity = digit * 64, digit * 64
        candidate = digit * 64
        facts.append(
            (
                locator,
                identity,
                {
                    "dataset_snapshot_fingerprint": dataset,
                    "plan": {
                        "candidates": [{"candidate_fingerprint": candidate, "graph_fingerprint": graph}],
                        "published_series": [
                            {
                                "candidate_fingerprint": candidate,
                                "node_fingerprint": node,
                                "output_name": "factor_value",
                            }
                        ],
                    },
                    "statistics_results": [],
                },
            )
        )
    _set_facts(readers["RESEARCH_RESULT"], facts)
    records = [r.facets for r in _build(readers).records if r.kind == "EvaluationProjectionRecord"]
    assert len(records) == 2
    assert {(r["graph_fingerprint"], r["candidate_node_fingerprint"], r["output_name"]) for r in records} == {
        (graph, node, "factor_value")
    }
    assert {r["dataset_snapshot_fingerprint"] for r in records} == {"d" * 64, "e" * 64}


def test_model_failure_is_operational_not_scientific_rejection() -> None:
    readers = _empty_readers()
    identity = "a" * 64
    _with_fact(
        readers["AGENT_PROVENANCE"],
        f"model-calls/results/{identity}",
        identity,
        {
            "outcome": "FAILED",
            "failure_code": "AGENT_MODEL_CALL_FAILED",
        },
    )
    records = [r for r in _build(readers).records if r.kind == "FailureEvidenceProjectionRecord"]
    assert len(records) == 1
    assert records[0].facets["classification"] == "OPERATIONAL_FAILURE"
    assert all(r.facets.get("classification") != "SCIENTIFIC_REJECTION" for r in records)


def test_parameter_observations_do_not_infer_an_unseen_grid_cell() -> None:
    readers = _empty_readers()
    experiment = "a" * 64
    space = "b" * 64
    facts: list[tuple[str, str, dict[str, object]]] = [
        (
            f"experiments/{experiment}",
            experiment,
            {
                "dataset_snapshot_fingerprint": "c" * 64,
                "catalog_generation_fingerprint": "d" * 64,
                "search_space_reference": {"search_space_fingerprint": space},
            },
        )
    ]
    proposals: dict[str, dict[str, object]] = {}
    for iteration_index, ordinal in enumerate((0, 1, 3)):
        identity = str(ordinal + 1) * 64
        proposal = str(ordinal + 5) * 64
        proposals[proposal] = {
            "proposal_fingerprint": proposal,
            "search_space_fingerprint": space,
            "ordinal": ordinal,
            "assignment": [{"target": "window", "value": ordinal}],
        }
        facts.append(
            (
                f"iteration-plans/{identity}",
                identity,
                {
                    "experiment_fingerprint": experiment,
                    "iteration_index": iteration_index,
                    "proposal_kind": "ONLY_PARAMETER_GRAPH_PROPOSAL",
                    "proposal_fingerprint": proposal,
                },
            )
        )
    _set_facts(readers["SEARCH_PROVENANCE"], facts)
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    projection = only_build_experiment_memory_projection(
        manifest,
        readers,
        lambda kind, identity: proposals[identity] if kind == "ONLY_PARAMETER_GRAPH_PROPOSAL" else None,
    )
    cells = [r.facets["grid_ordinal"] for r in projection.records if r.kind == "ParameterObservationProjectionRecord"]
    assert cells == [0, 1, 3]
    readers["SEARCH_PROVENANCE"].observations = tuple(reversed(readers["SEARCH_PROVENANCE"].observations))
    reordered = only_build_experiment_memory_projection(
        manifest,
        readers,
        lambda kind, identity: proposals[identity] if kind == "ONLY_PARAMETER_GRAPH_PROPOSAL" else None,
    )
    assert reordered.logical_digest == projection.logical_digest
    assert reordered.revision_fingerprint == projection.revision_fingerprint


def test_qualification_rejection_is_exact_context_not_global_factor_status() -> None:
    readers = _empty_readers()
    result_locator, result_identity, decision_identity = "a" * 64, "b" * 64, "c" * 64
    _with_fact(
        readers["RESEARCH_RESULT"],
        result_locator,
        result_identity,
        {
            "dataset_snapshot_fingerprint": "d" * 64,
            "plan": {"candidates": [], "published_series": []},
            "statistics_results": [],
        },
    )
    _with_fact(
        readers["QUALIFICATION_DECISION"],
        decision_identity,
        decision_identity,
        {
            "policy_id": "research_quality",
            "policy_version": "1",
            "policy_fingerprint": "e" * 64,
            "subject_strategy_fingerprint": "f" * 64,
            "outcome": "REJECTED",
            "evidence": [
                {
                    "kind": "RESEARCH_RESULT",
                    "locator_fingerprint": result_locator,
                    "evidence_fingerprint": result_identity,
                }
            ],
        },
    )
    records = [r for r in _build(readers).records if r.kind == "FailureEvidenceProjectionRecord"]
    assert len(records) == 1
    assert records[0].facets["classification"] == "QUALIFICATION_REJECT"
    assert records[0].facets["policy_fingerprint"] == "e" * 64
    assert {r.source_family for r in records[0].source_refs} == {"RESEARCH_RESULT", "QUALIFICATION_DECISION"}


def test_neighborhood_summary_requires_every_exact_upstream_in_selected_cuts() -> None:
    readers = _empty_readers()
    base_identity, summary_identity, neighborhood_identity = "a" * 64, "b" * 64, "c" * 64
    _with_fact(
        readers["RESEARCH_STATISTICS"],
        base_identity,
        base_identity,
        {
            "statistics_fingerprint": "d" * 64,
            "statistics_result_fingerprint": base_identity,
        },
    )
    _set_facts(
        readers["RESEARCH_SUMMARY_STATISTICS"],
        [
            (
                summary_identity,
                summary_identity,
                {
                    "statistics_fingerprint": "e" * 64,
                    "statistics_result_fingerprint": summary_identity,
                    "source_statistics_fingerprint": "d" * 64,
                    "source_statistics_result_fingerprint": base_identity,
                },
            ),
            (
                neighborhood_identity,
                neighborhood_identity,
                {
                    "statistics_fingerprint": "f" * 64,
                    "statistics_result_fingerprint": neighborhood_identity,
                    "upstream_statistics_references": {
                        "focal": {
                            "statistics_fingerprint": "e" * 64,
                            "statistics_result_fingerprint": summary_identity,
                        },
                        "neighbors": [{"statistics_fingerprint": "1" * 64, "statistics_result_fingerprint": "2" * 64}],
                    },
                },
            ),
        ],
    )
    with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
        _build(readers)


def test_run_linked_evaluation_requires_exact_runtime_work_binding() -> None:
    readers = _empty_readers()
    result = "a" * 64
    _with_fact(
        readers["RESEARCH_RESULT"],
        result,
        result,
        {
            "dataset_snapshot_fingerprint": "b" * 64,
            "plan": {"candidates": [], "published_series": []},
            "statistics_results": [],
        },
    )
    event = {
        "source_row": {
            "run_id": "00000000-0000-4000-8000-000000000001",
            "research_result_fingerprint": result,
            "specification_fingerprint": "c" * 64,
        }
    }
    _with_fact(readers["RESEARCH_RUN"], "00000000000000000001", "d" * 64, event)
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        _build(readers)


def test_evaluation_statistics_are_candidate_scoped_not_global_result_membership() -> None:
    readers = _empty_readers()
    stats_facts = []
    references = []
    for digit in ("1", "2"):
        logical, identity = digit * 64, str(int(digit) + 2) * 64
        stats_facts.append(
            (
                logical,
                identity,
                {
                    "statistics_fingerprint": logical,
                    "statistics_result_fingerprint": identity,
                },
            )
        )
        references.append({"statistics_fingerprint": logical, "statistics_result_fingerprint": identity})
    _set_facts(readers["RESEARCH_STATISTICS"], stats_facts)
    _with_fact(
        readers["RESEARCH_RESULT"],
        "a" * 64,
        "b" * 64,
        {
            "dataset_snapshot_fingerprint": "c" * 64,
            "statistics_results": references,
            "plan": {
                "candidates": [
                    {
                        "candidate_fingerprint": "d" * 64,
                        "graph_fingerprint": "e" * 64,
                        "statistics_fingerprints": ["1" * 64],
                    }
                ],
                "published_series": [
                    {"candidate_fingerprint": "d" * 64, "node_fingerprint": "f" * 64, "output_name": "factor_value"}
                ],
            },
        },
    )
    evaluation = next(r for r in _build(readers).records if r.kind == "EvaluationProjectionRecord")
    assert evaluation.facets["statistics_references"] == [references[0]]
    assert {ref.identity for ref in evaluation.source_refs if ref.source_family == "RESEARCH_STATISTICS"} == {"3" * 64}
