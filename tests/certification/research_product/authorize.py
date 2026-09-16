from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.certification.research_product.support import authorize_research_specification


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: authorize USER_DATA_ROOT RUNTIME_GENERATION_ROOT COMMAND_ID")
    authorize_research_specification(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        sys.argv[3],
        json.load(sys.stdin),
    )


if __name__ == "__main__":
    main()
