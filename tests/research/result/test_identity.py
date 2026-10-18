from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

from onlyalpha.research import (
    OnlyResearchResultManifest,
    OnlyResearchResultPlan,
    OnlyResearchStatisticsResultReference,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from tests.research.artifact.support import scientific_artifact_case
from tests.research.result.support import result_case

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


def test_historical_v1_and_legacy_only_scientific_v2_identities_and_serialization_are_pinned(tmp_path) -> None:
    v1 = result_case(tmp_path / "v1")[3].manifest
    v2 = scientific_artifact_case(tmp_path / "v2")[1].result.manifest
    assert (
        v1.research_result_plan_fingerprint,
        v1.research_result_content_fingerprint,
        v1.research_result_fingerprint,
    ) == (
        "3c59d735c059c20cb476a4197ce03b635cfc509f635ba7436e1489565046d4eb",
        "81c76d374cbfdfa678d13aa5caf1f446cd84adada909e57769e9433496b4b33b",
        "812b0250125cf24259f79fa1141db01c844063d9ef8a6103d0103399a4d05b34",
    )
    assert (
        v2.research_result_plan_fingerprint,
        v2.research_result_content_fingerprint,
        v2.research_result_fingerprint,
    ) == (
        "9d68d35d8e9b5fcb877fbb704b4ec2f816961e11cda642590dbfb8998abec511",
        "cef580fcf1a90fdd4e60b24b858e1b85834ba20952a9645aef7be4f388d519c1",
        "625d97c23f5a5780523bc9efb321791d761873214a0232cfc111bfc09ff09bba",
    )
    expected_serialization_hashes = (
        "52403441341e38ddfeb080a9f1ba302901ac1797c489df6181993b319f332132",
        "8032a40eb3735a04a274f30a0a5a97859975183dc1a2908559805622a81f0c00",
    )
    for manifest, expected in zip((v1, v2), expected_serialization_hashes, strict=True):
        fixed = replace(manifest, created_at=datetime(2026, 9, 6, tzinfo=UTC))
        serialized = json.dumps(fixed.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert sha256(serialized.encode()).hexdigest() == expected
        assert OnlyResearchResultManifest.from_dict(json.loads(serialized)) == fixed
