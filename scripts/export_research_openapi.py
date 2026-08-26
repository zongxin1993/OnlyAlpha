"""Backward-compatible wrapper for the single OpenAPI governance command."""

from __future__ import annotations

from collections.abc import Sequence

from openapi_contract import main as governance_main


def main(argv: Sequence[str] | None = None) -> int:
    return governance_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
