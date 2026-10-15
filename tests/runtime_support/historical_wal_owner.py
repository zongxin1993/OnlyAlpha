"""Independent process probing the Product historical WAL root owner."""

from __future__ import annotations

import sys
from pathlib import Path

from filelock import Timeout

from onlyalpha.application.market_data_product import _only_historical_root_lock


def main() -> None:
    owner = _only_historical_root_lock(Path(sys.argv[1]))
    try:
        owner.acquire(timeout=0)
    except Timeout:
        print("BLOCKED", flush=True)
        owner.acquire()
    try:
        print("ACQUIRED", flush=True)
        sys.stdin.readline()
    finally:
        owner.release()


if __name__ == "__main__":
    main()
