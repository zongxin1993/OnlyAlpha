"""Record finite Decimal comparisons from explicit mathematical relations, not evaluator output."""

from __future__ import annotations

import argparse
from pathlib import Path


def render_vectors() -> bytes:
    pairs = (
        ("zero", "0", "0", "EQ"),
        ("signed_zero", "-0.000", "0.00", "EQ"),
        ("scale", "1.0", "1.0000", "EQ"),
        ("integer_scale", "1000.00", "1000", "EQ"),
        ("negative_scale", "-123.4500", "-123.45", "EQ"),
        ("fraction_scale", "0.000100", "0.0001", "EQ"),
        ("wide_equal", "9" * 100 + ".00", "9" * 100, "EQ"),
        ("positive", "0", "0.0001", "LT"),
        ("negative", "-0.0001", "-0", "LT"),
        ("cross_sign", "-0.01", "0.01", "LT"),
        ("integer_digits", "9.999", "10.000", "LT"),
        ("negative_integer_digits", "-10", "-9.999", "LT"),
        ("fraction_digits", "0.009", "0.01", "LT"),
        ("negative_fraction_digits", "-0.01", "-0.009", "LT"),
        ("fraction_prefix", "1.2", "1.20001", "LT"),
        ("same_integer", "123.456", "123.457", "LT"),
        ("different_integer", "123.999", "124.000", "LT"),
        ("below_quantum", "0.000000001", "0.000000002", "LT"),
        ("beyond_float", "9007199254740992.0", "9007199254740993.0", "LT"),
        ("beyond_context", "1234567890123456789012345678.1", "1234567890123456789012345678.2", "LT"),
        ("wide_fraction", "1." + "0" * 100 + "1", "1." + "0" * 100 + "2", "LT"),
        ("tiny_fraction", "0." + "0" * 100 + "1", "0." + "0" * 100 + "2", "LT"),
        ("huge_integer", "9" * 100 + ".9", "1" + "0" * 100, "LT"),
        ("negative_huge", "-1" + "0" * 100, "-" + "9" * 100 + ".9", "LT"),
        ("missing_left", "null", "0.1", "NULL"),
        ("missing_right", "0.1", "null", "NULL"),
        ("missing_both", "null", "null", "NULL"),
    )
    tables = {
        "eq": {"LT": "false", "EQ": "true", "GT": "false", "NULL": "null"},
        "ne": {"LT": "true", "EQ": "false", "GT": "true", "NULL": "null"},
        "lt": {"LT": "true", "EQ": "false", "GT": "false", "NULL": "null"},
        "le": {"LT": "true", "EQ": "true", "GT": "false", "NULL": "null"},
        "gt": {"LT": "false", "EQ": "false", "GT": "true", "NULL": "null"},
        "ge": {"LT": "false", "EQ": "true", "GT": "true", "NULL": "null"},
    }
    lines = ["case_id\ttype_id\tsemantic_version\tleft\tright\texpected"]
    for op, table in tables.items():
        for label, left, right, relation in pairs:
            variants = [(label, left, right, relation)]
            if relation == "LT":
                variants.append((label + "_reversed", right, left, "GT"))
            for case, a, b, order in variants:
                lines.append(
                    f"{op}:{case}\tonlyalpha.predicate.internal.compare.{op}.decimal.refs\t1\t{a}\t{b}\t{table[order]}"
                )
    return ("\n".join(lines) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "test-data/predicate/decimal-refs-v1.tsv"
    expected = render_vectors()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Decimal Predicate vectors differ from explicit mathematical relations\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
