from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "PROJECT_CONSTITUTION.md"
FINGERPRINT = ROOT / "docs" / "governance" / "PROJECT_CONSTITUTION.sha256"
AGENTS = ROOT / "AGENTS.md"


def fail(message: str) -> None:
    raise SystemExit(f"governance check failed: {message}")


def main() -> None:
    if not CONSTITUTION.is_file():
        fail("PROJECT_CONSTITUTION.md is missing")
    if not FINGERPRINT.is_file():
        fail("constitution fingerprint is missing")
    if not AGENTS.is_file():
        fail("AGENTS.md is missing")

    parts = FINGERPRINT.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1] != "PROJECT_CONSTITUTION.md":
        fail("invalid constitution fingerprint format")

    expected = parts[0].lower()
    actual = hashlib.sha256(CONSTITUTION.read_bytes()).hexdigest()
    if actual != expected:
        fail(
            "PROJECT_CONSTITUTION.md does not match the pinned fingerprint "
            f"(expected {expected}, got {actual})"
        )

    agents = AGENTS.read_text(encoding="utf-8")
    required_markers = (
        "PROJECT_CONSTITUTION.md",
        "PLAN_CONFLICT",
        "MUST 首先完整阅读并理解",
        "Constitution Impact",
    )
    missing = [marker for marker in required_markers if marker not in agents]
    if missing:
        fail(f"AGENTS.md lost mandatory constitutional instructions: {missing!r}")

    print(f"constitution OK: sha256={actual}")


if __name__ == "__main__":
    main()
