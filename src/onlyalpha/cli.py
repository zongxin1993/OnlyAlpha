"""OnlyAlpha unified command-line entry."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.defaults import only_default_run_service


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = OnlyRunConfig.load(args.config)
    service = only_default_run_service()
    result = service.run(config)
    print(result.to_dict())
    return 0 if str(result.status) not in {"FAILED", "UNSUPPORTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
