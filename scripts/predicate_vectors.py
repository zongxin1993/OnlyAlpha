"""Regenerate portable Boolean Predicate vectors from explicit contract truth tables."""

from __future__ import annotations

import argparse
from pathlib import Path


def render_vectors() -> bytes:
    # Expected values are contract tables, never outputs captured from either implementation.
    values = ("true", "false", "null")
    tables = {
        "boolean.and": ("true", "false", "null", "false", "false", "false", "null", "false", "null"),
        "boolean.or": ("true", "true", "true", "true", "false", "null", "true", "null", "null"),
        "boolean.not": ("false", "true", "null"),
        "terminal.eligibility": values,
        "terminal.entry_signal": values,
        "terminal.exit_signal": values,
    }
    lines = ["case_id\ttype_id\tsemantic_version\tleft\tright\texpected"]
    for name, outputs in tables.items():
        pairs = (
            [(left, right) for left in values for right in values]
            if len(outputs) == 9
            else [(v, "null") for v in values]
        )
        for (left, right), expected in zip(pairs, outputs, strict=True):
            case = f"{name}:{left}:{right}"
            lines.append(f"{case}\tonlyalpha.predicate.internal.{name}\t1\t{left}\t{right}\t{expected}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "test-data/predicate/boolean-v1.tsv"
    expected = render_vectors()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Predicate vectors differ from the explicit contract truth tables\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
