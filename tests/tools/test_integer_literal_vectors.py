from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "mutation", ["expected", "precision", "owner", "duplicate", "truncated", "position", "literal"]
)
def test_integer_literal_vector_guard_rejects_changes(tmp_path: Path, mutation: str) -> None:
    script = tmp_path / "scripts/integer_literal_vectors.py"
    script.parent.mkdir()
    script.write_bytes((ROOT / "scripts/integer_literal_vectors.py").read_bytes())
    (script.parent / "integer_predicate_vectors.py").write_bytes(
        (ROOT / "scripts/integer_predicate_vectors.py").read_bytes()
    )
    corpus = tmp_path / "test-data/predicate/integer-literal-v1.tsv"
    corpus.parent.mkdir(parents=True)
    original = (ROOT / "test-data/predicate/integer-literal-v1.tsv").read_bytes()
    corpus.write_bytes(original)
    command = [sys.executable, str(script), "--check"]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    rows = original.splitlines(keepends=True)
    if mutation == "expected":
        rows[1] = rows[1].replace(b"\ttrue\n", b"\tfalse\n")
    elif mutation == "precision":
        rows = [row.replace(b"9007199254740993", b"9007199254740992") for row in rows]
    elif mutation == "owner":
        rows[1] = rows[1].replace(b".eq.integer.literal", b".ne.integer.literal")
    elif mutation == "duplicate":
        rows.append(rows[1])
    elif mutation == "position":
        rows[1] = rows[1].replace(b"\tfalse\t", b"\ttrue\t")
    elif mutation == "literal":
        fields = rows[1].split(b"\t")
        fields[4] = b"1"
        rows[1] = b"\t".join(fields)
    else:
        rows.pop()
    corpus.write_bytes(b"".join(rows))
    assert subprocess.run(command, capture_output=True, check=False).returncode == 1
