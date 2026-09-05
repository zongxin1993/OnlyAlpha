"""Test-owned deterministic process barrier around existing production boundaries."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event
from typing import Any

from onlyalpha.persistence.postgres import OnlyPostgresResearchExecutionStore
from onlyalpha.research.artifact.store import OnlyParquetResearchArtifactStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.worker_main import main as worker_main
from tests.runtime_generation_process_support import only_allow_unsealed_test_process_generation


def _block(barrier: Path, boundary: str) -> None:
    barrier.write_text(json.dumps({"boundary": boundary}), encoding="utf-8")
    Event().wait()


def _wrap(target: type[object], method_name: str, barrier: Path, boundary: str, *, after: bool) -> None:
    original: Callable[..., Any] = getattr(target, method_name)

    def wrapped(self: object, *args: object, **kwargs: object) -> object:
        if after:
            outcome = original(self, *args, **kwargs)
            _block(barrier, boundary)
            return outcome
        _block(barrier, boundary)
        return original(self, *args, **kwargs)

    setattr(target, method_name, wrapped)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("boundary", choices=("C1", "C2", "C3", "C4"))
    parser.add_argument("--barrier", type=Path, required=True)
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--runtime-generation-authority-root", type=Path, required=True)
    parser.add_argument("--runtime-generation-fingerprint", required=True)
    args = parser.parse_args(argv)
    if args.boundary == "C1":
        _wrap(
            OnlyParquetResearchDatasetSnapshotStore,
            "load_verified_table",
            args.barrier,
            args.boundary,
            after=False,
        )
    elif args.boundary == "C2":
        _wrap(OnlyJsonResearchResultStore, "commit", args.barrier, args.boundary, after=False)
    elif args.boundary == "C3":
        _wrap(OnlyParquetResearchArtifactStore, "commit", args.barrier, args.boundary, after=False)
    else:
        _wrap(OnlyPostgresResearchExecutionStore, "complete", args.barrier, args.boundary, after=False)
    only_allow_unsealed_test_process_generation()
    return worker_main(
        [
            "--user-data-root",
            str(args.user_data_root),
            "--polling-seconds",
            "0.05",
            "--lease-seconds",
            "30",
            "--heartbeat-seconds",
            "12",
            "--runtime-generation-authority-root",
            str(args.runtime_generation_authority_root),
            "--runtime-generation-fingerprint",
            args.runtime_generation_fingerprint,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
