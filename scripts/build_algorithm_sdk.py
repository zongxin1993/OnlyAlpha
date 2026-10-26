"""Build and install the current minimal algorithm closure, without editable imports.

The existing OnlyAlpha distribution supplies only its necessary SDK files here;
this is the worker's exact installation artifact, not a second backend distribution.
"""

from __future__ import annotations

import _decimal
import argparse
import base64
import csv
import decimal
import hashlib
import importlib.metadata as metadata
import io
import json
import os
import subprocess
import sys
import sysconfig
import tomllib
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = (
    "canonical.py",
    "calculation/definition.py",
    "calculation/implementation.py",
    "calculation/decimal_execution.py",
    "calculation/chart_decimal.py",
    "calculation/chart_study.py",
    "calculation/value_semantics.py",
    "algorithm/__init__.py",
    "algorithm/batch.py",
    "algorithm/private_factor.py",
)
INDICATORS = (
    "definitions.py",
    "research.py",
    "chart.py",
    "calibrated.py",
    "financial_semantics.py",
    "chart_factory.py",
)
WORKER = ("codec.py", "type_declaration.py", "chart_worker.py", "chart_isolation.py")


def distribution_version(distribution: str) -> str:
    if distribution.startswith("onlyalpha-plugin-"):
        path = ROOT / "plugs" / distribution / "pyproject.toml"
        return str(tomllib.loads(path.read_text())["project"]["version"])
    path = ROOT / "packages/backend/Cargo.toml"
    return str(tomllib.loads(path.read_text())["package"]["version"])


def wheel(output: Path, distribution: str, sources: dict[str, bytes], dependencies: tuple[str, ...]) -> Path:
    version = distribution_version(distribution)
    name = distribution.replace("-", "_")
    info = f"{name}-{version}.dist-info"
    sources = dict(sources)
    sources[f"{info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\nSummary: Exact minimal OnlyAlpha algorithm closure\n"
        + "".join(
            f"Requires-Dist: {d}=={distribution_version(d)}\n" if d.startswith("onlyalpha") else f"Requires-Dist: {d}\n"
            for d in dependencies
        )
    ).encode()
    sources[f"{info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: OnlyAlpha canonical algorithm builder\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for path, content in sorted(sources.items()):
        writer.writerow(
            (
                path,
                "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("="),
                len(content),
            )
        )
    writer.writerow((f"{info}/RECORD", "", ""))
    sources[f"{info}/RECORD"] = record.getvalue().encode()
    wheel_path = output / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, content in sorted(sources.items()):
            entry = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100444 << 16
            archive.writestr(entry, content)
    return wheel_path


def build(output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    sdk = {"onlyalpha/" + name: (ROOT / "src/onlyalpha" / name).read_bytes() for name in SDK}
    sdk["onlyalpha/__init__.py"] = b'"""Minimal mathematical authoring SDK; no business services."""\n'
    sdk["onlyalpha/calculation/__init__.py"] = (
        b"from onlyalpha.calculation.definition import *\nfrom onlyalpha.calculation.decimal_execution import only_decimal_context, only_quantize_decimal\n"
    )
    plugin = {
        "onlyalpha_plugin_indicators/" + name: (
            ROOT / "plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators" / name
        ).read_bytes()
        for name in INDICATORS
    }
    plugin["onlyalpha_plugin_indicators/__init__.py"] = b'"""Installed pure Indicator algorithms."""\n'
    worker = {
        "onlyalpha_calculation_worker/" + name: (
            ROOT / "packages/onlyalpha-calculation-worker/src/onlyalpha_calculation_worker" / name
        ).read_bytes()
        for name in WORKER
    }
    worker["onlyalpha_calculation_worker/__init__.py"] = b'"""Pure bounded algorithm process."""\n'
    gateway = {"onlyalpha_gateway_protocol/__init__.py": b"", "onlyalpha_gateway_protocol/v1/__init__.py": b""}
    # This is the exact generated canonical projection, never a hand-written wire family.
    for name in ("calculation_pb2.py",):
        gateway["onlyalpha_gateway_protocol/v1/" + name] = (
            ROOT / "packages/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1" / name
        ).read_bytes()
    return [
        wheel(output, "onlyalpha", sdk, ()),
        wheel(output, "onlyalpha-plugin-indicators", plugin, ("onlyalpha", "pyarrow")),
        wheel(
            output,
            "onlyalpha-calculation-worker",
            worker,
            ("onlyalpha", "onlyalpha-plugin-indicators", "onlyalpha-gateway-protocol", "protobuf"),
        ),
        wheel(output, "onlyalpha-gateway-protocol", gateway, ("protobuf",)),
    ]


def install(output: Path, destination: Path) -> str:
    if destination.exists():
        raise ValueError("ALGORITHM_INSTALLATION_ALREADY_EXISTS")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("ALGORITHM_PYTHON_VERSION_UNAVAILABLE")
    wheels = build(output)
    venv.EnvBuilder(with_pip=False, symlinks=False).create(destination)
    # CPython may add an unused lib64 -> lib alias even with symlinks=False.
    # The admitted installation uses the explicit lib/... paths below only.
    alias = destination / "lib64"
    if alias.is_symlink():
        if alias.readlink() != Path("lib"):
            raise ValueError("ALGORITHM_INSTALLATION_LAYOUT_INVALID")
        alias.unlink()
    elif alias.exists():
        raise ValueError("ALGORITHM_INSTALLATION_LAYOUT_INVALID")

    site = destination / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    for path in wheels:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(site)
    for name in ("pyarrow", "protobuf"):
        dist = metadata.distribution(name)
        if not dist.files:
            raise ValueError("ALGORITHM_DEPENDENCY_RECORD_UNAVAILABLE")
        for entry in dist.files:
            relative = Path(str(entry))
            if relative.is_absolute() or ".." in relative.parts or relative.suffix == ".pth":
                raise ValueError("ALGORITHM_DEPENDENCY_CLOSURE_INVALID")
            source = Path(str(dist.locate_file(entry)))
            if source.suffix == ".pyc" or "__pycache__" in source.parts:
                continue
            if source.is_symlink() or not source.is_file():
                raise ValueError("ALGORITHM_DEPENDENCY_FILE_INVALID")
            content = source.read_bytes()
            if entry.hash is not None:
                if (
                    entry.hash.mode != "sha256"
                    or base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                    != entry.hash.value
                ):
                    raise ValueError("ALGORITHM_DEPENDENCY_RECORD_MISMATCH")
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    # Remove activation helpers: the admitted process has one interpreter entry.
    for path in (destination / "bin").iterdir():
        if path.name != "python":
            path.unlink()
    runtime_files = {
        str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (
            decimal.__file__,
            _decimal.__file__,
            str(Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")),
        )
    }
    python_paths = json.loads(
        subprocess.check_output(
            [str(destination / "bin/python"), "-B", "-I", "-c", "import json,sys;print(json.dumps(sys.path))"], env={}
        )
    )
    files = {
        str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(site.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": 1,
        "kind": "ONLYALPHA_ALGORITHM_INSTALLATION",
        "distribution_version": distribution_version("onlyalpha"),
        "interpreter_sha256": hashlib.sha256((destination / "bin/python").read_bytes()).hexdigest(),
        "files": files,
        "environment_files": {"pyvenv.cfg": hashlib.sha256((destination / "pyvenv.cfg").read_bytes()).hexdigest()},
        "runtime_files": runtime_files,
        "python_paths": python_paths,
        "wheels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels},
        "dependencies": {name: metadata.version(name) for name in ("pyarrow", "protobuf")},
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (destination / "algorithm-installation.json").write_bytes(payload)
    for directory, children, names in os.walk(destination, topdown=False):
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o555 if path.parent == destination / "bin" else 0o444)
        for name in children:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o555)
    destination.chmod(0o555)
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--install", type=Path)
    args = parser.parse_args()
    if args.install:
        print(install(args.output, args.install))
    else:
        for path in build(args.output):
            print(path)


if __name__ == "__main__":
    main()
