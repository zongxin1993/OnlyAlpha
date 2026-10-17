"""Independent Boolean/UTF-8 string equality facts, not backend execution output."""

from __future__ import annotations

import argparse
from pathlib import Path


def render_vectors() -> bytes:
    boolean_pairs = (
        ("tt", True, True, "EQ"),
        ("tf", True, False, "NE"),
        ("tn", True, None, "NULL"),
        ("ft", False, True, "NE"),
        ("ff", False, False, "EQ"),
        ("fn", False, None, "NULL"),
        ("nt", None, True, "NULL"),
        ("nf", None, False, "NULL"),
        ("nn", None, None, "NULL"),
    )
    string_pairs = (
        ("empty", "", "", "EQ"),
        ("ascii", "BTCUSD", "BTCUSD", "EQ"),
        ("unicode", "商品", "商品", "EQ"),
        ("combining", "e\u0301", "e\u0301", "EQ"),
        ("nul", "\0", "\0", "EQ"),
        ("controls", "\t\n\r", "\t\n\r", "EQ"),
        ("emoji", "👩‍💻", "👩‍💻", "EQ"),
        ("maximum_scalar", "\U0010ffff", "\U0010ffff", "EQ"),
        ("long", "x" * 512, "x" * 512, "EQ"),
        ("case", "A", "a", "NE"),
        ("normalization", "é", "e\u0301", "NE"),
        ("compatibility", "ﬃ", "ffi", "NE"),
        ("width", "Ａ", "A", "NE"),
        ("whitespace", "", " ", "NE"),
        ("controls_different", "\t", "\n", "NE"),
        ("nul_suffix", "a\0", "a", "NE"),
        ("nul_tail", "a\0b", "a\0c", "NE"),
        ("non_bmp", "🙂", "🙃", "NE"),
        ("variation_selector", "❤", "❤️", "NE"),
        ("long_tail", "x" * 512 + "a", "x" * 512 + "b", "NE"),
        ("text_null", "null", "", "NE"),
        ("missing_left", None, "null", "NULL"),
        ("missing_right", "null", None, "NULL"),
        ("missing_both", None, None, "NULL"),
    )
    tables = {"eq": {"EQ": "true", "NE": "false", "NULL": "null"}, "ne": {"EQ": "false", "NE": "true", "NULL": "null"}}
    lines = ["case_id\ttype_id\tsemantic_version\tleft\tright\tliteral\tliteral_left\texpected"]
    for family, pairs in (("boolean", boolean_pairs), ("string", string_pairs)):

        def token(value: bool | str | None) -> str:
            if value is None:
                return "null"
            if type(value) is bool:
                return "true" if value else "false"
            assert isinstance(value, str)
            return "utf8:" + value.encode("utf-8").hex()

        for op, table in tables.items():
            for label, left, right, relation in pairs:
                variants = [(label, left, right)]
                if family == "string" and relation == "NE":
                    variants.append((label + "_reversed", right, left))
                for case, a, b in variants:
                    prefix = f"{family}:{op}:{case}"
                    type_id = f"onlyalpha.predicate.internal.compare.{op}.{family}"
                    expected = table[relation]
                    lines.append(f"{prefix}:refs\t{type_id}.refs\t1\t{token(a)}\t{token(b)}\t-\t-\t{expected}")
                    for literal_left in (False, True):
                        value, literal = (b, a) if literal_left else (a, b)
                        if literal is None:
                            continue
                        position = "true" if literal_left else "false"
                        lines.append(
                            f"{prefix}:literal:{position}\t{type_id}.literal\t1\t{token(value)}\t-\t{token(literal)}\t{position}\t{expected}"
                        )
    return ("\n".join(lines) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "test-data/predicate/scalar-equality-v1.tsv"
    expected = render_vectors()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Scalar equality vectors differ from explicit equality facts\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
