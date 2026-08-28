"""Submit and inspect a Research Run through the governed Product API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from onlyalpha_client import JSONValue, OnlyAlphaClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path, help="Resolved Research Specification JSON")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--idempotency-key", required=True, help="Caller-retained canonical UUID4 command identity")
    args = parser.parse_args()
    raw = json.loads(args.specification.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError("Research specification must be one JSON object")
    with OnlyAlphaClient(base_url=args.base_url) as client:
        accepted = client.research.create(
            specification=cast(dict[str, JSONValue], raw),
            idempotency_key=args.idempotency_key,
        )
        run = client.research.get(accepted["run"]["run_id"])
    print(json.dumps(run, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
