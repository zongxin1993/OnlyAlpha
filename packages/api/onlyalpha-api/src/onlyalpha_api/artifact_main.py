"""Explicit server composition root for a portable Research Artifact directory."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from onlyalpha.research.artifact.store import OnlyParquetResearchArtifactStore

from .app import create_artifact_query_app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-artifact-api")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    reader = OnlyParquetResearchArtifactStore(args.artifact_root)
    uvicorn.run(create_artifact_query_app(reader), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
