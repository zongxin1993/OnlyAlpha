from __future__ import annotations

import argparse
import sys

from .config import OnlyTushareConfig
from .data_source.validation import only_validate_response
from .sdk.adapter import OnlyTushareSdkClient
from .sdk.loader import load_tushare
from .errors import OnlyTushareError


def main() -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-tushare")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser(
        "doctor", help="run a minimal read-only Tushare check"
    )
    doctor.add_argument("--token-env", default="ONLYALPHA_TUSHARE_TOKEN")
    doctor.add_argument("--symbol", default="600000.SH")
    doctor.add_argument("--start-date", default="20260101")
    doctor.add_argument("--end-date", default="20260107")
    args = parser.parse_args()
    config = OnlyTushareConfig(token_env=args.token_env)
    try:
        client = OnlyTushareSdkClient(load_tushare(), config.resolve_token())
        response = client.pro_bar(
            ts_code=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date,
            asset="E",
            freq="D",
            adj=None,
        )
        rows, _ = only_validate_response(response, args.symbol)
    except OnlyTushareError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print(
            "TUSHARE_REQUEST_FAILED: read-only pro_bar request failed", file=sys.stderr
        )
        return 1
    print(f"Tushare doctor OK: sdk/client/query/schema, rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
