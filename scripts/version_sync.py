from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from tomlkit import dumps, parse

ROOT = Path(__file__).resolve().parents[1]
TEST_DISTRIBUTION_PATHS = (Path("tests/fixtures/external_plugins/onlyalpha_test_plugin/pyproject.toml"),)
WEB_PACKAGE_PATH = Path("packages/onlyalpha-web-console/package.json")
WEB_LOCK_PATH = Path("packages/onlyalpha-web-console/package-lock.json")


class VersionSyncError(RuntimeError):
    """Raised when the workspace release graph is invalid or inconsistent."""


@dataclass(frozen=True, slots=True)
class WorkspaceDistribution:
    path: Path
    name: str
    canonical_name: str
    version: Version
    dependencies: tuple[Requirement, ...]
    optional_dependencies: tuple[Requirement, ...]


def read_document(path: Path) -> Any:
    if not path.is_file():
        raise VersionSyncError(f"missing file: {path}")
    try:
        return parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VersionSyncError(f"invalid TOML in {path}: {exc}") from exc


def write_document(path: Path, document: Any) -> None:
    path.write_text(dumps(document), encoding="utf-8")


def _project_table(document: Any, *, path: Path) -> Any:
    project = document.get("project")
    if project is None:
        raise VersionSyncError(f"{path}: missing [project]")
    return project


def _required_project_text(project: Any, field: str, *, path: Path) -> str:
    value = project.get(field)
    if not isinstance(value, str) or not value.strip():
        raise VersionSyncError(f"{path}: missing project.{field}")
    return value


def _requirement_values(value: Any, *, location: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise VersionSyncError(f"{location}: expected an array of requirements")
    values = tuple(str(item) for item in value)
    if any(not item.strip() for item in values):
        raise VersionSyncError(f"{location}: empty requirement")
    return values


def _parse_requirements(values: Sequence[str], *, location: str) -> tuple[Requirement, ...]:
    requirements: list[Requirement] = []
    for raw_requirement in values:
        try:
            requirements.append(Requirement(raw_requirement))
        except InvalidRequirement as exc:
            raise VersionSyncError(f"{location}: invalid requirement {raw_requirement!r}: {exc}") from exc
    return tuple(requirements)


def _distribution_from_document(path: Path, document: Any) -> WorkspaceDistribution:
    project = _project_table(document, path=path)
    name = _required_project_text(project, "name", path=path)
    raw_version = _required_project_text(project, "version", path=path)
    try:
        version = Version(raw_version)
    except InvalidVersion as exc:
        raise VersionSyncError(f"{path}: invalid project.version {raw_version!r}") from exc

    dependency_values = _requirement_values(
        project.get("dependencies"),
        location=f"{path}: project.dependencies",
    )
    dependencies = _parse_requirements(
        dependency_values,
        location=f"{path}: project.dependencies",
    )

    optional_dependencies: list[Requirement] = []
    optional_table = project.get("optional-dependencies", {})
    if not isinstance(optional_table, Mapping):
        raise VersionSyncError(f"{path}: project.optional-dependencies must be a table")
    for group, raw_values in optional_table.items():
        location = f"{path}: project.optional-dependencies.{group}"
        values = _requirement_values(raw_values, location=location)
        optional_dependencies.extend(_parse_requirements(values, location=location))

    return WorkspaceDistribution(
        path=path,
        name=name,
        canonical_name=canonicalize_name(name),
        version=version,
        dependencies=dependencies,
        optional_dependencies=tuple(optional_dependencies),
    )


def _workspace_member_paths(root: Path, root_document: Any) -> tuple[Path, ...]:
    tool = root_document.get("tool")
    uv = None if tool is None else tool.get("uv")
    workspace = None if uv is None else uv.get("workspace")
    raw_members = None if workspace is None else workspace.get("members")
    if isinstance(raw_members, (str, bytes)) or not isinstance(raw_members, Sequence):
        raise VersionSyncError(f"{root / 'pyproject.toml'}: missing tool.uv.workspace.members")

    member_paths: list[Path] = []
    for raw_member in raw_members:
        member = str(raw_member).strip()
        if not member:
            raise VersionSyncError(f"{root / 'pyproject.toml'}: empty workspace member")
        member_pyproject = root / member / "pyproject.toml"
        if not member_pyproject.is_file():
            raise VersionSyncError(f"missing workspace member pyproject.toml: {member_pyproject}")
        member_paths.append(member_pyproject)
    return tuple(member_paths)


def load_workspace_distributions(root: Path) -> tuple[WorkspaceDistribution, ...]:
    root_pyproject = root / "pyproject.toml"
    root_document = read_document(root_pyproject)
    paths = (root_pyproject, *_workspace_member_paths(root, root_document))
    distributions = tuple(
        _distribution_from_document(path, root_document if path == root_pyproject else read_document(path))
        for path in paths
    )
    distribution_index(distributions)
    return distributions


def distribution_index(
    distributions: Sequence[WorkspaceDistribution],
) -> Mapping[str, WorkspaceDistribution]:
    index: dict[str, WorkspaceDistribution] = {}
    for distribution in distributions:
        previous = index.get(distribution.canonical_name)
        if previous is not None:
            raise VersionSyncError(
                "duplicate canonical distribution name "
                f"{distribution.canonical_name!r}: {previous.path} and {distribution.path}"
            )
        index[distribution.canonical_name] = distribution
    return index


def load_test_distributions(
    root: Path,
    paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS,
) -> tuple[WorkspaceDistribution, ...]:
    return tuple(_distribution_from_document(root / path, read_document(root / path)) for path in paths)


def _requirement_pin_error(requirement: Requirement, *, version: Version) -> str | None:
    if requirement.url is not None:
        return f"direct URL {requirement.url!r}"
    specifiers = tuple(requirement.specifier)
    expected_version = str(version)
    if len(specifiers) != 1 or specifiers[0].operator != "==" or specifiers[0].version != expected_version:
        actual = str(requirement.specifier) or "<missing>"
        return actual
    return None


def _internal_edge_errors(
    distribution: WorkspaceDistribution,
    *,
    formal_index: Mapping[str, WorkspaceDistribution],
    version: Version,
) -> list[str]:
    errors: list[str] = []
    for requirement in (*distribution.dependencies, *distribution.optional_dependencies):
        dependency_name = canonicalize_name(requirement.name)
        if dependency_name not in formal_index:
            continue
        actual = _requirement_pin_error(requirement, version=version)
        if actual is not None:
            errors.append(
                f"{distribution.path}: internal dependency {requirement.name!r}; "
                f"expected '=={version}'; found {actual!r}"
            )
    return errors


def workspace_graph_errors(
    root: Path,
    *,
    test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS,
) -> list[str]:
    distributions = load_workspace_distributions(root)
    formal_index = distribution_index(distributions)
    release_version = distributions[0].version
    errors: list[str] = []

    for distribution in distributions:
        if distribution.version != release_version:
            errors.append(
                f"{distribution.path}: distribution {distribution.name!r}; "
                f"expected version {str(release_version)!r}; found {str(distribution.version)!r}"
            )
        errors.extend(
            _internal_edge_errors(
                distribution,
                formal_index=formal_index,
                version=release_version,
            )
        )

    for distribution in load_test_distributions(root, test_distribution_paths):
        errors.extend(
            _internal_edge_errors(
                distribution,
                formal_index=formal_index,
                version=release_version,
            )
        )
    for relative_path in (WEB_PACKAGE_PATH, WEB_LOCK_PATH):
        path = root / relative_path
        if not path.is_file():
            errors.append(f"{path}: missing Web version authority")
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        version = document.get("version")
        if version != str(release_version):
            errors.append(f"{path}: expected version {str(release_version)!r}; found {version!r}")
        if relative_path == WEB_LOCK_PATH:
            root_package = document.get("packages", {}).get("", {})
            if root_package.get("version") != str(release_version):
                errors.append(
                    f"{path}: root package expected version {str(release_version)!r}; "
                    f"found {root_package.get('version')!r}"
                )
    return errors


def check_versions(
    root: Path = ROOT,
    *,
    test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS,
) -> None:
    errors = workspace_graph_errors(root, test_distribution_paths=test_distribution_paths)
    if errors:
        message = "\n".join(f"- {error}" for error in errors)
        raise VersionSyncError(f"workspace release graph integrity failed:\n{message}")

    release_version = load_workspace_distributions(root)[0].version
    print(f"Workspace release graph is consistent at {release_version}")


def rewrite_internal_requirement(
    raw_requirement: str,
    *,
    formal_distribution_names: frozenset[str],
    version: str,
) -> str:
    try:
        requirement = Requirement(raw_requirement)
    except InvalidRequirement as exc:
        raise VersionSyncError(f"invalid requirement {raw_requirement!r}: {exc}") from exc
    if canonicalize_name(requirement.name) not in formal_distribution_names:
        return raw_requirement

    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    marker = f"; {requirement.marker}" if requirement.marker is not None else ""
    return f"{requirement.name}{extras}=={version}{marker}"


def _rewrite_project_requirements(
    project: Any,
    *,
    formal_distribution_names: frozenset[str],
    version: str,
) -> None:
    dependencies = project.get("dependencies")
    if dependencies is not None:
        for index, raw_requirement in enumerate(dependencies):
            dependencies[index] = rewrite_internal_requirement(
                str(raw_requirement),
                formal_distribution_names=formal_distribution_names,
                version=version,
            )

    optional_table = project.get("optional-dependencies", {})
    for dependencies in optional_table.values():
        for index, raw_requirement in enumerate(dependencies):
            dependencies[index] = rewrite_internal_requirement(
                str(raw_requirement),
                formal_distribution_names=formal_distribution_names,
                version=version,
            )


def _normalized_version(version: str) -> str:
    try:
        normalized = str(Version(version))
    except InvalidVersion as exc:
        raise VersionSyncError(f"invalid version: {version}") from exc
    if normalized != version:
        raise VersionSyncError(f"version must already be normalized: {version!r} -> {normalized!r}")
    return normalized


def rewrite_workspace(
    root: Path,
    version: str,
    *,
    test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS,
) -> None:
    normalized = _normalized_version(version)
    distributions = load_workspace_distributions(root)
    load_test_distributions(root, test_distribution_paths)
    formal_names = frozenset(distribution.canonical_name for distribution in distributions)

    documents: list[tuple[Path, Any]] = []
    for distribution in distributions:
        document = read_document(distribution.path)
        project = _project_table(document, path=distribution.path)
        project["version"] = normalized
        _rewrite_project_requirements(
            project,
            formal_distribution_names=formal_names,
            version=normalized,
        )
        documents.append((distribution.path, document))

    for relative_path in test_distribution_paths:
        path = root / relative_path
        document = read_document(path)
        project = _project_table(document, path=path)
        _rewrite_project_requirements(
            project,
            formal_distribution_names=formal_names,
            version=normalized,
        )
        documents.append((path, document))

    web_documents: list[tuple[Path, dict[str, Any]]] = []
    for relative_path in (WEB_PACKAGE_PATH, WEB_LOCK_PATH):
        path = root / relative_path
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise VersionSyncError(f"invalid Web version document {path}: {exc}") from exc
        document["version"] = normalized
        if relative_path == WEB_LOCK_PATH:
            document["packages"][""]["version"] = normalized
        web_documents.append((path, document))

    for path, document in documents:
        write_document(path, document)
    for path, document in web_documents:
        path.write_text(json.dumps(document, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def set_versions(version: str, root: Path = ROOT) -> None:
    rewrite_workspace(root, version)
    try:
        subprocess.run(
            ["uv", "lock", "--python", "3.12"],
            cwd=root,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise VersionSyncError(f"uv lock failed with exit code {exc.returncode}") from exc
    check_versions(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="check workspace release graph integrity")
    set_parser = subparsers.add_parser("set", help="set the version of the complete release graph")
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
