from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from onlyalpha_plugin_miniqmt.config import OnlyMiniQmtConfig
from onlyalpha_plugin_miniqmt.doctor import diagnose
from onlyalpha_plugin_miniqmt.sdk.loader import load_xtquant


def main() -> int:
    userdata = os.environ.get("userdata_mini_path") or os.environ.get("ONLYALPHA_MINIQMT_PATH")
    account_id = os.environ.get("ONLYALPHA_MINIQMT_ACCOUNT_ID", "")
    if not userdata or not account_id:
        print(
            "MiniQMT local verification requires userdata_mini_path and ONLYALPHA_MINIQMT_ACCOUNT_ID", file=sys.stderr
        )
        return 2
    config = OnlyMiniQmtConfig(Path(userdata), account_id)
    result = diagnose(config)
    if not result["ok"]:
        print(result, file=sys.stderr)
        return 2
    sdk = load_xtquant()
    session_id = int(time.time() * 1000) % 2_147_483_647
    trader = sdk.xttrader.XtQuantTrader(str(config.require_path()), session_id)
    account = sdk.xttype.StockAccount(account_id)
    trader.start()
    try:
        if trader.connect() != 0:
            raise RuntimeError("MiniQMT trader read-only connection failed")
        if trader.subscribe(account) != 0:
            raise RuntimeError("MiniQMT account subscription failed")
        queries = {
            "account": trader.query_stock_asset(account),
            "positions": trader.query_stock_positions(account),
            "orders": trader.query_stock_orders(account),
            "trades": trader.query_stock_trades(account),
        }
        if queries["account"] is None:
            raise RuntimeError("MiniQMT account query returned no account snapshot")
        print({key: 1 if key == "account" else len(value or ()) for key, value in queries.items()})
    finally:
        trader.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
