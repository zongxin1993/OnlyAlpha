"""The Rust zone-name lookup must select the exact pinned file for that name."""

import json
from pathlib import Path

import pytest

from scripts import domain_timezone_data as check


@pytest.mark.parametrize("mutation", ["swap", "duplicate", "missing", "unsorted"])
def test_rejects_zone_lookup_mapping_mutations(tmp_path: Path, mutation: str) -> None:
    domain = Path(__file__).resolve().parents[2] / "crates/onlyalpha-kernel/domain"
    source = domain / "src/tzdb_rules.rs"
    lines = source.read_text().splitlines(keepends=True)
    if mutation == "swap":
        lines[3] = lines[3].replace("resources/tzdata/2026.3/Africa/Abidjan", "resources/tzdata/2026.3/Africa/Accra")
    elif mutation == "duplicate":
        lines.insert(4, lines[3])
    elif mutation == "missing":
        del lines[3]
    else:
        lines[3], lines[4] = lines[4], lines[3]
    target = tmp_path / "src/tzdb_rules.rs"
    target.parent.mkdir()
    target.write_text("".join(lines))
    dataset = json.loads((domain / "resources/tzdata/2026.3/dataset.json").read_text())
    with pytest.raises(ValueError, match="DOMAIN_TIMEZONE_INDEX_MISMATCH"):
        check.validate_index(tmp_path, dataset)
