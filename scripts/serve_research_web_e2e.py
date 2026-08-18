from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from onlyalpha_api import create_artifact_query_app  # noqa: E402

from tests.research.query.support import query_case  # noqa: E402


def main() -> int:
    with TemporaryDirectory(prefix="onlyalpha-web-e2e-") as raw_root:
        root = Path(raw_root)
        *_, candidate, store, _ = query_case(root)
        artifact = store.load_verified(candidate.research_result_fingerprint)
        for name in ("datasets", "calculation-results", "statistics-results", "research-results"):
            source = root / name
            if source.exists():
                source.rename(root / f"unavailable-{name}")
        if not artifact.rows:
            raise RuntimeError("E2E fixture must contain exact Statistics rows")
        uvicorn.run(create_artifact_query_app(store), host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
