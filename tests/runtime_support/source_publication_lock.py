"""Controlled subprocess probe for source-owned publication exclusion."""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

from onlyalpha.research.source_cut import OnlySourcePublicationBarrier


def main() -> None:
    root, mode = Path(sys.argv[1]), sys.argv[2]
    operation = fcntl.LOCK_SH if mode == "publication" else fcntl.LOCK_EX
    descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            print("blocked", flush=True)
        else:
            raise AssertionError("conflicting owning lock was not held")
    finally:
        os.close(descriptor)
    barrier = OnlySourcePublicationBarrier(root)
    context = barrier.publication() if mode == "publication" else barrier.inspect_readonly()
    with context:
        print("entered", flush=True)


if __name__ == "__main__":
    main()
