from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from onlyalpha.backtest import OnlyBacktestEvidenceStore
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore
from tests.strategy.test_strategy_freeze import _freeze_case

from .support import experiment, fingerprint, plan
from .test_store_and_references import (
    FakeCandidate,
    FakeDecision,
    FakeEvidence,
    FakeFreezeRelation,
    FakeResearchManifest,
    FakeResearchPlan,
    FakeResearchResult,
    stores,
)


def test_fresh_process_reconstructs_complete_exact_provenance(tmp_path: Path) -> None:
    store, candidates, research_results, decisions = stores(
        tmp_path,
        candidate_fingerprint=fingerprint("c"),
        research_result_fingerprint=fingerprint("d"),
        decision_fingerprint=fingerprint("e"),
    )
    search = experiment()
    store.commit_experiment(search)

    iteration_0 = plan(search.experiment_fingerprint, 0)
    store.commit_iteration_plan(iteration_0)
    result_0 = OnlySearchIterationResultV1(
        iteration_0.iteration_plan_fingerprint,
        None,
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.FAILED,
        OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
    )
    store.commit_iteration_result(result_0)

    iteration_1 = plan(
        search.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint=result_0.iteration_result_fingerprint,
        proposal_fingerprint=fingerprint("7"),
        decision_output_fingerprint=fingerprint("8"),
    )
    store.commit_iteration_plan(iteration_1)
    result_1 = OnlySearchIterationResultV1(
        iteration_1.iteration_plan_fingerprint,
        fingerprint("c"),
        True,
        OnlySearchResearchResultReferenceV1(fingerprint("0"), fingerprint("d")),
        False,
        None,
        OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
        None,
    )
    store.commit_iteration_result(result_1)

    # Give the second Candidate/Research/Qualification chain distinct exact identities.
    candidate_2 = fingerprint("1")
    research_2 = fingerprint("2")
    research_locator_2 = fingerprint("4")
    decision_2 = fingerprint("3")
    candidates.values[candidate_2] = FakeCandidate(candidate_2)
    research_results.values[research_locator_2] = FakeResearchResult(
        FakeResearchManifest(
            research_locator_2,
            research_2,
            search.dataset_snapshot_fingerprint,
            FakeResearchPlan((FakeCandidate(candidate_2),)),
        )
    )
    relation_2 = fingerprint("6")
    strategy_2 = fingerprint("a")
    decisions.values[decision_2] = FakeDecision(
        decision_2,
        (FakeEvidence("RESEARCH_RESULT", research_2, research_locator_2, relation_2),),
        strategy_2,
    )
    decisions.freeze_relations.values[relation_2] = FakeFreezeRelation(
        relation_2,
        candidate_2,
        research_2,
        strategy_2,
    )
    iteration_2 = plan(
        search.experiment_fingerprint,
        2,
        parent_iteration_result_fingerprint=result_1.iteration_result_fingerprint,
        proposal_fingerprint=fingerprint("9"),
        decision_output_fingerprint=fingerprint("a"),
    )
    store.commit_iteration_plan(iteration_2)
    result_2 = OnlySearchIterationResultV1(
        iteration_2.iteration_plan_fingerprint,
        candidate_2,
        True,
        OnlySearchResearchResultReferenceV1(research_locator_2, research_2),
        True,
        decision_2,
        OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
        None,
    )
    store.commit_iteration_result(result_2)

    script = textwrap.dedent(
        """
        import json
        import sys
        from types import SimpleNamespace as N
        from pathlib import Path
        from onlyalpha.research.experiment import OnlyJsonSearchProvenanceStore, OnlySearchExperimentManifestV1

        root, final_result, experiment_json = sys.argv[1:]
        manifest = OnlySearchExperimentManifestV1.from_dict(json.loads(experiment_json))

        class Catalogs:
            def generation(self, fingerprint):
                return N(generation_fingerprint=fingerprint)
        class Datasets:
            def load_verified_table(self, fingerprint):
                return N(snapshot=N(snapshot_fingerprint=fingerprint))
        class Candidates:
            def load_verified(self, fingerprint):
                if fingerprint not in {"c" * 64, "1" * 64}:
                    raise KeyError(fingerprint)
                return N(candidate_fingerprint=fingerprint)
        class Research:
            def load_verified(self, locator):
                values = {"0" * 64: ("d" * 64, "c" * 64), "4" * 64: ("2" * 64, "1" * 64)}
                result, candidate = values[locator]
                return N(manifest=N(
                    research_result_plan_fingerprint=locator,
                    research_result_fingerprint=result,
                    dataset_snapshot_fingerprint="5" * 64,
                    plan=N(candidates=(N(candidate_fingerprint=candidate),)),
                ))
        class Decisions:
            def load_verified(self, fingerprint):
                if fingerprint != "3" * 64:
                    raise KeyError(fingerprint)
                return N(
                    decision_fingerprint=fingerprint,
                    subject_strategy_fingerprint="a" * 64,
                    evidence=(N(
                        kind="RESEARCH_RESULT",
                        evidence_fingerprint="2" * 64,
                        locator_fingerprint="4" * 64,
                        subject_binding_fingerprint="6" * 64,
                    ),),
                )
        class FreezeRelations:
            def load_freeze_relation(self, fingerprint):
                if fingerprint != "6" * 64:
                    raise KeyError(fingerprint)
                return N(
                    relation_fingerprint=fingerprint,
                    candidate_fingerprint="1" * 64,
                    research_result_fingerprint="2" * 64,
                    strategy_fingerprint="a" * 64,
                )

        store = OnlyJsonSearchProvenanceStore(
            Path(root), catalogs=Catalogs(), datasets=Datasets(), candidates=Candidates(),
            research_results=Research(), qualification_decisions=Decisions(),
            freeze_relations=FreezeRelations(),
        )
        result = store.load_iteration_result_verified(final_result)
        chain = []
        while True:
            plan = store.load_iteration_plan_verified(result.iteration_plan_fingerprint)
            chain.append({
                "iteration_index": plan.iteration_index,
                "proposal_fingerprint": plan.proposal_fingerprint,
                "candidate_fingerprint": result.candidate_fingerprint,
                "research_result_reference": (
                    None if result.research_result_reference is None
                    else result.research_result_reference.to_dict()
                ),
                "qualification_decision_fingerprint": result.qualification_decision_fingerprint,
            })
            if plan.parent_iteration_result_fingerprint is None:
                break
            result = store.load_iteration_result_verified(plan.parent_iteration_result_fingerprint)
        loaded_experiment = store.load_experiment_verified(plan.experiment_fingerprint)
        print(json.dumps({
            "experiment_fingerprint": loaded_experiment.experiment_fingerprint,
            "hypothesis_fingerprint": loaded_experiment.hypothesis.hypothesis_fingerprint,
            "chain": chain,
            "reparsed_fingerprint": manifest.experiment_fingerprint,
        }, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            result_2.iteration_result_fingerprint,
            json.dumps(search.to_dict(), sort_keys=True),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    closure = json.loads(completed.stdout)
    assert closure["experiment_fingerprint"] == search.experiment_fingerprint
    assert closure["hypothesis_fingerprint"] == search.hypothesis.hypothesis_fingerprint
    assert closure["reparsed_fingerprint"] == search.experiment_fingerprint
    assert [item["iteration_index"] for item in closure["chain"]] == [2, 1, 0]
    assert closure["chain"][0]["qualification_decision_fingerprint"] == decision_2
    assert closure["chain"][1]["research_result_reference"]["result_fingerprint"] == fingerprint("d")
    assert closure["chain"][2]["candidate_fingerprint"] is None


def test_fresh_process_closes_real_research_qualification_and_freeze_authorities(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "authority"
    semantic_root = tmp_path / "semantic"
    search_root = tmp_path / "search"
    service, run, candidate, strategies, _ = _freeze_case(  # type: ignore[no-untyped-call]
        authority_root,
        semantic_root=semantic_root,
    )
    frozen = service.freeze(OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "closure-test"))
    relation = strategies.load_freeze_relation(frozen.freeze_record.record_fingerprint)
    research_results = service._research_results
    result_locator = service._specification_resolver.resolve(run.specification).workload.result_plan.fingerprint
    research_result = research_results.load_verified(result_locator)

    policies = OnlyQualificationPolicyStore(semantic_root)
    decisions, decision_publisher = _only_compose_qualification_decision_authority(semantic_root)
    policy = OnlyQualificationPolicyRevision(
        "search-closure",
        "1",
        OnlyQualificationGate.RESEARCH_TO_BACKTEST,
        (
            OnlyQualificationCriterion(
                "has-statistics",
                OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                "research.statistics_result_count",
                "GE",
                Decimal(1),
            ),
        ),
    )
    policies.put(policy)
    qualification_evidence = (
        OnlyQualificationEvidenceReference(
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            research_result.manifest.research_result_fingerprint,
            result_locator,
            relation.relation_fingerprint,
        ),
    )
    decision = OnlyQualificationEvaluator(
        strategies=strategies,
        policies=policies,
        research_results=research_results,
        backtest_evidence=OnlyBacktestEvidenceStore(tmp_path / "backtest"),
        decisions=decision_publisher,
    ).evaluate(
        subject_strategy_fingerprint=relation.strategy_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        evidence=qualification_evidence,
    )

    search = replace(
        experiment(),
        dataset_snapshot_fingerprint=research_result.manifest.dataset_snapshot_fingerprint,
    )

    class Catalogs:
        def generation(self, fingerprint: str) -> object:
            if fingerprint != search.catalog_generation_fingerprint:
                raise KeyError(fingerprint)
            return SimpleNamespace(generation_fingerprint=fingerprint)

    class Candidates:
        def load_verified(self, fingerprint: str) -> object:
            if fingerprint != candidate.candidate_fingerprint:
                raise KeyError(fingerprint)
            return SimpleNamespace(candidate_fingerprint=fingerprint)

    search_store = OnlyJsonSearchProvenanceStore(
        search_root,
        catalogs=Catalogs(),  # type: ignore[arg-type]
        datasets=service._datasets,
        candidates=Candidates(),  # type: ignore[arg-type]
        research_results=research_results,
        qualification_decisions=decisions,
        freeze_relations=OnlyFrozenStrategyRevisionStore(semantic_root),
    )
    search_store.commit_experiment(search)
    iteration = plan(search.experiment_fingerprint)
    search_store.commit_iteration_plan(iteration)
    terminal = OnlySearchIterationResultV1(
        iteration.iteration_plan_fingerprint,
        candidate.candidate_fingerprint,
        True,
        OnlySearchResearchResultReferenceV1(
            result_locator,
            research_result.manifest.research_result_fingerprint,
        ),
        True,
        decision.decision_fingerprint,
        OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
        None,
    )
    search_store.commit_iteration_result(terminal)

    script = textwrap.dedent(
        """
        import json
        import sys
        from datetime import UTC, datetime
        from pathlib import Path
        from types import SimpleNamespace

        from onlyalpha.research import (
            OnlyJsonResearchResultStore,
            OnlyParquetResearchCalculationResultStore,
            OnlyParquetResearchDatasetSnapshotStore,
            OnlyParquetResearchStatisticsResultStore,
        )
        from onlyalpha.research.experiment import OnlyJsonSearchProvenanceStore
        from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore
        from onlyalpha.strategy.qualification_store import OnlyQualificationDecisionStore

        authority_root, semantic_root, search_root, terminal_fp, catalog_fp, candidate_fp = sys.argv[1:]
        authority = Path(authority_root)
        datasets = OnlyParquetResearchDatasetSnapshotStore(authority / "base" / "datasets")
        calculations = OnlyParquetResearchCalculationResultStore(
            authority / "calculation-results", datasets, audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC)
        )
        statistics = OnlyParquetResearchStatisticsResultStore(
            authority / "statistics-results", calculations, audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC)
        )
        research = OnlyJsonResearchResultStore(authority / "research-results", statistics, calculations)
        strategies = OnlyFrozenStrategyRevisionStore(Path(semantic_root))

        class Catalogs:
            def generation(self, fingerprint):
                if fingerprint != catalog_fp:
                    raise KeyError(fingerprint)
                return SimpleNamespace(generation_fingerprint=fingerprint)
        class Candidates:
            def load_verified(self, fingerprint):
                if fingerprint != candidate_fp:
                    raise KeyError(fingerprint)
                return SimpleNamespace(candidate_fingerprint=fingerprint)

        store = OnlyJsonSearchProvenanceStore(
            Path(search_root),
            catalogs=Catalogs(),
            datasets=datasets,
            candidates=Candidates(),
            research_results=research,
            qualification_decisions=OnlyQualificationDecisionStore(Path(semantic_root)),
            freeze_relations=strategies,
        )
        loaded = store.load_iteration_result_verified(terminal_fp)
        print(json.dumps({
            "terminal": loaded.iteration_result_fingerprint,
            "locator": loaded.research_result_reference.locator_fingerprint,
            "result": loaded.research_result_reference.result_fingerprint,
            "decision": loaded.qualification_decision_fingerprint,
        }, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(authority_root),
            str(semantic_root),
            str(search_root),
            terminal.iteration_result_fingerprint,
            search.catalog_generation_fingerprint,
            candidate.candidate_fingerprint,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    closure = json.loads(completed.stdout)
    assert closure == {
        "decision": decision.decision_fingerprint,
        "locator": result_locator,
        "result": research_result.manifest.research_result_fingerprint,
        "terminal": terminal.iteration_result_fingerprint,
    }
