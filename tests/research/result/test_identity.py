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
        "c6216713e54d22c9f2101dee7f7ef74d86a4b45af39a1a5b67f159172e3f6801",
        "382c6d5fc7b0c8e84683bea80bf923c30186565cf7bb17d8cfd89dada2b1b90b",
        "c373c509a6850acb6d94cd40d2499fe4631ca78b8c6ef2affde11bbc12214fa5",
    )
    assert (
        v2.research_result_plan_fingerprint,
        v2.research_result_content_fingerprint,
        v2.research_result_fingerprint,
    ) == (
        "00639e25b538ea378792791abbebd8da3f34da17820a104ac3ee2e60b5940dab",
        "3a218e50ed78b6d5484e8de96587baaf7c353112820c868cd868a5cd46687cc5",
        "e062f457a2e98f5a8dfda531b8ce210db8297ef36dcbe13fd4ef8833672b7a5b",
    )
    expected_serialization_hashes = (
        "cdf390e8965838b6f6194bef3bc3b7666c12ead60b4a5b086a48d9bd7232e2c0",
        "dd806d27180296325bf3191547bfd59f1069a9b6db6933de343d070bb6afb98f",
    )
    for manifest, expected in zip((v1, v2), expected_serialization_hashes, strict=True):
        fixed = replace(manifest, created_at=datetime(2026, 9, 6, tzinfo=UTC))
        serialized = json.dumps(fixed.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert sha256(serialized.encode()).hexdigest() == expected
        assert OnlyResearchResultManifest.from_dict(json.loads(serialized)) == fixed
