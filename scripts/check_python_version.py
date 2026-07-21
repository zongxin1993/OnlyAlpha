from __future__ import annotations

import sys


def main() -> int:
    expected = (3, 12)
    actual = sys.version_info[:2]

    if actual != expected:
        print(
            f"OnlyAlpha requires Python {expected[0]}.{expected[1]}; current interpreter is {actual[0]}.{actual[1]}.",
            file=sys.stderr,
        )
        return 1

    print(f"Python version check passed: {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
