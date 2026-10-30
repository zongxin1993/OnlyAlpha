"""Exact managed installation and bounded frame reads; no business authority."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import BinaryIO


def read(stream: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def verify_installation(root: Path, expected: str) -> None:
    raw = (root / "algorithm-installation.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("CHART_INSTALLATION_UNAVAILABLE")
    manifest = json.loads(raw)
    if manifest["interpreter_sha256"] != hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest():
        raise ValueError("CHART_INTERPRETER_CHANGED")
    if sys.path != manifest["python_paths"]:
        raise ValueError("CHART_IMPORT_PATH_CHANGED")
    for name, digest in manifest["environment_files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("CHART_ENVIRONMENT_CHANGED")
    for name, digest in manifest["runtime_files"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError("CHART_NUMERIC_RUNTIME_CHANGED")
    for name, digest in manifest["files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("CHART_INSTALLATION_CHANGED")
    packages = root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    actual = {str(path.relative_to(root)) for path in packages.rglob("*") if path.is_file()}
    if actual != set(manifest["files"]) or any(path.suffix == ".pth" for path in packages.rglob("*")):
        raise ValueError("CHART_INSTALLATION_CLOSURE_CHANGED")
