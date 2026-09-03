"""Read-only access to non-production Strategy authoring assets."""

import json
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast

_ASSET_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")


def strategy_asset_resource(
    asset_name: str,
    relative_path: str,
    *,
    library_root: str | Path | None = None,
) -> Traversable:
    """Resolve one named asset resource from a checkout or installed distribution."""

    if _ASSET_NAME.fullmatch(asset_name) is None:
        raise ValueError("Strategy asset name must be canonical lower-case text")
    if relative_path not in {"metadata.json", "research-definition.json"}:
        raise ValueError("Strategy asset resource is unsupported")
    if library_root is not None:
        root = Path(library_root).expanduser().resolve()
        asset_root = (root / asset_name).resolve()
        if root not in asset_root.parents:
            raise ValueError("Strategy asset escapes the library root")
        candidate = (asset_root / relative_path).resolve()
        if candidate.parent != asset_root or not candidate.is_file():
            raise FileNotFoundError(f"Strategy asset resource is unavailable: {asset_name}/{relative_path}")
        return candidate

    packaged = files(__package__).joinpath(asset_name, relative_path)
    if packaged.is_file():
        return packaged
    source_checkout = Path(__file__).resolve().parents[2] / asset_name / relative_path
    if source_checkout.is_file():
        return source_checkout
    raise FileNotFoundError(f"Strategy asset resource is unavailable: {asset_name}/{relative_path}")


def strategy_definition_resource(
    asset_name: str,
    *,
    library_root: str | Path | None = None,
) -> Traversable:
    """Resolve one named authoring document from a checkout or installed distribution."""

    return strategy_asset_resource(asset_name, "research-definition.json", library_root=library_root)


def read_strategy_definition(asset_name: str, *, library_root: str | Path | None = None) -> str:
    """Read exact authoring JSON without importing OnlyAlpha Runtime."""

    return strategy_definition_resource(asset_name, library_root=library_root).read_text(encoding="utf-8")


def load_strategy_definition(asset_name: str, *, library_root: str | Path | None = None) -> dict[str, object]:
    """Decode one authoring document for Product Definition submission."""

    payload = json.loads(read_strategy_definition(asset_name, library_root=library_root))
    if not isinstance(payload, dict):
        raise ValueError("Strategy authoring document must be a JSON object")
    return cast(dict[str, object], payload)


def simple_momentum_definition_path(*, library_root: str | Path | None = None) -> Path:
    """Return a filesystem path when the resource is source/editable/unpacked."""

    resource = strategy_definition_resource("simple_momentum", library_root=library_root)
    candidate = Path(str(resource))
    if not candidate.is_file():
        raise RuntimeError("Packaged Strategy resource has no filesystem path; use read_strategy_definition()")
    return candidate


__all__ = [
    "load_strategy_definition",
    "read_strategy_definition",
    "simple_momentum_definition_path",
    "strategy_asset_resource",
    "strategy_definition_resource",
]
