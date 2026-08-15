from __future__ import annotations

import json
import os
import subprocess
import sys

from onlyalpha.research import (
    OnlyResearchResultPlan,
    OnlyResearchStatisticsResultReference,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def test_plan_content_and_result_identities_are_distinct_and_deterministic() -> None:
    plan = OnlyResearchResultPlan((B, A))
    references = (
        OnlyResearchStatisticsResultReference(A, C),
        OnlyResearchStatisticsResultReference(B, D),
    )
    content = only_research_result_content_fingerprint(tuple(item.to_dict() for item in references))
    result = only_research_result_fingerprint(plan.fingerprint, content)

    assert len({plan.fingerprint, content, result}) == 3
    assert all(len(value) == 64 for value in (plan.fingerprint, content, result))


def test_identity_is_stable_across_fresh_process_hash_seeds() -> None:
    code = (
        "import json; from onlyalpha.research import *; "
        "p=OnlyResearchResultPlan(('b'*64,'a'*64)); "
        "r=(OnlyResearchStatisticsResultReference('a'*64,'c'*64),"
        "OnlyResearchStatisticsResultReference('b'*64,'d'*64)); "
        "c=only_research_result_content_fingerprint(tuple(x.to_dict() for x in r)); "
        "print(json.dumps([p.fingerprint,c,only_research_result_fingerprint(p.fingerprint,c)]))"
    )
    outputs = []
    for seed in ("1", "827"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", code],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]
    assert len(json.loads(outputs[0])) == 3
