"""Strict classification of co-located Statistics authority families."""

from __future__ import annotations

import json
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.source_cut import OnlySourceCutError, only_sha256_source_inventory


def only_statistics_family_inventory(root: Path, family_name: str) -> tuple[str, ...]:
    """Classify every published artifact; unknown schemas block certification."""
    from .summary.family import only_research_statistics_family

    matching: list[str] = []
    for locator in only_sha256_source_inventory(root):
        target = root / "sha256" / locator[:2] / locator
        manifest = target / "manifest.json"
        try:
            if target.is_symlink() or not target.is_dir() or manifest.is_symlink():
                raise ValueError("unsafe Statistics path")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("noncanonical Statistics manifest")
            kind = only_research_statistics_family(payload)
        except (OSError, ValueError, TypeError) as exc:
            raise OnlySourceCutError("STATISTICS_CUT_UNKNOWN_FAMILY") from exc
        if kind.value == family_name:
            matching.append(locator)
    return tuple(matching)
