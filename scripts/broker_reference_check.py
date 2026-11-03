"""Frozen normalized Broker observations with exact v2 identities.

Technical codec/replay inputs captured before producer retirement, not execution of
an active Virtual Broker or Shipping Web/Runtime acceptance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def virtual_corpus(root: Path = ROOT) -> list[dict[str, Any]]:
    raw = (root / "test-data/broker/virtual-v2.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != "19e716b18c7382a86e1bf733c3c9cb279323dfcc793c4d1094cc588dfeda7d69":
        raise ValueError("BROKER_VIRTUAL_FIXTURE_DRIFT")
    result: list[dict[str, Any]] = json.loads(raw)
    return result


if __name__ == "__main__":
    print(json.dumps(virtual_corpus(), ensure_ascii=False, sort_keys=True))
