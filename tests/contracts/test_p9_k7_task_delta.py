from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
P9_K7_TASK_BASE_SHA = "baa91014ec4e0197ac5c34f41138abc68c18471a"
P9_K7_VERIFIED_CLOSURE_SHA = "f74ddd273f600ef076b459a500b6073d2ab0cb78"
PRODUCT_OPENAPI = Path("contracts/research-api/v2/openapi.json")
PROTECTED_P9_SEMANTIC_PATHS = (
    "src/onlyalpha/research",
    "src/onlyalpha/strategy",
    "src/onlyalpha/application",
    "src/onlyalpha/kernel",
    "src/onlyalpha/runtime",
    "src/onlyalpha/execution",
)

pytestmark = [pytest.mark.contract, pytest.mark.historical_git]


def _require_commit(revision: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise AssertionError(f"required P9.K.7 audit commit is unavailable: {revision}")


def test_missing_required_k7_task_baseline_fails_closed() -> None:
    with pytest.raises(AssertionError, match="required P9.K.7 audit commit is unavailable"):
        _require_commit("0" * 40)


def test_product_openapi_was_byte_identical_during_k7() -> None:
    _require_commit(P9_K7_TASK_BASE_SHA)
    _require_commit(P9_K7_VERIFIED_CLOSURE_SHA)
    baseline = subprocess.run(
        ["git", "show", f"{P9_K7_TASK_BASE_SHA}:{PRODUCT_OPENAPI.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    closure = subprocess.run(
        ["git", "show", f"{P9_K7_VERIFIED_CLOSURE_SHA}:{PRODUCT_OPENAPI.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert closure == baseline


def test_protected_p9_semantic_sources_were_unchanged_during_k7() -> None:
    _require_commit(P9_K7_TASK_BASE_SHA)
    _require_commit(P9_K7_VERIFIED_CLOSURE_SHA)
    changed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            P9_K7_TASK_BASE_SHA,
            P9_K7_VERIFIED_CLOSURE_SHA,
            "--",
            *PROTECTED_P9_SEMANTIC_PATHS,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert changed == ""
