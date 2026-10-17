"""Record exact integer Predicate comparisons from explicit ordered examples."""

from __future__ import annotations

import argparse
from pathlib import Path


def render_vectors() -> bytes:
    # Relations are independently declared mathematical facts, never backend output.
    pairs = (
        ("zero", "0", "0", "EQ"),
        ("negative_equal", "-999", "-999", "EQ"),
        ("positive", "0", "1", "LT"),
        ("negative", "-1", "0", "LT"),
        ("cross_sign", "-100", "1", "LT"),
        ("digit_count", "9", "10", "LT"),
        ("negative_digit_count", "-10", "-9", "LT"),
        ("same_width", "123", "124", "LT"),
        ("negative_same_width", "-124", "-123", "LT"),
        ("float_precision", "9007199254740992", "9007199254740993", "LT"),
        ("negative_float_precision", "-9007199254740993", "-9007199254740992", "LT"),
        ("signed_minimum", "-9223372036854775808", "-9223372036854775807", "LT"),
        ("signed_maximum", "9223372036854775806", "9223372036854775807", "LT"),
        ("unsigned_boundary", "18446744073709551615", "18446744073709551616", "LT"),
        ("wide_boundary", "170141183460469231731687303715884105727", "170141183460469231731687303715884105728", "LT"),
        ("many_digits", "9" * 100, "1" + "0" * 100, "LT"),
        ("negative_many_digits", "-1" + "0" * 100, "-" + "9" * 100, "LT"),
        ("large_equal", "1" + "0" * 100, "1" + "0" * 100, "EQ"),
        ("missing_left", "null", "0", "NULL"),
        ("missing_right", "0", "null", "NULL"),
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
                    f"{op}:{case}\tonlyalpha.predicate.internal.compare.{op}.integer.refs\t1\t{a}\t{b}\t{table[order]}"
                )
    return ("\n".join(lines) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "test-data/predicate/integer-refs-v1.tsv"
    expected = render_vectors()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Integer Predicate vectors differ from explicit ordered examples\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
