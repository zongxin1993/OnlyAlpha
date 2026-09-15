"""Hermetic closure, deterministic identity and disposable-revision regression tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandKind
from onlyalpha.application.search_product import only_search_experiment_work_id
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.command.model import OnlyDerivedResearchSubmitCommandV2, only_derived_research_run_id
from onlyalpha.research.experiment import (
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.memory.projector import (
    PROJECTION_SCHEMA_VERSION,
    PROJECTOR_ALGORITHM_VERSION,
    only_build_experiment_memory_projection,
    only_project_experiment_memory,
)
from onlyalpha.research.memory.source_manifest import (
    MANDATORY_FAMILIES,
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.search.parameter.integration import parameter_submission_key
from onlyalpha.research.search.symbolic.controller import symbolic_submission_key
from onlyalpha.research.source_cut import (
    OnlySourceClosedCutV1,
    OnlySourceCutEntryV1,
    OnlySourceCutError,
    OnlySourceObservationV1,
    _OnlyFileSourceCutAuthority,
)
from tests.research.specification.support import specification


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


def _shared_result_lineage_case():
    readers = _empty_readers()
    scientific = specification()
    result, locator, candidate = "d" * 64, "c" * 64, "e" * 64
    experiments = ("1" * 64, "2" * 64)
    plans = (
        OnlySearchIterationPlanV1(experiments[0], 0, "ONLY_SYMBOLIC_GRAPH_PROPOSAL", 1, "a" * 64, (), (), "f" * 64),
        OnlySearchIterationPlanV1(experiments[1], 0, "ONLY_PARAMETER_GRAPH_PROPOSAL", 1, "b" * 64, (), (), "f" * 64),
    )
    commands = (symbolic_submission_key(plans[0]), parameter_submission_key(plans[1]))
    run_ids = tuple(only_derived_research_run_id(command).value for command in commands)
    direct = "00000000-0000-4000-8000-000000000003"
    terminal = OnlySearchIterationResultV1(
        plans[0].iteration_plan_fingerprint,
        candidate,
        True,
        OnlySearchResearchResultReferenceV1(locator, result),
        False,
        None,
        OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
        None,
    )
    search_facts = [
        (
            f"experiments/{experiment}",
            experiment,
            {
                "dataset_snapshot_fingerprint": scientific.dataset_snapshot_fingerprint,
                "catalog_generation_fingerprint": "9" * 64,
                "search_space_reference": {"search_space_fingerprint": "8" * 64},
            },
        )
        for experiment in experiments
    ]
    search_facts.extend(
        (f"iteration-plans/{plan.iteration_plan_fingerprint}", plan.iteration_plan_fingerprint, plan.to_dict())
        for plan in plans
    )
    search_facts.append(
        (
            f"iteration-results/{terminal.iteration_result_fingerprint}",
            terminal.iteration_result_fingerprint,
            terminal.to_dict(),
        )
    )
    _set_facts(readers["SEARCH_PROVENANCE"], search_facts)
    _with_fact(
        readers["RESEARCH_RESULT"],
        locator,
        result,
        {
            "dataset_snapshot_fingerprint": scientific.dataset_snapshot_fingerprint,
            "statistics_results": [],
            "plan": {
                "candidates": [{"candidate_fingerprint": candidate, "graph_fingerprint": "f" * 64}],
                "published_series": [
                    {"candidate_fingerprint": candidate, "node_fingerprint": "0" * 64, "output_name": "factor_value"}
                ],
            },
        },
    )
    _set_facts(
        readers["RESEARCH_RUN"],
        [
            (
                f"{index:020d}",
                str(index) * 64,
                {
                    "source_row": {
                        "run_id": run_id,
                        "revision": 2,
                        "state": "COMPLETED",
                        "specification_fingerprint": scientific.specification_fingerprint,
                        "specification_payload": only_canonical_json(scientific.to_dict()),
                        "research_result_fingerprint": result,
                        "artifact_content_fingerprint": "7" * 64,
                        "authoring_provenance": None,
                        "calculation_execution_evidence_fingerprints": [],
                    }
                },
            )
            for index, run_id in enumerate((*run_ids, direct), start=1)
        ],
    )
    admissions = []
    receipts = []
    for index, (plan, command, run_id) in enumerate(zip(plans, commands, run_ids, strict=True), start=1):
        fingerprint = OnlyDerivedResearchSubmitCommandV2(
            command, scientific, only_search_experiment_work_id(plan.experiment_fingerprint)
        ).command_fingerprint
        admission = {
            "command_id": command.value,
            "command_kind": OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            "command_fingerprint": fingerprint,
            "schema_version": 1,
        }
        receipt = {
            **admission,
            "outcome_kind": "RESEARCH_RUN",
            "outcome_id": run_id,
            "accepted_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        }
        admissions.append((f"{index:020d}", str(index + 3) * 64, {"source_row": admission}))
        receipts.append((f"{index:020d}", str(index + 5) * 64, {"source_row": receipt}))
    _set_facts(readers["PRODUCT_COMMAND_ADMISSION"], admissions)
    _set_facts(readers["PRODUCT_COMMAND_RECEIPT"], receipts)

    def reference(kind: str, identity: str):
        if kind == "RUNTIME_WORK_BINDING":
            return {
                "work_id": identity,
                "runtime_generation_fingerprint": "6" * 64,
                "catalog_generation_fingerprint": "9" * 64,
            }
        if kind == "ONLY_PARAMETER_GRAPH_PROPOSAL":
            return {
                "proposal_fingerprint": identity,
                "search_space_fingerprint": "8" * 64,
                "ordinal": 0,
                "assignment": [],
            }
        return {}

    return readers, plans, commands, run_ids, direct, reference


@pytest.mark.recovery
def test_receipt_bound_search_lineage_is_per_run_and_rebuildable(tmp_path: Path) -> None:
    readers, plans, commands, run_ids, direct, reference = _shared_result_lineage_case()
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    projection = only_build_experiment_memory_projection(manifest, readers, reference)
    evaluation = next(record for record in projection.records if record.kind == "EvaluationProjectionRecord")
    closures = {
        closure["run_id"]: closure["search_lineage"] for closure in evaluation.facets["run_evaluation_closures"]
    }
    assert closures[direct] is None
    for index, run_id in enumerate(run_ids):
        lineage = closures[run_id]
        assert lineage["search_method"] == ("SYMBOLIC", "PARAMETER")[index]
        assert lineage["experiment_fingerprint"] == plans[index].experiment_fingerprint
        assert lineage["iteration_plan_fingerprint"] == plans[index].iteration_plan_fingerprint
        assert lineage["research_product_command_id"] == commands[index].value
        assert lineage["research_product_command_kind"] == "CREATE_RESEARCH_RUN"
        assert lineage["iteration_result_fingerprint"] == (
            next(
                item.identity
                for item in readers["SEARCH_PROVENANCE"].observations
                if item.locator.startswith("iteration-results/")
            )
            if index == 0
            else None
        )
    assert closures[run_ids[0]]["experiment_fingerprint"] != closures[run_ids[1]]["experiment_fingerprint"]
    assert evaluation.facets["search_experiment_refs"] == [plans[0].experiment_fingerprint]

    root = tmp_path / "experiment-memory"
    store = OnlyExperimentMemoryRevisionStore(root)
    store.publish_and_activate(manifest, readers, reference)
    before = {family: reader.cut.cut_fingerprint for family, reader in readers.items()}
    import shutil

    shutil.rmtree(root)
    for reader in readers.values():
        reader.observations = tuple(reversed(reader.observations))
    rebuilt = only_build_experiment_memory_projection(manifest, readers, reference)
    assert rebuilt == projection
    assert rebuilt.logical_digest == projection.logical_digest
    assert rebuilt.revision_fingerprint == projection.revision_fingerprint
    assert before == {family: reader.cut.cut_fingerprint for family, reader in readers.items()}

    old_readers = deepcopy(readers)
    search = readers["SEARCH_PROVENANCE"]
    later = "3" * 64
    _set_facts(
        search,
        [
            *((item.locator, item.identity, dict(item.canonical_payload)) for item in search.observations),
            (
                f"experiments/{later}",
                later,
                {"dataset_snapshot_fingerprint": "a" * 64, "catalog_generation_fingerprint": "9" * 64},
            ),
        ],
    )
    newer = only_build_experiment_memory_projection(
        OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()]),
        readers,
        reference,
    )
    assert newer.revision_fingerprint != projection.revision_fingerprint
    assert only_build_experiment_memory_projection(manifest, old_readers, reference) == projection


@pytest.mark.recovery
def test_resultless_run_failures_keep_exact_occurrence_context(tmp_path: Path) -> None:
    readers, plans, commands, run_ids, direct, reference = _shared_result_lineage_case()
    search = readers["SEARCH_PROVENANCE"]
    _set_facts(
        search,
        [
            (item.locator, item.identity, dict(item.canonical_payload))
            for item in search.observations
            if not item.locator.startswith("iteration-results/")
        ],
    )
    resultful = "00000000-0000-4000-8000-000000000004"
    run_facts: list[tuple[str, str, dict[str, object]]] = []
    for index, item in enumerate(readers["RESEARCH_RUN"].observations, start=1):
        payload = dict(item.canonical_payload)
        row = dict(payload["source_row"])  # type: ignore[arg-type]
        row.update(
            state="FAILED",
            research_result_fingerprint=None,
            artifact_content_fingerprint=None,
            failure_phase="EXECUTION",
            failure_code=f"FAILED_{index}",
            failure_detail=f"failure {index}",
        )
        payload["source_row"] = row
        run_facts.append((item.locator, item.identity, payload))
    resultful_row = dict(run_facts[-1][2]["source_row"])  # type: ignore[arg-type]
    resultful_row.update(run_id=resultful, research_result_fingerprint="d" * 64)
    run_facts.append(("00000000000000000004", "4" * 64, {"source_row": resultful_row}))
    _set_facts(readers["RESEARCH_RUN"], run_facts)

    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    projection = only_build_experiment_memory_projection(manifest, readers, reference)
    failures = {
        record.facets["run_context"]["run_id"]: record  # type: ignore[index]
        for record in projection.records
        if record.kind == "FailureEvidenceProjectionRecord" and "run_context" in record.facets
    }
    assert set(failures) == {*run_ids, direct, resultful}
    for index, run_id in enumerate(run_ids):
        context = failures[run_id].facets["run_context"]
        lineage = context["search_lineage"]
        assert context["research_result_fingerprint"] is None
        assert context["artifact_content_fingerprint"] is None
        assert context["runtime_generation_fingerprint"] == "6" * 64
        assert context["catalog_generation_fingerprint"] == "9" * 64
        assert lineage["experiment_fingerprint"] == plans[index].experiment_fingerprint
        assert lineage["iteration_plan_fingerprint"] == plans[index].iteration_plan_fingerprint
        assert lineage["research_product_command_id"] == commands[index].value
        assert {ref.source_family for ref in failures[run_id].source_refs} == {
            "SEARCH_PROVENANCE",
            "PRODUCT_COMMAND_ADMISSION",
            "PRODUCT_COMMAND_RECEIPT",
            "RESEARCH_RUN",
        }
    assert (
        failures[run_ids[0]].facets["run_context"]["search_lineage"]
        != failures[run_ids[1]].facets["run_context"]["search_lineage"]
    )
    assert failures[direct].facets["run_context"]["search_lineage"] is None
    assert failures[resultful].facets["run_context"]["research_result_fingerprint"] == "d" * 64
    parameter = next(
        record
        for record in projection.records
        if record.kind == "ParameterObservationProjectionRecord"
        and record.facets["experiment_fingerprint"] == plans[1].experiment_fingerprint
    )
    assert (
        parameter.facets["iteration_plan_fingerprint"]
        == failures[run_ids[1]].facets["run_context"]["search_lineage"]["iteration_plan_fingerprint"]
    )

    root = tmp_path / "experiment-memory"
    store = OnlyExperimentMemoryRevisionStore(root)
    store.publish_and_activate(manifest, readers, reference)
    source_cuts = {family: reader.cut.cut_fingerprint for family, reader in readers.items()}
    shutil.rmtree(root)
    for reader in readers.values():
        reader.observations = tuple(reversed(reader.observations))
    rebuilt = only_build_experiment_memory_projection(manifest, readers, reference)
    assert rebuilt == projection
    assert rebuilt.logical_digest == projection.logical_digest
    assert rebuilt.revision_fingerprint == projection.revision_fingerprint
    assert source_cuts == {family: reader.cut.cut_fingerprint for family, reader in readers.items()}


@pytest.mark.parametrize(
    "corruption", ["admission", "receipt", "missing_receipt", "schema", "run", "plan", "experiment", "outcome_kind"]
)
def test_search_lineage_conflicts_fail_closed(corruption: str, tmp_path: Path) -> None:
    readers, plans, _, run_ids, direct, reference = _shared_result_lineage_case()
    run_reader = readers["RESEARCH_RUN"]
    run_rows = [(item.locator, item.identity, dict(item.canonical_payload)) for item in run_reader.observations]
    failed_payload = run_rows[0][2]
    failed_payload["source_row"] = {
        **failed_payload["source_row"],  # type: ignore[dict-item]
        "state": "FAILED",
        "research_result_fingerprint": None,
        "artifact_content_fingerprint": None,
        "failure_phase": "EXECUTION",
        "failure_code": "SEARCH_EXECUTION_FAILED",
        "failure_detail": "resultless failure",
    }
    assert failed_payload["source_row"]["run_id"] == run_ids[0]  # type: ignore[index]
    _set_facts(run_reader, run_rows)
    search_reader = readers["SEARCH_PROVENANCE"]
    _set_facts(
        search_reader,
        [
            (item.locator, item.identity, dict(item.canonical_payload))
            for item in search_reader.observations
            if not item.locator.startswith("iteration-results/")
        ],
    )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([source.cut for source in readers.values()])
    store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    original = store.publish_and_activate(manifest, readers, reference)
    if corruption == "admission":
        reader = readers["PRODUCT_COMMAND_ADMISSION"]
        rows = [(o.locator, o.identity, dict(o.canonical_payload)) for o in reader.observations]
        rows[0][2]["source_row"] = {**rows[0][2]["source_row"], "command_fingerprint": "0" * 64}
    elif corruption in {"receipt", "missing_receipt", "schema", "run", "outcome_kind"}:
        reader = readers["PRODUCT_COMMAND_RECEIPT"]
        rows = [(o.locator, o.identity, dict(o.canonical_payload)) for o in reader.observations]
        if corruption == "missing_receipt":
            rows.pop(0)
            _set_facts(reader, rows)
            with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
                store.publish_and_activate(
                    OnlyExperimentMemorySourceCutManifestV1.from_cuts([source.cut for source in readers.values()]),
                    readers,
                    reference,
                )
            assert store.load_active_verified().revision_fingerprint == original
            return
        changed = {
            "receipt": {"command_kind": "CANCEL_RESEARCH_RUN"},
            "schema": {"schema_version": 2},
            "run": {"outcome_id": direct},
            "outcome_kind": {"outcome_kind": "BACKTEST_RUN"},
        }[corruption]
        rows[0][2]["source_row"] = {**rows[0][2]["source_row"], **changed}
    else:
        reader = readers["SEARCH_PROVENANCE"]
        rows = [(o.locator, o.identity, dict(o.canonical_payload)) for o in reader.observations]
        index = next(
            i
            for i, row in enumerate(rows)
            if row[1]
            == (plans[0].iteration_plan_fingerprint if corruption == "plan" else plans[0].experiment_fingerprint)
        )
        locator, identity, payload = rows[index]
        rows[index] = (
            locator,
            identity if corruption == "plan" else "4" * 64,
            {**payload, "experiment_fingerprint": plans[1].experiment_fingerprint} if corruption == "plan" else payload,
        )
    _set_facts(reader, rows)
    with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
        store.publish_and_activate(
            OnlyExperimentMemorySourceCutManifestV1.from_cuts([source.cut for source in readers.values()]),
            readers,
            reference,
        )
    assert store.load_active_verified().revision_fingerprint == original


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
        proposal = str(ordinal + 5) * 64
        plan = OnlySearchIterationPlanV1(
            experiment, iteration_index, "ONLY_PARAMETER_GRAPH_PROPOSAL", 1, proposal, (), (), "f" * 64
        )
        identity = plan.iteration_plan_fingerprint
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
                plan.to_dict(),
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


def test_evaluation_closures_bind_each_historical_run_without_cross_association(tmp_path: Path) -> None:
    readers = _empty_readers()
    result = "a" * 64
    _with_fact(
        readers["RESEARCH_RESULT"],
        result,
        result,
        {
            "dataset_snapshot_fingerprint": "b" * 64,
            "statistics_results": [],
            "plan": {
                "candidates": [{"candidate_fingerprint": "c" * 64, "graph_fingerprint": "d" * 64}],
                "published_series": [
                    {"candidate_fingerprint": "c" * 64, "node_fingerprint": "e" * 64, "output_name": "value"}
                ],
            },
        },
    )
    run1 = "00000000-0000-4000-8000-000000000001"
    run2 = "00000000-0000-4000-8000-000000000002"
    run3 = "00000000-0000-4000-8000-000000000003"

    def row(run_id: str, revision: int, state: str, spec: str, authoring: str | None, artifact: str | None):
        return {
            "source_row": {
                "run_id": run_id,
                "revision": revision,
                "state": state,
                "specification_fingerprint": spec,
                "research_result_fingerprint": result,
                "artifact_content_fingerprint": artifact,
                "authoring_provenance": (
                    {
                        "execution_generation_fingerprint": authoring,
                        "catalog_generation_fingerprint": ("a" if authoring == "5" * 64 else "b") * 64,
                    }
                    if authoring is not None
                    else None
                ),
                "calculation_execution_evidence_fingerprints": ["8" * 64] if artifact else [],
            }
        }

    _set_facts(
        readers["RESEARCH_RUN"],
        [
            ("00000000000000000001", "1" * 64, row(run1, 2, "RUNNING", "3" * 64, "5" * 64, None)),
            ("00000000000000000002", "2" * 64, row(run1, 3, "FAILED", "3" * 64, "5" * 64, None)),
            ("00000000000000000003", "3" * 64, row(run2, 2, "COMPLETED", "4" * 64, "6" * 64, "7" * 64)),
            ("00000000000000000004", "4" * 64, row(run3, 2, "CANCELLED", "4" * 64, None, None)),
        ],
    )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])

    def reference(kind: str, identity: str):
        if kind == "RUNTIME_WORK_BINDING":
            generation, catalog = ("9", "a") if identity == run1 else ("f", "b") if identity == run2 else ("7", "c")
            return {
                "work_id": identity,
                "runtime_generation_fingerprint": generation * 64,
                "catalog_generation_fingerprint": catalog * 64,
            }
        if kind == "AUTHORING_GENERATION":
            return {
                "execution_generation_fingerprint": identity,
                "provenance": {"catalog_generation_fingerprint": ("a" if identity == "5" * 64 else "b") * 64},
            }
        return {}

    def build():
        return only_build_experiment_memory_projection(manifest, readers, reference)

    projection = build()
    assert (PROJECTION_SCHEMA_VERSION, PROJECTOR_ALGORITHM_VERSION) == (5, 5)
    evaluation = next(record for record in projection.records if record.kind == "EvaluationProjectionRecord")
    assert evaluation.facets["catalog_generation_refs"] == ["a" * 64, "b" * 64]
    closures = evaluation.facets["run_evaluation_closures"]
    assert [(c["run_id"], c["run_revision"], c["run_state"]) for c in closures] == [
        (run1, 2, "RUNNING"),
        (run1, 3, "FAILED"),
        (run2, 2, "COMPLETED"),
        (run3, 2, "CANCELLED"),
    ]
    assert [
        (
            c["specification_fingerprint"],
            c["runtime_generation_fingerprint"],
            c["catalog_generation_fingerprint"],
            c["authoring_generation_fingerprint"],
            c["artifact_content_fingerprint"],
        )
        for c in closures
    ] == [
        ("3" * 64, "9" * 64, "a" * 64, "5" * 64, None),
        ("3" * 64, "9" * 64, "a" * 64, "5" * 64, None),
        ("4" * 64, "f" * 64, "b" * 64, "6" * 64, "7" * 64),
        ("4" * 64, "7" * 64, "c" * 64, None, None),
    ]
    assert closures[0]["catalog_generation_fingerprint"] != "b" * 64
    assert closures[2]["catalog_generation_fingerprint"] != "a" * 64
    assert closures[3]["authoring_generation_fingerprint"] is None
    assert [c["calculation_execution_evidence_fingerprints"] for c in closures] == [[], [], ["8" * 64], []]
    assert [c["run_source_ref"]["locator"] for c in closures] == [f"{i:020d}" for i in range(1, 5)]
    readers["RESEARCH_RUN"].observations = tuple(reversed(readers["RESEARCH_RUN"].observations))
    assert build().logical_digest == projection.logical_digest
    assert build().revision_fingerprint == projection.revision_fingerprint

    def mismatched_reference(kind: str, identity: str):
        if kind == "AUTHORING_GENERATION":
            return {
                "execution_generation_fingerprint": identity,
                "provenance": {"catalog_generation_fingerprint": "e" * 64},
            }
        return reference(kind, identity)

    store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    store.publish_and_activate(manifest, readers, reference)
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        store.publish_and_activate(manifest, readers, mismatched_reference)
    assert store.load_active_verified() == projection

    _set_facts(
        readers["RESEARCH_RUN"],
        [("00000000000000000001", "1" * 64, row(run1, 2, "COMPLETED", "3" * 64, "5" * 64, None))],
    )
    with pytest.raises(OnlyMemoryProjectionError, match="SOURCE_OBSERVATION_MISMATCH"):
        only_build_experiment_memory_projection(
            OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()]),
            readers,
            reference,
        )
