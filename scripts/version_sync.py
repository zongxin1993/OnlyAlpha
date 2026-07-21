from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version
from tomlkit import dumps, parse

ROOT = Path(__file__).resolve().parents[1]
ROOT_PYPROJECT = ROOT / "pyproject.toml"

FORMAL_PACKAGES = (
    ROOT / "packages/provider/onlyalpha-plugin-tushare/pyproject.toml",
    ROOT / "packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml",
)

TEST_PACKAGES = (ROOT / "tests/fixtures/external_plugins/onlyalpha_test_plugin/pyproject.toml",)


class VersionSyncError(RuntimeError):
    """Raised when monorepo versions are inconsistent."""


def read_document(path: Path) -> Any:
    if not path.is_file():
        raise VersionSyncError(f"missing pyproject.toml: {path}")

    return parse(path.read_text(encoding="utf-8"))


def write_document(path: Path, document: Any) -> None:
    path.write_text(dumps(document), encoding="utf-8")


def root_version() -> str:
    document = read_document(ROOT_PYPROJECT)
    value = str(document["project"]["version"])
    Version(value)
    return value


def replace_onlyalpha_dependency(
    dependencies: list[Any],
    version: str,
    *,
    path: Path,
) -> None:
    replacement = f"onlyalpha=={version}"
    matched = False

    for index, dependency in enumerate(dependencies):
        dependency_text = str(dependency).strip()

        if (
            dependency_text == "onlyalpha"
            or dependency_text.startswith("onlyalpha==")
            or dependency_text.startswith("onlyalpha>=")
            or dependency_text.startswith("onlyalpha<")
            or dependency_text.startswith("onlyalpha~=")
            or dependency_text.startswith("onlyalpha!=")
        ):
            dependencies[index] = replacement
            matched = True

    if not matched:
        raise VersionSyncError(f"{path}: project.dependencies does not contain onlyalpha")


def set_versions(version: str) -> None:
    try:
        normalized = str(Version(version))
    except InvalidVersion as exc:
        raise VersionSyncError(f"invalid version: {version}") from exc

    if normalized != version:
        raise VersionSyncError(f"version must already be normalized: {version!r} -> {normalized!r}")

    root_document = read_document(ROOT_PYPROJECT)
    root_document["project"]["version"] = version
    write_document(ROOT_PYPROJECT, root_document)

    for path in FORMAL_PACKAGES:
        document = read_document(path)
        document["project"]["version"] = version

        dependencies = document["project"].get("dependencies")
        if dependencies is None:
            raise VersionSyncError(f"{path}: missing project.dependencies")

        replace_onlyalpha_dependency(
            dependencies,
            version,
            path=path,
        )
        write_document(path, document)

    for path in TEST_PACKAGES:
        document = read_document(path)

        dependencies = document["project"].get("dependencies")
        if dependencies is None:
            raise VersionSyncError(f"{path}: missing project.dependencies")

        replace_onlyalpha_dependency(
            dependencies,
            version,
            path=path,
        )
        write_document(path, document)

    subprocess.run(
        ["uv", "lock", "--python", "3.12"],
        cwd=ROOT,
        check=True,
    )

    check_versions()


def expected_dependency(version: str) -> str:
    return f"onlyalpha=={version}"


def check_dependency(
    document: Any,
    *,
    version: str,
    path: Path,
) -> list[str]:
    errors: list[str] = []
    dependencies = document["project"].get("dependencies", [])
    matches = [str(item) for item in dependencies if str(item).strip().startswith("onlyalpha")]

    expected = expected_dependency(version)

    if matches != [expected]:
        errors.append(f"{path}: expected exactly {expected!r}, found {matches!r}")

    return errors


def check_versions() -> None:
    version = root_version()
    errors: list[str] = []

    for path in FORMAL_PACKAGES:
        document = read_document(path)
        package_name = str(document["project"]["name"])
        package_version = str(document["project"]["version"])

        if package_version != version:
            errors.append(f"{package_name}: version={package_version}, expected={version}")

        errors.extend(
            check_dependency(
                document,
                version=version,
                path=path,
            )
        )

    for path in TEST_PACKAGES:
        document = read_document(path)
        errors.extend(
            check_dependency(
                document,
                version=version,
                path=path,
            )
        )

    if errors:
        message = "\n".join(f"- {error}" for error in errors)
        raise VersionSyncError(f"monorepo version synchronization failed:\n{message}")

    print(f"All OnlyAlpha packages are synchronized at {version}")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "check",
        help="check monorepo version consistency",
    )

    set_parser = subparsers.add_parser(
        "set",
        help="set the version of all formal distributions",
    )
    set_parser.add_argument("version")

    args = parser.parse_args()

    try:
        if args.command == "check":
            check_versions()
        elif args.command == "set":
            set_versions(args.version)
        else:
            parser.error(f"unsupported command: {args.command}")
    except VersionSyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
