"""Record DECIMAL literal cases from independently declared mathematical relations."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.decimal_predicate_vectors import render_vectors as render_reference_vectors  # noqa: E402


def render_vectors() -> bytes:
    # Reuse explicit relation tables, never registered Python/Rust execution output.
    lines = ["case_id\ttype_id\tsemantic_version\tinput\tliteral\tliteral_left\texpected"]
    for row in csv.DictReader(io.StringIO(render_reference_vectors().decode("ascii")), delimiter="\t"):
        for literal_left in (False, True):
            value, literal = (row["right"], row["left"]) if literal_left else (row["left"], row["right"])
            if literal == "null":
                continue  # Required literal parameters are never missing.
            position = "true" if literal_left else "false"
            lines.append(
                f"{row['case_id']}:{position}\t{row['type_id'].replace('.refs', '.literal')}\t1"
                f"\t{value}\t{literal}\t{position}\t{row['expected']}"
            )
    return ("\n".join(lines) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "test-data/predicate/decimal-literal-v1.tsv"
    expected = render_vectors()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Decimal literal vectors differ from explicit ordered examples\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
