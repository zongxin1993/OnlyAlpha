from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mutation", ["expected", "precision", "owner", "duplicate", "truncated"])
def test_decimal_vector_guard_rejects_changes(tmp_path: Path, mutation: str) -> None:
    script = tmp_path / "scripts/decimal_predicate_vectors.py"
    script.parent.mkdir()
    script.write_bytes((ROOT / "scripts/decimal_predicate_vectors.py").read_bytes())
    corpus = tmp_path / "test-data/predicate/decimal-refs-v1.tsv"
    corpus.parent.mkdir(parents=True)
    original = (ROOT / "test-data/predicate/decimal-refs-v1.tsv").read_bytes()
    corpus.write_bytes(original)
    command = [sys.executable, str(script), "--check"]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    rows = original.splitlines(keepends=True)
    if mutation == "expected":
        rows[1] = rows[1].replace(b"\ttrue\n", b"\tfalse\n")
    elif mutation == "precision":
        rows = [row.replace(b"9007199254740993.0", b"9007199254740992.0") for row in rows]
    elif mutation == "owner":
        rows[1] = rows[1].replace(b".eq.decimal.refs", b".ne.decimal.refs")
    elif mutation == "duplicate":
        rows.append(rows[1])
    else:
        rows.pop()
    corpus.write_bytes(b"".join(rows))
    assert subprocess.run(command, capture_output=True, check=False).returncode == 1
