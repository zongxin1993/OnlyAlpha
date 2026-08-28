"""Product CLI implemented exclusively through :mod:`onlyalpha_client`."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from .client import OnlyAlphaClient
from .errors import OnlyAlphaClientError
from .generated.contract import JSONValue


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onlyalpha-client")
    parser.add_argument("--base-url", default=os.environ.get("ONLYALPHA_API_URL", "http://127.0.0.1:8000"))
    research = parser.add_subparsers(dest="resource", required=True).add_parser("research")
    commands = research.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("specification", type=Path)
    create.add_argument("--idempotency-key", required=True)
    get = commands.add_parser("get")
    get.add_argument("run_id")
    list_runs = commands.add_parser("list")
    list_runs.add_argument("--limit", type=int, default=50)
    list_runs.add_argument("--cursor")
    cancel = commands.add_parser("cancel")
    cancel.add_argument("run_id")
    cancel.add_argument("--idempotency-key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        with OnlyAlphaClient(base_url=cast(str, args.base_url)) as client:
            result: object
            if args.command == "create":
                raw = json.loads(cast(Path, args.specification).read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
                    raise ValueError("Research specification must be one JSON object")
                result = client.research.create(
                    specification=cast(dict[str, JSONValue], raw),
                    idempotency_key=cast(str, args.idempotency_key),
                )
            elif args.command == "get":
                result = client.research.get(cast(str, args.run_id))
            elif args.command == "list":
                result = client.research.list(limit=cast(int, args.limit), cursor=cast(str | None, args.cursor))
            else:
                result = client.research.cancel(
                    cast(str, args.run_id),
                    idempotency_key=cast(str | None, args.idempotency_key),
                )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError, OnlyAlphaClientError) as exc:
        print(f"onlyalpha-client: {exc}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
