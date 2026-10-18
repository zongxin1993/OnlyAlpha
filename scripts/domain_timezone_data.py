"""Verify Rust's exact TZif inputs against the pinned upstream Python package."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def validate_index(domain: Path, dataset: dict[str, Any]) -> None:
    expected = (
        f"// Generated from pinned Python tzdata {dataset['version']} / IANA {dataset['iana_version']}. Do not edit zone bytes.\n"
        "#[rustfmt::skip]\n"
        "pub(crate) const ZONES: &[(&str, &[u8])] = &[\n"
        + "".join(
            f'    ("{name}", include_bytes!("../resources/tzdata/{dataset["version"]}/{name}")),\n'
            for name in sorted(dataset["zones"])
        )
        + "];\n"
    )
    if (domain / "src/tzdb_rules.rs").read_text() != expected:
        raise ValueError("DOMAIN_TIMEZONE_INDEX_MISMATCH")


def main() -> None:
    domain = ROOT / "crates/onlyalpha-kernel/domain"
    root = domain / "resources/tzdata/2026.3"
    dataset = json.loads((root / "dataset.json").read_text())
    validate_index(domain, dataset)
    if version("tzdata") != dataset["version"]:
        raise ValueError("DOMAIN_TIMEZONE_DATASET_MISMATCH")
    with files("tzdata.zoneinfo").joinpath("tzdata.zi").open("r", encoding="utf-8") as stream:
        if stream.readline().strip() != f"# version {dataset['iana_version']}":
            raise ValueError("DOMAIN_TIMEZONE_DATASET_MISMATCH")
    for name, expected in dataset["zones"].items():
        data = (root / name).read_bytes()
        upstream = files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
        if not data.startswith(b"TZif") or hashlib.sha256(data).hexdigest() != expected or data != upstream:
            raise ValueError(f"DOMAIN_TIMEZONE_DATASET_MISMATCH:{name}")
    print(f"DOMAIN_PINNED_TZIF: {len(dataset['zones'])} identical zones")


if __name__ == "__main__":
    main()
