"""Read-only MiniQMT environment diagnostics."""

import argparse
import json

from .config import OnlyMiniQmtConfig
from .errors import OnlyMiniQmtError
from .sdk.loader import load_xtquant


def diagnose(config: OnlyMiniQmtConfig) -> dict[str, object]:
    checks: dict[str, object] = {
        "userdata_mini": config.userdata_mini_path.is_dir(),
        "xtquant": False,
        "market_data": False,
        "trading_api": False,
        "account_configured": bool(config.account_id),
    }
    try:
        sdk = load_xtquant()
        checks["xtquant"] = True
        checks["market_data"] = sdk.xtdata.__name__ == "xtquant.xtdata"
        checks["trading_api"] = (
            sdk.xttrader.__name__ == "xtquant.xttrader"
            and sdk.xttype.__name__ == "xtquant.xttype"
        )
    except OnlyMiniQmtError as exc:
        checks["error"] = exc.to_dict()
    checks["ok"] = all(
        bool(checks[key])
        for key in ("userdata_mini", "xtquant", "market_data", "trading_api")
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-miniqmt")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--userdata-mini-path")
    doctor.add_argument("--account-id", default="")
    args = parser.parse_args()
    config = OnlyMiniQmtConfig.parse(
        {
            key: value
            for key, value in {
                "userdata_mini_path": args.userdata_mini_path,
                "account_id": args.account_id,
            }.items()
            if value
        }
    )
    result = diagnose(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
