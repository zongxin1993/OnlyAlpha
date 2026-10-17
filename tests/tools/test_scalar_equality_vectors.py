from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "mutation", ["expected", "owner", "input", "literal", "position", "unicode", "duplicate", "truncated"]
)
def test_scalar_equality_guard_rejects_every_changed_semantic_dimension(tmp_path: Path, mutation: str) -> None:
    script = tmp_path / "scripts/scalar_equality_vectors.py"
    script.parent.mkdir()
    script.write_bytes((ROOT / "scripts/scalar_equality_vectors.py").read_bytes())
    corpus = tmp_path / "test-data/predicate/scalar-equality-v1.tsv"
    corpus.parent.mkdir(parents=True)
    original = (ROOT / "test-data/predicate/scalar-equality-v1.tsv").read_bytes()
    corpus.write_bytes(original)
    command = [sys.executable, str(script), "--check"]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    rows = original.splitlines(keepends=True)
    if mutation == "expected":
        rows[1] = rows[1].replace(b"\ttrue\n", b"\tfalse\n")
    elif mutation == "owner":
        rows[1] = rows[1].replace(b".eq.boolean.refs", b".ne.boolean.refs")
    elif mutation == "input":
        fields = rows[1].split(b"\t")
        fields[3] = b"false"
        rows[1] = b"\t".join(fields)
    elif mutation in ("literal", "position"):
        index = next(i for i, row in enumerate(rows) if b".boolean.literal\t" in row)
        fields = rows[index].split(b"\t")
        fields[5 if mutation == "literal" else 6] = b"false" if mutation == "literal" else b"true"
        rows[index] = b"\t".join(fields)
    elif mutation == "unicode":
        rows = [row.replace(b"utf8:c3a9", b"utf8:65cc81") for row in rows]
    elif mutation == "duplicate":
        rows.append(rows[1])
    else:
        rows.pop()
    altered = b"".join(rows)
    assert altered != original
    corpus.write_bytes(altered)
    assert subprocess.run(command, capture_output=True, check=False).returncode == 1
