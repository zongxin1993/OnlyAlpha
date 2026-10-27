"""Immutable per-unit source artifacts, with no extraction or publication on consumption."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dev_verification import source_inputs
from scripts.release_metadata import load_release_units
from scripts.runtime_artifacts import encode as encode
from scripts.rust_kernel_check import _workspace_packages

CONTEXT_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    "pyproject.toml",
    "uv.lock",
    "packages/frontend/package-lock.json",
)


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == name
        and "\\" not in name
    )


def _workspace(root: Path, unit: str) -> dict[str, Any]:
    if unit == "frontend" or (
        unit.startswith("plugin-") and not (root / "plugs" / ("onlyalpha-" + unit) / "Cargo.toml").is_file()
    ):
        return {}
    workspace = tomllib.loads((root / "Cargo.toml").read_text())["workspace"]
    value = {key: data for key, data in workspace.items() if key != "members"}
    value["package"] = dict(workspace["package"])
    # Backend/plugin versions are independent; the selected libs own this field.
    if unit != "libs":
        value["package"].pop("version", None)
    return value


def _paths(root: Path, unit: str, inputs: dict[str, str]) -> set[str]:
    if unit not in load_release_units(root):
        raise ValueError("RELEASE_SOURCE_UNKNOWN_UNIT")
    members = _workspace_packages(root)
    if unit == "libs":
        prefixes = [path.as_posix() + "/" for path, _ in members.values() if path.parts[0] == "crates"]
    elif unit in {"backend", "frontend"}:
        prefixes = [f"packages/{unit}/"]
    else:
        prefixes = ["plugs/onlyalpha-" + unit + "/"]
    selected = {name for name in inputs if any(name.startswith(prefix) for prefix in prefixes)}
    if not selected:
        raise ValueError("RELEASE_SOURCE_EMPTY_UNIT")
    if "LICENSE" in inputs:
        selected.add("LICENSE")
    if unit == "libs":
        selected.update(name for name in inputs if name.startswith("contracts/gateway/"))
        selected.update(
            name for name in ("scripts/gateway_protocol.py", "scripts/domain_timezone_data.py") if name in inputs
        )
    if unit == "backend":
        selected.update(name for name in inputs if name.startswith(("database/postgres/migrations/", "contracts/")))
        selected.update(
            "scripts/" + name
            for name in (
                "native_workstation_build.py",
                "native_http_contract.py",
                "market_data_stream_contract.py",
                "build_algorithm_sdk.py",
                "dev_verification.py",
                "release_inputs.py",
                "release_sources.py",
                "release_metadata.py",
                "runtime_artifacts.py",
                "runtime_build.py",
                "version_sync.py",
                "rust_kernel_check.py",
            )
            if "scripts/" + name in inputs
        )
        sdk_builder = root / "scripts/build_algorithm_sdk.py"
        if sdk_builder.exists():
            sdk = next(
                ast.literal_eval(node.value)
                for node in ast.parse(sdk_builder.read_text()).body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SDK" for t in node.targets)
            )
            selected.update("src/onlyalpha/" + name for name in sdk)
    # Follow literal compile-time Rust inputs, including independently owned vectors.
    # Dynamic includes require an explicit closure design, never silent omission.
    for name in list(selected):
        if not name.endswith(".rs"):
            continue
        text = (root / name).read_text()
        includes = list(re.finditer(r'\binclude_(?:str|bytes)\s*!\s*\(\s*"([^"\n]+)"\s*\)', text))
        if len(includes) != len(re.findall(r"\binclude_(?:str|bytes)\s*!", text)):
            raise ValueError("RELEASE_SOURCE_UNDECLARED_INPUT")
        for match in includes:
            resolved = (root / name).parent.joinpath(match[1]).resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError("RELEASE_SOURCE_PATH_INVALID")
            selected.add(resolved.relative_to(root.resolve()).as_posix())
    if not selected <= inputs.keys():
        raise ValueError("RELEASE_SOURCE_MISSING_INPUT")
    return selected


def inventory(root: Path, unit: str) -> dict[str, Any]:
    inputs = source_inputs(root)
    paths = _paths(root, unit, inputs)
    return {
        "unit": unit,
        "version": load_release_units(root)[unit],
        "workspace": _workspace(root, unit),
        "files": {
            name: {"sha256": inputs[name], "execute_bits": (root / name).stat().st_mode & 0o111}
            for name in sorted(paths)
        },
    }


def required_units(root: Path) -> set[str]:
    packages = _workspace_packages(root)
    pending = ["onlyalpha-backend"]
    visited: set[str] = set()
    result: set[str] = {"libs"}
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        directory, manifest = packages[name]
        if directory.parts[0] == "plugs":
            result.add(name.removeprefix("onlyalpha-"))
        for table in (manifest, *manifest.get("target", {}).values()):
            for kind in ("dependencies", "build-dependencies"):
                for alias, value in table.get(kind, {}).items():
                    dependency = value.get("package", alias) if isinstance(value, dict) else alias
                    if (
                        isinstance(value, dict)
                        and "path" in value
                        and (
                            dependency not in packages
                            or (root / directory / value["path"]).resolve()
                            != (root / packages[dependency][0]).resolve()
                        )
                    ):
                        raise ValueError("RELEASE_SOURCE_UNDECLARED_DEPENDENCY")
                    if dependency in packages:
                        pending.append(dependency)
    executor = tomllib.loads((root / "packages/backend/python/algorithms/pyproject.toml").read_text())
    for raw in executor["project"]["dependencies"]:
        dependency_name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", raw)
        if dependency_name is not None and re.sub(r"[-_.]+", "-", dependency_name[1]).lower().startswith(
            "onlyalpha-plugin-"
        ):
            match = re.fullmatch(
                r"onlyalpha-(plugin-[a-z0-9]+(?:-[a-z0-9]+)*)\s*==\s*[0-9]+\.[0-9]+\.[0-9]+", raw.strip()
            )
            if match is None:
                raise ValueError("RELEASE_SOURCE_DEPENDENCY_UNPINNED")
            result.add(match[1])
    if not result <= load_release_units(root).keys():
        raise ValueError("RELEASE_SOURCE_DEPENDENCY_UNKNOWN")
    return result


def _zip(manifest: dict[str, Any], payloads: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted({"manifest.json": encode(manifest), **payloads}.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100444 << 16
            archive.writestr(entry, raw)
    return output.getvalue()


def export(root: Path, unit: str, revision: str, output: Path, *, tag: str | None = None) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None or revision == "0" * 40:
        raise ValueError("RELEASE_SOURCE_EXACT_REVISION_REQUIRED")
    git = ["git", "--no-replace-objects", "-C", str(root)]
    if subprocess.check_output([*git, "rev-parse", "--verify", revision + "^{commit}"], text=True).strip() != revision:
        raise ValueError("RELEASE_SOURCE_REVISION_INVALID")
    # Archive attributes (including uncommitted .git/info/attributes) must never
    # filter/substitute exact committed bytes. Batch raw blobs in tree order.
    tree = subprocess.check_output([*git, "ls-tree", "-r", "-z", "--full-tree", revision])
    entries = []
    for record in tree.split(b"\0"):
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        relative = name.decode("utf-8")
        if mode not in {"100644", "100755"} or kind != "blob" or not _safe_name(relative):
            raise ValueError("RELEASE_SOURCE_PATH_INVALID")
        entries.append((mode, oid, relative))
    raw = subprocess.check_output(
        [*git, "cat-file", "--batch"], input="".join(oid + "\n" for _, oid, _ in entries).encode()
    )
    blobs = io.BytesIO(raw)
    with tempfile.TemporaryDirectory(prefix="onlyalpha-source-") as temporary:
        snapshot = Path(temporary)
        for mode, oid, relative in entries:
            blob_oid, kind, size = blobs.readline().decode().split()
            content = blobs.read(int(size))
            if (
                blob_oid != oid
                or kind != "blob"
                or len(content) != int(size)
                or blobs.read(1) != b"\n"
                or hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() != oid
            ):
                raise ValueError("RELEASE_SOURCE_OBJECT_INVALID")
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o555 if mode == "100755" else 0o444)
        if blobs.read(1):
            raise ValueError("RELEASE_SOURCE_OBJECT_INVALID")
        manifest = inventory(snapshot, unit)
        if tag is not None and (
            tag != f"{unit}-v{manifest['version']}"
            or subprocess.check_output(
                [*git, "rev-parse", "--verify", "refs/tags/" + tag + "^{commit}"], text=True
            ).strip()
            != revision
        ):
            raise ValueError("RELEASE_SOURCE_TAG_MISMATCH")
        manifest.update(schema_version=1, revision=revision, tag=tag)
        if any(not (snapshot / name).is_file() for name in CONTEXT_FILES):
            raise ValueError("RELEASE_SOURCE_CONTEXT_MISSING")
        manifest["context"] = {
            name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest() for name in CONTEXT_FILES
        }
        payloads = {"source/" + name: (snapshot / name).read_bytes() for name in manifest["files"]}
        payloads.update({"context/" + name: (snapshot / name).read_bytes() for name in manifest["context"]})
        bundle = _zip(manifest, payloads)
    with output.open("xb") as target:
        target.write(bundle)
    return hashlib.sha256(bundle).hexdigest()


def verify(root: Path, unit: str, path: Path, digest: str) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError("RELEASE_SOURCE_SYMLINK")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("RELEASE_SOURCE_DIGEST_MISMATCH")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or any(not _safe_name(name) for name in names):
                raise ValueError("RELEASE_SOURCE_PATH_INVALID")
            manifest: dict[str, Any] = json.loads(archive.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or not isinstance(manifest.get("context"), dict)
                or set(manifest["context"]) != set(CONTEXT_FILES)
            ):
                raise ValueError("RELEASE_SOURCE_MANIFEST_INVALID")
            expected = inventory(root, unit)
            if set(manifest) != {*expected, "schema_version", "revision", "tag", "context"} or encode(
                {key: manifest[key] for key in expected}
            ) != encode(expected):
                raise ValueError("RELEASE_SOURCE_CONTENT_MISMATCH")
            if (
                type(manifest["schema_version"]) is not int
                or manifest["schema_version"] != 1
                or re.fullmatch(r"[0-9a-f]{40}", manifest["revision"]) is None
                or manifest["revision"] == "0" * 40
            ):
                raise ValueError("RELEASE_SOURCE_ORIGIN_INVALID")
            if manifest["tag"] is not None and manifest["tag"] != f"{unit}-v{manifest['version']}":
                raise ValueError("RELEASE_SOURCE_TAG_MISMATCH")
            payloads = {name: archive.read(name) for name in names if name != "manifest.json"}
            expected_payloads = {"source/" + name: item["sha256"] for name, item in manifest["files"].items()}
            expected_payloads.update({"context/" + name: sha for name, sha in manifest["context"].items()})
            if {
                name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()
            } != expected_payloads or raw != _zip(manifest, payloads):
                raise ValueError("RELEASE_SOURCE_PAYLOAD_MISMATCH")
        return manifest
    except (OSError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ValueError("RELEASE_SOURCE_INVALID") from error


def selections(root: Path, path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError("RELEASE_SOURCE_SYMLINK")
        references = json.loads(path.read_text())
        if not isinstance(references, dict) or set(references) != required_units(root):
            raise ValueError("RELEASE_SOURCE_SELECTION_INCOMPLETE")
        result = {}
        for unit, reference in sorted(references.items()):
            if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
                raise ValueError("RELEASE_SOURCE_REFERENCE_INVALID")
            bundle = Path(reference["path"])
            if not bundle.is_absolute():
                bundle = path.parent / bundle
            manifest = verify(root, unit, bundle, reference["sha256"])
            result[unit] = {
                "sha256": reference["sha256"],
                "version": manifest["version"],
                "revision": manifest["revision"],
                "tag": manifest["tag"],
                "content_sha256": hashlib.sha256(
                    encode({key: manifest[key] for key in ("unit", "version", "workspace", "files")})
                ).hexdigest(),
            }
        return result
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("RELEASE_SOURCE_SELECTION_INVALID") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit")
    parser.add_argument("revision", help="exact nonzero commit SHA, never HEAD/latest")
    parser.add_argument("output", type=Path)
    parser.add_argument("--tag", help="optional existing exact release tag; never created")
    args = parser.parse_args()
    print(export(Path(__file__).resolve().parents[1], args.unit, args.revision, args.output, tag=args.tag))


if __name__ == "__main__":
    main()
