from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_SURFACES = (
    ROOT / "deploy",
    ROOT / "scripts",
    ROOT / ".github/workflows",
    ROOT / "tests/architecture",
    ROOT / "tests/certification",
    ROOT / "tests/integration",
    ROOT / "tests/strategy",
    ROOT / "pyproject.toml",
    ROOT / "quality-policy.toml",
)

PHASE_COUPLING = re.compile(
    r"(?i)(?<![a-z0-9])(?:p\d+(?:[._-]?\d+)?(?:[._-]?k\d+)?|"
    r"closure[._-]?\d+|phase[._-]?\d+|increment[._-]?\d+|a" + r"0)(?![a-z0-9])"
)

# These are exact durable identities, not a directory-wide waiver. Their
# historical spelling remains part of a manifest or one-shot contract.
SERIALIZED_CONTRACT_ALLOWLIST = {
    "a0_golden_v1": "immutable Binance Golden bundle_kind in the persisted manifest contract",
    "a0_binance_golden": "approved immutable source-manifest fixture path",
    "authorized-a0-corrections": "one-shot OpenAPI pre-freeze correction manifest path",
    "a0-pre-freeze-contract-correction": "accepted ADR identity referenced by the correction manifest",
    "authorized_a0_corrections": "in-code authority handle for that exact manifest",
    "authorized_a0_correction": "serialized OpenAPI correction result identity",
    "required_a0_contract_correction": "manifest classification bound to the accepted ADR",
    "p9_calculation_equivalence_v2": "historical serialized calculation-equivalence evidence identity",
    "onlyalpha_p9_calculation_equivalence_v2": "historical serialized calculation-equivalence authority identity",
}

SERIALIZED_CONTRACT_PATH_ALLOWLIST = {
    "contracts/product-api/v2/authorized-a0-corrections.json": "one-shot OpenAPI correction manifest",
    "test-data/a0_binance_golden/source-manifest.json": "approved immutable Binance source manifest fixture",
}


def _active_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for surface in ACTIVE_SURFACES:
        if surface.is_file():
            files.append(surface)
            continue
        files.extend(
            path
            for path in surface.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    return tuple(sorted(files))


def _match_is_allowlisted(line: str, match: re.Match[str]) -> bool:
    normalized = line.casefold()
    match_start, match_end = match.span()
    return any(
        marker_start <= match_start and match_end <= marker_start + len(marker)
        for marker in SERIALIZED_CONTRACT_ALLOWLIST
        for marker_start in range(len(normalized))
        if normalized.startswith(marker, marker_start)
    )


def test_active_integration_surfaces_use_capability_names() -> None:
    violations: list[str] = []
    for path in _active_files():
        relative = path.relative_to(ROOT).as_posix()
        path_match = PHASE_COUPLING.search(relative)
        if path_match and relative not in SERIALIZED_CONTRACT_PATH_ALLOWLIST:
            violations.append(f"{relative}: path contains {path_match.group(0)!r}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in PHASE_COUPLING.finditer(line):
                if not _match_is_allowlisted(line, match):
                    violations.append(f"{relative}:{line_number}: {match.group(0)!r}")
    assert violations == []


def test_serialized_contract_allowlist_is_explicit_and_narrow() -> None:
    assert SERIALIZED_CONTRACT_ALLOWLIST
    assert SERIALIZED_CONTRACT_PATH_ALLOWLIST
    assert all("*" not in entry and "?" not in entry for entry in SERIALIZED_CONTRACT_PATH_ALLOWLIST)
    assert all(reason.strip() for reason in SERIALIZED_CONTRACT_ALLOWLIST.values())
    assert all(reason.strip() for reason in SERIALIZED_CONTRACT_PATH_ALLOWLIST.values())
