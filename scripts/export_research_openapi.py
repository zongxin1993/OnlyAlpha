from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from onlyalpha_api import create_app

from onlyalpha.research.artifact.model import OnlyResearchArtifact

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/research-api/v2/openapi.json"


class _ContractReader:
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchArtifact:
        raise RuntimeError(f"OpenAPI generation must not load Artifact {research_result_fingerprint}")


def rendered_contract() -> str:
    return json.dumps(create_app(_ContractReader()).openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    args = parser.parse_args(argv)
    rendered = rendered_contract()
    if args.mode == "write":
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(rendered, encoding="utf-8")
        return 0
    if not CONTRACT.is_file() or CONTRACT.read_text(encoding="utf-8") != rendered:
        raise SystemExit("Research API OpenAPI contract is stale; run export_research_openapi.py write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
