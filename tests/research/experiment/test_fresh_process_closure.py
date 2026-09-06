from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
)

from .support import experiment, fingerprint, plan
from .test_store_and_references import (
    FakeCandidate,
    FakeDecision,
    FakeEvidence,
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
        fingerprint("d"),
        False,
        None,
        OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
        None,
    )
    store.commit_iteration_result(result_1)

    # Give the second Candidate/Research/Qualification chain distinct exact identities.
    candidate_2 = fingerprint("1")
    research_2 = fingerprint("2")
    decision_2 = fingerprint("3")
    candidates.values[candidate_2] = FakeCandidate(candidate_2)
    research_results.values[research_2] = FakeResearchResult(
        FakeResearchManifest(
            research_2,
            search.dataset_snapshot_fingerprint,
            FakeResearchPlan((FakeCandidate(candidate_2),)),
        )
    )
    decisions.values[decision_2] = FakeDecision(decision_2, (FakeEvidence(research_2),))
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
        research_2,
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
            def load_verified(self, fingerprint):
                candidates = {"d" * 64: "c" * 64, "2" * 64: "1" * 64}
                candidate = candidates[fingerprint]
                return N(manifest=N(
                    research_result_fingerprint=fingerprint,
                    dataset_snapshot_fingerprint="5" * 64,
                    plan=N(candidates=(N(candidate_fingerprint=candidate),)),
                ))
        class Decisions:
            def load_verified(self, fingerprint):
                if fingerprint != "3" * 64:
                    raise KeyError(fingerprint)
                return N(decision_fingerprint=fingerprint, evidence=(N(evidence_fingerprint="2" * 64),))

        store = OnlyJsonSearchProvenanceStore(
            Path(root), catalogs=Catalogs(), datasets=Datasets(), candidates=Candidates(),
            research_results=Research(), qualification_decisions=Decisions(),
        )
        result = store.load_iteration_result_verified(final_result)
        chain = []
        while True:
            plan = store.load_iteration_plan_verified(result.iteration_plan_fingerprint)
            chain.append({
                "iteration_index": plan.iteration_index,
                "proposal_fingerprint": plan.proposal_fingerprint,
                "candidate_fingerprint": result.candidate_fingerprint,
                "research_result_fingerprint": result.research_result_fingerprint,
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
    assert closure["chain"][1]["research_result_fingerprint"] == fingerprint("d")
    assert closure["chain"][2]["candidate_fingerprint"] is None
