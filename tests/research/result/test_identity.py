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
        "3b64271f49607b744f669c85230c28c47565a13decd49176d1f59b071a1078b1",
        "e3941921eb094e8bf1443d3aae512bf8002af9bb7ae520b97979ff06535f1b34",
        "76c838643e6f456eb9a4a16fbe31c1b6361964a10ef7ec942f375f8cd076b27d",
    )
    assert (
        v2.research_result_plan_fingerprint,
        v2.research_result_content_fingerprint,
        v2.research_result_fingerprint,
    ) == (
        "782c4e29a7fc2d7b36f80a8882db905ee00c70f2634133a4da77811a859152fe",
        "1b655f4580a1b195b4af128db7218089abc4c61df26e27ed0aac503d3ee615a9",
        "5f83d24daa97c02aa9f5e6d3b4d3aa5fc85d1fbb6cfd7df9db857b4678c1bdd5",
    )
    expected_serialization_hashes = (
        "66fa5759ebeea384e57d669805f9af2ec589d295067ca2a4fb6e4c3979e1b154",
        "4c2408d84e6a5ede4454bf6edb5b4d0e2e1c81f4ea0069e68b61168e1a0c6756",
    )
    for manifest, expected in zip((v1, v2), expected_serialization_hashes, strict=True):
        fixed = replace(manifest, created_at=datetime(2026, 9, 6, tzinfo=UTC))
        serialized = json.dumps(fixed.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert sha256(serialized.encode()).hexdigest() == expected
        assert OnlyResearchResultManifest.from_dict(json.loads(serialized)) == fixed
