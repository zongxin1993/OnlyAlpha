"""Select and check exact native build inputs; selection is not publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import release_sources
from scripts.dev_verification import source_inputs
from scripts.release_sources import encode as encode
from scripts.version_sync import load_release_units


def candidate(root: Path, *, source_bundles: Path | None = None) -> dict[str, Any]:
    inputs = source_inputs(root)
    required = ("Cargo.lock", "uv.lock", "packages/frontend/package-lock.json", "rust-toolchain.toml")
    if not all(name in inputs for name in required):
        raise ValueError("RELEASE_INPUT_MISSING")
    target = {
        "aarch64": "aarch64-unknown-linux-gnu",
        "arm64": "aarch64-unknown-linux-gnu",
        "x86_64": "x86_64-unknown-linux-gnu",
    }
    value = {
        "schema_version": 1,
        "source_inputs": inputs,
        "versions": load_release_units(root),
        "build": {
            "target": target[platform.machine()],
            "profile": "release",
            "features": [],
            "default_features": True,
            "toolchain": tomllib.loads((root / "rust-toolchain.toml").read_text())["toolchain"]["channel"],
            "web_environment": {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"},
        },
    }
    if source_bundles is not None:
        value["sources"] = release_sources.selections(root, source_bundles)
    return value


def verify(root: Path, path: Path, digest: str, *, source_bundles: Path | None = None) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("RELEASE_INPUT_SYMLINK")
    try:
        raw = path.read_bytes()
        selected = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != digest or raw != encode(candidate(root, source_bundles=source_bundles)):
            raise ValueError("RELEASE_INPUT_SELECTION_MISMATCH")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("RELEASE_INPUT_INVALID") from error
    return {
        "sha256": digest,
        **{key: value for key, value in selected.items() if key not in {"schema_version", "source_inputs"}},
    }


def verify_receipt(receipt: dict[str, Any], inputs: dict[str, str]) -> None:
    """The existing artifact manifest owns source bytes; do not duplicate them."""
    selected = {
        "schema_version": 1,
        "source_inputs": inputs,
        "versions": receipt["versions"],
        "build": receipt["build"],
    }
    if "sources" in receipt:
        selected["sources"] = receipt["sources"]
    if (
        set(receipt) - {"sources"} != {"sha256", "versions", "build"}
        or hashlib.sha256(encode(selected)).hexdigest() != receipt["sha256"]
    ):
        raise ValueError("RELEASE_INPUT_RECEIPT_MISMATCH")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("candidate", "check"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--source-bundles", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.mode == "candidate":
        with args.path.open("xb") as output:
            output.write(encode(candidate(root, source_bundles=args.source_bundles)))
        print(hashlib.sha256(args.path.read_bytes()).hexdigest())
    elif not args.sha256:
        parser.error("check requires an independently selected --sha256")
    else:
        print(json.dumps(verify(root, args.path, args.sha256, source_bundles=args.source_bundles), sort_keys=True))


if __name__ == "__main__":
    main()
