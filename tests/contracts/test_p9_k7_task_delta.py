from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
P9_K7_TASK_BASE_SHA = "baa91014ec4e0197ac5c34f41138abc68c18471a"
PRODUCT_OPENAPI = Path("contracts/research-api/v2/openapi.json")
PROTECTED_P9_SEMANTIC_PATHS = (
    "src/onlyalpha/research",
    "src/onlyalpha/strategy",
    "src/onlyalpha/application",
    "src/onlyalpha/kernel",
    "src/onlyalpha/runtime",
    "src/onlyalpha/execution",
)


def _require_commit(base: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise AssertionError(f"required P9.K.7 task baseline is unavailable: {base}")


@pytest.mark.contract
def test_missing_required_k7_task_baseline_fails_closed() -> None:
    with pytest.raises(AssertionError, match="required P9.K.7 task baseline is unavailable"):
        _require_commit("0" * 40)


@pytest.mark.contract
def test_product_openapi_is_byte_identical_to_k7_task_base() -> None:
    _require_commit(P9_K7_TASK_BASE_SHA)
    baseline = subprocess.run(
        ["git", "show", f"{P9_K7_TASK_BASE_SHA}:{PRODUCT_OPENAPI.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert (ROOT / PRODUCT_OPENAPI).read_bytes() == baseline


@pytest.mark.contract
def test_protected_p9_semantic_sources_are_unchanged_from_k7_task_base() -> None:
    _require_commit(P9_K7_TASK_BASE_SHA)
    changed = subprocess.run(
        ["git", "diff", "--name-only", P9_K7_TASK_BASE_SHA, "--", *PROTECTED_P9_SEMANTIC_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert changed == ""
