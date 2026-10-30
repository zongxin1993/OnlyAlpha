from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from tomlkit import dumps, parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_metadata import VersionSyncError as VersionSyncError
from scripts.release_metadata import load_release_units as load_release_units
from scripts.release_metadata import validate_release_version

ROOT = Path(__file__).resolve().parents[1]
TEST_DISTRIBUTION_PATHS = (
    Path("test-data/external_plugins/onlyalpha_test_plugin/pyproject.toml"),
    Path("test-data/runtime_factor_provider/pyproject.toml"),
)
WEB_PACKAGE_PATH = Path("packages/frontend/package.json")
WEB_LOCK_PATH = Path("packages/frontend/package-lock.json")
QUANT_ASSET_VERSION_PROJECTIONS = {
    Path("plugs/onlyalpha-plugin-operators/src/onlyalpha_plugin_operators/metadata.py"): re.compile(
        r'(?m)^(?P<prefix>DISTRIBUTION_VERSION\s*=\s*)"(?P<version>[^"]+)"(?P<suffix>[ \t]*)$'
    ),
    Path("plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators/provider.py"): re.compile(
        r'(?m)^(?P<prefix>\s*distribution_version\s*=\s*)"(?P<version>[^"]+)"(?P<suffix>,\s*)$'
    ),
}


def _operator_provider_uses_projection(path: Path, version: str) -> bool:
    try:
        tree = ast.parse(path.read_text())
        metadata = ast.parse(path.with_name("metadata.py").read_text())
    except (OSError, SyntaxError):
        return False
    bindings = [
        node
        for node in ast.walk(metadata)
        if isinstance(node, ast.Name) and node.id == "DISTRIBUTION_VERSION" and not isinstance(node.ctx, ast.Load)
    ]
    assignments = [
        node
        for node in metadata.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and node.targets[0] in bindings
        and isinstance(node.value, ast.Constant)
        and node.value.value == version
    ]
    if len(bindings) != 1 or len(assignments) != 1:
        return False
    imports = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "onlyalpha_plugin_operators.metadata" and node.level == 0
        for alias in node.names
        if alias.name == "DISTRIBUTION_VERSION" and alias.asname is None
    ]
    if len(imports) != 1:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id == "DISTRIBUTION_VERSION"
            and not isinstance(node.ctx, ast.Load)
            or isinstance(node, ast.arg)
            and node.arg == "DISTRIBUTION_VERSION"
            or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == "DISTRIBUTION_VERSION"
            or isinstance(node, ast.alias)
            and (node.asname or node.name) == "DISTRIBUTION_VERSION"
            and node is not imports[0]
        ):
            return False
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "quant_asset_provider"
    ]
    match functions:
        case [
            ast.FunctionDef(
                body=[
                    ast.Return(
                        value=ast.Call(
                            func=ast.Name(id="OnlyQuantAssetProvider"),
                            args=[ast.Call(func=ast.Name(id="OnlyQuantAssetProviderManifest"), keywords=keywords), *_],
                        )
                    )
                ]
            )
        ]:
            sources = [keyword.value for keyword in keywords if keyword.arg == "source"]
        case _:
            return False
    match sources:
        case [ast.Call(func=ast.Name(id="OnlyDistributionProviderSource")) as call]:
            pass
        case _:
            return False
    if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
        keyword.arg is None for keyword in call.keywords
    ):
        return False
    versions = [*call.args[1:], *(keyword.value for keyword in call.keywords if keyword.arg == "distribution_version")]
    return len(versions) == 1 and isinstance(versions[0], ast.Name) and versions[0].id == "DISTRIBUTION_VERSION"


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


BACKEND_MANIFEST = Path("packages/backend/Cargo.toml")
BACKEND_RUST_COMPONENTS = {"onlyalpha-backend"}


def _rust_members(root: Path) -> list[tuple[Path, Any, str]]:
    workspace = read_document(root / "Cargo.toml")["workspace"]
    result = []
    for member in workspace["members"]:
        path = root / str(member) / "Cargo.toml"
        document = read_document(path)
        name = document["package"]["name"]
        unit = (
            "plugin-" + name.removeprefix("onlyalpha-plugin-")
            if Path(member).parts[0] == "plugs"
            else "backend"
            if name in BACKEND_RUST_COMPONENTS
            else "libs"
        )
        result.append((path, document, unit))
    names = [document["package"]["name"] for _, document, _ in result]
    if len(names) != len(set(names)):
        raise VersionSyncError("duplicate Rust workspace package")
    return result


def _python_unit(distribution: WorkspaceDistribution, root: Path) -> str:
    if distribution.path.relative_to(root).parts[0] == "plugs":
        return "plugin-" + distribution.name.removeprefix("onlyalpha-plugin-")
    if distribution.path.relative_to(root).as_posix() == "packages/agent/pyproject.toml":
        return "agent"
    return "backend"


def workspace_graph_errors(
    root: Path,
    *,
    test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS,
) -> list[str]:
    units = load_release_units(root)
    distributions = load_workspace_distributions(root)
    formal_index = distribution_index(distributions)
    errors: list[str] = []
    for distribution in distributions:
        expected = units[_python_unit(distribution, root)]
        if str(distribution.version) != expected:
            errors.append(f"{distribution.path}: expected version {expected!r}; found {str(distribution.version)!r}")
    for distribution in (*distributions, *load_test_distributions(root, test_distribution_paths)):
        for requirement in (*distribution.dependencies, *distribution.optional_dependencies):
            dependency = formal_index.get(canonicalize_name(requirement.name))
            if dependency is not None:
                actual = _requirement_pin_error(requirement, version=dependency.version)
                if actual is not None:
                    errors.append(
                        f"{distribution.path}: internal dependency {requirement.name!r}; expected '=={dependency.version}'; found {actual!r}"
                    )
    frontend = units["frontend"]
    try:
        lock = json.loads((root / WEB_LOCK_PATH).read_text())
        if lock["version"] != frontend or lock["packages"][""]["version"] != frontend:
            errors.append("Web lock version differs from frontend")
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(f"invalid Web lock: {error}")
    for relative, pattern in QUANT_ASSET_VERSION_PROJECTIONS.items():
        path = root / relative
        plugin = formal_index.get(canonicalize_name(relative.parts[1]))
        if plugin is not None or path.exists():
            matches = tuple(pattern.finditer(path.read_text())) if path.is_file() else ()
            if (
                plugin is None
                or len(matches) != 1
                or matches[0]["version"] != str(plugin.version)
                or relative.name == "metadata.py"
                and not _operator_provider_uses_projection(path.with_name("provider.py"), str(plugin.version))
            ):
                errors.append(f"{relative}: quant asset distribution provenance mismatch")
    try:
        lock = tomllib.loads((root / "Cargo.lock").read_text())
        for path, document, unit in _rust_members(root):
            package = document["package"]
            value = package["version"]
            if unit != "libs" and not isinstance(value, str):
                errors.append(f"{path}: {unit} must have an independent version")
            actual = units["libs"] if isinstance(value, Mapping) and value.get("workspace") is True else value
            if actual != units[unit]:
                errors.append(f"{path}: expected {unit} version {units[unit]}")
            records = [p for p in lock["package"] if p["name"] == package["name"] and "source" not in p]
            if len(records) != 1 or records[0]["version"] != actual:
                errors.append(f"Rust lock mismatch: {package['name']}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(f"invalid Rust lock/metadata: {error}")
    return errors


def check_versions(root: Path = ROOT, *, test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS) -> None:
    errors = workspace_graph_errors(root, test_distribution_paths=test_distribution_paths)
    if errors:
        raise VersionSyncError("workspace release graph integrity failed:\n" + "\n".join(errors))
    print("Release units consistent: " + json.dumps(load_release_units(root), sort_keys=True))


def rewrite_internal_requirement(
    raw_requirement: str, *, formal_distribution_names: frozenset[str], version: str
) -> str:
    requirement = Requirement(raw_requirement)
    if canonicalize_name(requirement.name) not in formal_distribution_names:
        return raw_requirement
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    marker = f"; {requirement.marker}" if requirement.marker is not None else ""
    return f"{requirement.name}{extras}=={version}{marker}"


def rewrite_unit(
    root: Path, unit: str, version: str, *, test_distribution_paths: Sequence[Path] = TEST_DISTRIBUTION_PATHS
) -> None:
    units = load_release_units(root)
    if unit not in units:
        raise VersionSyncError(f"unknown release unit: {unit}")
    next_release_version(version)
    check_versions(root, test_distribution_paths=test_distribution_paths)
    documents: dict[Path, Any] = {}
    distributions = load_workspace_distributions(root)
    changed_names = frozenset(d.canonical_name for d in distributions if _python_unit(d, root) == unit)
    for distribution in (*distributions, *load_test_distributions(root, test_distribution_paths)):
        document = read_document(distribution.path)
        project = document["project"]
        if distribution.canonical_name in changed_names:
            project["version"] = version
        groups = [project.get("dependencies", [])] + list(project.get("optional-dependencies", {}).values())
        for dependencies in groups:
            for index, value in enumerate(dependencies):
                dependencies[index] = rewrite_internal_requirement(
                    str(value), formal_distribution_names=changed_names, version=version
                )
        if dumps(document) != distribution.path.read_text():
            documents[distribution.path] = document
    changed_rust = {}
    for path, document, owner in _rust_members(root):
        if owner == unit:
            package = document["package"]
            changed_rust[package["name"]] = units[unit]
            if unit != "libs":
                package["version"] = version
                documents[path] = document
            elif isinstance(package["version"], str):
                package["version"] = version
                documents[path] = document
    if unit == "libs":
        document = read_document(root / "Cargo.toml")
        document["workspace"]["package"]["version"] = version
        documents[root / "Cargo.toml"] = document
    if changed_rust:
        lock = read_document(root / "Cargo.lock")
        for package in lock["package"]:
            if package["name"] in changed_rust and "source" not in package:
                package["version"] = version
            for index, dependency in enumerate(package.get("dependencies", [])):
                for name, old in changed_rust.items():
                    if dependency == f"{name} {old}":
                        package["dependencies"][index] = f"{name} {version}"
        documents[root / "Cargo.lock"] = lock
    providers = []
    for relative, pattern in QUANT_ASSET_VERSION_PROJECTIONS.items():
        path = root / relative
        if path.exists() and canonicalize_name(relative.parts[1]) in changed_names:
            providers.append(
                (
                    path,
                    pattern.sub(lambda m: m["prefix"] + f'"{version}"' + m["suffix"], path.read_text()),
                )
            )
    web = []
    if unit == "frontend":
        for relative in (WEB_PACKAGE_PATH, WEB_LOCK_PATH):
            path = root / relative
            document = json.loads(path.read_text())
            document["version"] = version
            if relative == WEB_LOCK_PATH:
                document["packages"][""]["version"] = version
            web.append((path, document))
    for path, document in documents.items():
        write_document(path, document)
    for path, source in providers:
        path.write_text(source)
    for path, document in web:
        path.write_text(json.dumps(document, indent=4, ensure_ascii=False) + "\n")


def next_release_version(version: str, level: str = "patch") -> str:
    validate_release_version(version)
    major, minor, patch = map(int, version.split("."))
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "major":
        return f"{major + 1}.0.0"
    raise VersionSyncError(f"unknown release level: {level}")


def check_release_transition(base: str, candidate: str, level: str = "patch") -> str:
    expected = next_release_version(base, level)
    if candidate != expected:
        raise VersionSyncError(f"{level} release requires {base} -> {expected}; found {candidate!r}")
    return f"OnlyAlpha release: {base} -> {candidate} ({level})"


def release_selections_from_context(context: Mapping[str, Any]) -> dict[str, str]:
    events = context["events"]
    ids = [event["id"] for event in events]
    if any(type(value) is not int or value <= 0 for value in ids) or ids != sorted(set(ids)):
        raise VersionSyncError("release event history is incomplete or not strictly ordered")
    labels = context["pull_request"]["labels"]
    if context["pull_request"].get("merged") is True:
        merge_sha = context["pull_request"]["merge_commit_sha"]
        cuts = [i for i, event in enumerate(events) if event["event"] == "merged" and event["commit_id"] == merge_sha]
        if len(cuts) != 1:
            raise VersionSyncError("historical release selection unavailable: exact merge event missing or ambiguous")
        events = events[: cuts[0]]
        active: set[str] = set()
        for event in events:
            if event["event"] in {"labeled", "unlabeled"}:
                name = event["label"]["name"]
                if event["event"] == "labeled":
                    active.add(name)
                else:
                    active.discard(name)
        labels = [{"name": name} for name in active]
    selections = {}
    for label in labels:
        name = label["name"]
        if not isinstance(name, str):
            raise VersionSyncError("invalid release label")
        if not name.startswith("release:"):
            continue
        match = re.fullmatch(
            r"release:(libs|backend|frontend|agent|plugin-[a-z0-9]+(?:-[a-z0-9]+)*):(patch|minor|major)", name
        )
        if match is None or match[1] in selections:
            raise VersionSyncError("conflicting or unknown release labels")
        unit, level = match.groups()
        if level != "patch":
            owner = context["repository"]["owner"]
            if owner["type"] != "User":
                raise VersionSyncError("minor/major requires a governed human repository Owner")
            occurrences = [event for event in events if event.get("label", {}).get("name") == name]
            if (
                not occurrences
                or occurrences[-1]["event"] != "labeled"
                or occurrences[-1]["actor"]["login"] != owner["login"]
            ):
                raise VersionSyncError("minor/major requires an explicit Owner action on the selected release label")
        selections[unit] = level
    return selections


def read_git_release_transition(base_ref: str, root: Path = ROOT) -> tuple[dict[str, str], dict[str, str]]:
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"], cwd=root, text=True
    ).strip()
    return load_release_units(root, revision), load_release_units(root)


def validate_transitions(
    base: Mapping[str, str], candidate: Mapping[str, str], selections: Mapping[str, str]
) -> list[str]:
    from scripts.release_metadata import validate_inventory

    introduced = validate_inventory(dict(base), dict(candidate))
    changed = {unit for unit in base if base[unit] != candidate[unit]}
    if changed != selections.keys():
        raise VersionSyncError(
            f"selected units must equal changed units: changed={sorted(changed)}, selected={sorted(selections)}"
        )
    return (["agent: initial 0.1.0 inventory established; no release selected"] if introduced else []) + [
        f"{unit}: " + check_release_transition(base[unit], candidate[unit], selections[unit])
        for unit in sorted(changed)
    ]


def write_release_notice(notice: str, summary_file: Path | None) -> None:
    print(notice)
    if summary_file is not None:
        with summary_file.open("a") as stream:
            stream.write(notice + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    for name in ("set", "next"):
        child = subparsers.add_parser(name)
        child.add_argument("--unit", required=True)
        if name == "set":
            child.add_argument("version")
        else:
            child.add_argument("--level", choices=("patch", "minor", "major"), default="patch")
    for name in ("check-transition", "report-merge"):
        child = subparsers.add_parser(name)
        child.add_argument("--context-file", type=Path)
        child.add_argument("--summary-file", type=Path)
        if name == "check-transition":
            child.add_argument("--base-ref", required=True)
        else:
            child.add_argument("--notice-only", action="store_true")
    child = subparsers.add_parser("release-selection")
    child.add_argument("--context-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            check_versions()
        elif args.command == "set":
            rewrite_unit(ROOT, args.unit, args.version)
            subprocess.run(["uv", "lock", "--python", "3.12"], cwd=ROOT, check=True)
            check_versions()
        elif args.command == "next":
            print(next_release_version(load_release_units()[args.unit], args.level))
        else:
            if args.command == "release-selection":
                print(
                    json.dumps(
                        release_selections_from_context(json.loads(args.context_file.read_text())), sort_keys=True
                    )
                )
                return 0
            base, candidate = read_git_release_transition(
                args.base_ref if args.command == "check-transition" else "HEAD^"
            )
            actual = {unit: [base[unit], candidate[unit]] for unit in base if base[unit] != candidate[unit]}
            write_release_notice("Actual release transitions: " + json.dumps(actual, sort_keys=True), args.summary_file)
            if args.command == "report-merge" and args.notice_only:
                return 0
            context: Mapping[str, Any] = (
                json.loads(args.context_file.read_text())
                if args.context_file
                else {"pull_request": {"labels": []}, "events": []}
            )
            if args.command == "report-merge":
                sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
                if context["pull_request"].get("merged") is not True or sha != context["pull_request"].get(
                    "merge_commit_sha"
                ):
                    raise VersionSyncError("historical proof belongs to a different merge")
            check_versions()
            for notice in validate_transitions(base, candidate, release_selections_from_context(context)):
                write_release_notice(notice, args.summary_file)
    except (VersionSyncError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
