from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mutation", ["expected", "version", "owner", "duplicate", "truncated"])
def test_predicate_vector_guard_rejects_changed_recorded_bytes(tmp_path: Path, mutation: str) -> None:
    script = tmp_path / "scripts/predicate_vectors.py"
    script.parent.mkdir()
    script.write_bytes((_ROOT / "scripts/predicate_vectors.py").read_bytes())
    corpus = tmp_path / "test-data/predicate/boolean-v1.tsv"
    corpus.parent.mkdir(parents=True)
    original = (_ROOT / "test-data/predicate/boolean-v1.tsv").read_bytes()
    corpus.write_bytes(original)
    command = [sys.executable, str(script), "--check"]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    rows = original.splitlines(keepends=True)
    if mutation == "expected":
        fields = rows[1].decode().rstrip("\n").split("\t")
        fields[-1] = "false"
        rows[1] = ("\t".join(fields) + "\n").encode()
    elif mutation == "version":
        rows[1] = rows[1].replace(b"\t1\t", b"\t2\t")
    elif mutation == "owner":
        rows[1] = rows[1].replace(b".boolean.and\t", b".boolean.or\t")
    elif mutation == "duplicate":
        rows.append(rows[1])
    else:
        rows.pop()
    corpus.write_bytes(b"".join(rows))
    result = subprocess.run(command, capture_output=True, check=False)
    assert result.returncode == 1
    assert b"differ from the explicit contract truth tables" in result.stderr
