"""Independent original-contract vectors, not owner/source completeness evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.projector import OnlyExperimentMemoryProjectionV1
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.novelty.decision import OnlyNoveltyDecisionRequestV2
from onlyalpha.research.novelty.decision_store import OnlyNoveltyDecisionAuthority
from onlyalpha.research.novelty.model import (
    OnlyNoveltyPolicyCondition,
    OnlyNoveltyPolicyOutcome,
    OnlyNoveltyPolicyRevisionV1,
    OnlyNoveltyPolicyRuleV1,
)
from onlyalpha.research.novelty.store import OnlyNoveltyPolicyStore
from onlyalpha.research.source_cut import OnlySourceClosedCutV1


def reference() -> dict[str, object]:
    subject = OnlyExactEvaluationIntentSubjectV1(
        "1" * 64,
        "2" * 64,
        "value",
        "3" * 64,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        ("7" * 64,),
        "8" * 64,
        "9" * 64,
        None,
    )
    command = OnlyProductCommandId("11111111-1111-4111-8111-111111111111")
    outcomes = {
        "CERTIFIED_NO_MATCH": "ADMIT",
        "EXACT_COMPLETED_EVALUATION": "REUSE",
        "EXACT_COMPLETED_NEGATIVE_EVIDENCE": "SUPPRESS",
        "OPERATIONAL_FAILURE": "REVIEW",
        "PROOF_INCOMPLETE": "FAIL_CLOSED",
        "PROOF_UNAVAILABLE": "FAIL_CLOSED",
        "SEARCH_OR_BUDGET_STOP": "REVIEW",
    }
    policy = OnlyNoveltyPolicyRevisionV1(
        "native",
        "1",
        tuple(
            OnlyNoveltyPolicyRuleV1(OnlyNoveltyPolicyCondition(condition), OnlyNoveltyPolicyOutcome(outcome))
            for condition, outcome in sorted(outcomes.items())
        ),
    )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        [OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES]
    )
    projection = OnlyExperimentMemoryProjectionV1(manifest, ())
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        revisions = OnlyExperimentMemoryRevisionStore(root / "experiment-memory")
        revisions._publish_and_activate(projection)
        policies = OnlyNoveltyPolicyStore(root)
        policies.put(policy)
        request = OnlyNoveltyDecisionRequestV2(command, "native", "1", subject)
        group = OnlyNoveltyDecisionAuthority(root).seal_group_from_requests(
            (request,),
            projection.revision_fingerprint,
            revisions,
            policies,
        )
    return {
        "subject": subject.to_dict(),
        "subject_fingerprint": subject.subject_fingerprint,
        "command_id": command.value,
        "policy": policy.to_dict(),
        "projection": projection.to_dict(),
        "group": group.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).parents[1] / "fixtures" / "research_novelty.json"
    output = json.dumps(reference(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        assert target.read_text() == output
    else:
        target.write_text(output)


if __name__ == "__main__":
    main()
