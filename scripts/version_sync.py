from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parents[1]
RUST_MODULES = frozenset(
    {
        "onlyalpha-domain",
        "onlyalpha-calculation",
        "onlyalpha-gateway-protocol",
        "onlyalpha-calculation-worker",
        "onlyalpha-runtime-persistence",
        "onlyalpha-backtest-driver",
        "onlyalpha-kernel",
        "onlyalpha-clock",
        "onlyalpha-event",
        "onlyalpha-market-data-state",
        "onlyalpha-market-data-construction",
        "onlyalpha-market-data-delivery",
        "onlyalpha-market-data-pipeline",
        "onlyalpha-strategy",
        "onlyalpha-order",
        "onlyalpha-position",
        "onlyalpha-account",
        "onlyalpha-strategy-ledger",
        "onlyalpha-risk",
        "onlyalpha-execution",
        "onlyalpha-broker",
        "onlyalpha-fee",
        "onlyalpha-settlement",
        "onlyalpha-margin",
    }
)
TEST_DISTRIBUTION_PATHS = (
    Path("test-data/external_plugins/onlyalpha_test_plugin/pyproject.toml"),
    Path("test-data/runtime_factor_provider/pyproject.toml"),
)
WEB_PACKAGE_PATH = Path("packages/onlyalpha-web-console/package.json")
WEB_LOCK_PATH = Path("packages/onlyalpha-web-console/package-lock.json")
QUANT_ASSET_PROVIDER_PATHS = (
    Path("plugs/onlyalpha-plugin-operators/src/onlyalpha_plugin_operators/provider.py"),
    Path("plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators/provider.py"),
)
_DISTRIBUTION_VERSION = re.compile(
    r'(?m)^(?P<prefix>\s*distribution_version\s*=\s*)"(?P<version>[^"]+)"(?P<suffix>,\s*)$'
)


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
    for relative_path in QUANT_ASSET_PROVIDER_PATHS:
        path = root / relative_path
        if not path.is_file():
            continue
        matches = tuple(_DISTRIBUTION_VERSION.finditer(path.read_text(encoding="utf-8")))
        if len(matches) != 1:
            errors.append(f"{path}: expected exactly one quant asset distribution_version")
        elif matches[0].group("version") != str(release_version):
            errors.append(
                f"{path}: quant asset distribution_version expected {str(release_version)!r}; "
                f"found {matches[0].group('version')!r}"
            )
    if (root / "Cargo.toml").is_file() or (root / "Cargo.lock").is_file():
        try:
            cargo = tomllib.loads((root / "Cargo.toml").read_text())
            lock = tomllib.loads((root / "Cargo.lock").read_text())
            packages = [item for item in lock["package"] if item["name"] in RUST_MODULES]
            if (
                cargo["workspace"]["package"]["version"] != str(release_version)
                or len(packages) != len(RUST_MODULES)
                or {item["name"] for item in packages} != RUST_MODULES
                or any(item["version"] != str(release_version) for item in packages)
            ):
                errors.append("Rust workspace/lock release version differs from pyproject.toml")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Rust workspace/lock metadata is invalid: {exc}")
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

    provider_documents: list[tuple[Path, str]] = []
    for relative_path in QUANT_ASSET_PROVIDER_PATHS:
        path = root / relative_path
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if len(tuple(_DISTRIBUTION_VERSION.finditer(source))) != 1:
            raise VersionSyncError(f"{path}: expected exactly one quant asset distribution_version")
        provider_documents.append(
            (
                path,
                _DISTRIBUTION_VERSION.sub(
                    lambda match: f'{match.group("prefix")}"{normalized}"{match.group("suffix")}',
                    source,
                ),
            )
        )

    if (root / "Cargo.toml").is_file() or (root / "Cargo.lock").is_file():
        cargo = read_document(root / "Cargo.toml")
        lock = read_document(root / "Cargo.lock")
        cargo["workspace"]["package"]["version"] = normalized
        packages = [item for item in lock["package"] if item["name"] in RUST_MODULES]
        if len(packages) != len(RUST_MODULES) or {item["name"] for item in packages} != RUST_MODULES:
            raise VersionSyncError("Rust lock must contain each canonical module exactly once")
        for package in packages:
            package["version"] = normalized
        documents += [(root / "Cargo.toml", cargo), (root / "Cargo.lock", lock)]
    for path, document in documents:
        write_document(path, document)
    for path, document in web_documents:
        path.write_text(json.dumps(document, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, source in provider_documents:
        path.write_text(source, encoding="utf-8")


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


def next_release_version(version: str, level: str = "patch") -> str:
    """Release counters are not API, Provider or semantic compatibility versions."""
    if (
        not isinstance(version, str)
        or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version) is None
    ):
        raise VersionSyncError(f"release version must be canonical X.Y.Z: {version!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "major":
        return f"{major + 1}.0.0"
    raise VersionSyncError(f"unknown release level: {level!r}")


def check_release_transition(base: str, candidate: str, level: str = "patch") -> str:
    expected = next_release_version(base, level)
    if candidate != expected:
        raise VersionSyncError(
            f"{level} release requires {base} -> {expected}; found {candidate!r}; "
            "refresh against the current main branch and synchronize the complete release graph"
        )
    return f"OnlyAlpha release: {base} -> {candidate} ({level})"


def release_level_from_context(context: Mapping[str, Any]) -> str:
    """Interpret read-only GitHub observations, not PR text as Owner authority."""
    events = context["events"]
    ids = [event["id"] for event in events]
    if any(type(value) is not int or value <= 0 for value in ids) or ids != sorted(set(ids)):
        raise VersionSyncError("release event history is incomplete or not strictly ordered")
    labels = context["pull_request"]["labels"]
    if context["pull_request"].get("merged") is True:
        merge_sha = context["pull_request"]["merge_commit_sha"]
        cuts = [
            index
            for index, event in enumerate(events)
            if event["event"] == "merged" and event["commit_id"] == merge_sha
        ]
        if len(cuts) != 1:
            raise VersionSyncError(
                "historical release selection unavailable: exact merge event is missing or ambiguous"
            )
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
    selected: set[str] = set()
    for label in labels:
        name = label["name"]
        if not isinstance(name, str):
            raise VersionSyncError("invalid release label")
        if name.startswith("release:"):
            selected.add(name)
    if not selected:
        return "patch"
    if len(selected) != 1 or not selected <= {"release:patch", "release:minor", "release:major"}:
        raise VersionSyncError("conflicting or unknown release labels")
    level = next(iter(selected)).split(":", 1)[1]
    if level == "patch":
        return level
    owner = context["repository"]["owner"]
    if owner["type"] != "User":
        raise VersionSyncError("minor/major requires an explicitly governed human repository Owner")
    label_events = [event for event in events if event.get("label", {}).get("name") in selected]
    owner_label = bool(label_events) and (
        label_events[-1]["event"] == "labeled" and label_events[-1]["actor"]["login"] == owner["login"]
    )
    if not owner_label:
        raise VersionSyncError("minor/major requires an explicit Owner action on the selected release label")
    return level


def read_git_release_transition(base_ref: str, root: Path = ROOT) -> tuple[str, str]:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
            cwd=root,
            text=True,
        ).strip()
        raw = subprocess.check_output(["git", "show", f"{revision}:pyproject.toml"], cwd=root, text=True)
        base = tomllib.loads(raw)["project"]["version"]
    except (subprocess.CalledProcessError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise VersionSyncError("cannot establish the main-branch release version") from exc
    path = root / "pyproject.toml"
    candidate = _required_project_text(_project_table(read_document(path), path=path), "version", path=path)
    next_release_version(base)
    next_release_version(candidate)
    return base, candidate


def check_transition_from_git(base_ref: str, level: str, root: Path = ROOT) -> str:
    base, candidate = read_git_release_transition(base_ref, root)
    check_versions(root)
    return check_release_transition(base, candidate, level)


def write_release_notice(notice: str, summary_file: Path | None) -> None:
    print(notice)
    if summary_file is not None:
        with summary_file.open("a", encoding="utf-8") as stream:
            stream.write(f"## {notice}\n\nRelease numbering only; not product acceptance or deployment permission.\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="check workspace release graph integrity")
    set_parser = subparsers.add_parser("set", help="set the version of the complete release graph")
    set_parser.add_argument("version")
    next_parser = subparsers.add_parser("next", help="suggest a version without modifying files")
    next_parser.add_argument("--level", choices=("patch", "minor", "major"), default="patch")
    transition_parser = subparsers.add_parser("check-transition", help="check one PR's main-branch release increment")
    transition_parser.add_argument("--base-ref", required=True)
    transition_parser.add_argument("--level", choices=("patch", "minor", "major"), default="patch")
    transition_parser.add_argument("--summary-file", type=Path)
    level_parser = subparsers.add_parser("release-level", help="resolve level from read-only GitHub PR observations")
    level_parser.add_argument("--context-file", type=Path, required=True)
    report_parser = subparsers.add_parser(
        "report-merge", help="always report actual Git numbers before historical validation"
    )
    report_parser.add_argument("--context-file", type=Path)
    report_parser.add_argument("--summary-file", type=Path)
    report_parser.add_argument("--notice-only", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "check":
            check_versions()
        elif args.command == "set":
            set_versions(args.version)
        elif args.command == "next":
            current = str(load_workspace_distributions(ROOT)[0].version)
            print(next_release_version(current, args.level))
        elif args.command == "check-transition":
            notice = check_transition_from_git(args.base_ref, args.level)
            write_release_notice(notice, args.summary_file)
        elif args.command in {"release-level", "report-merge"}:
            if args.command == "report-merge":
                base, candidate = read_git_release_transition("HEAD^", ROOT)
                write_release_notice(f"OnlyAlpha merged release: {base} -> {candidate}", args.summary_file)
                if args.notice_only:
                    return 0
                if args.context_file is None:
                    raise VersionSyncError("historical merge validation requires GitHub context")
            try:
                context = json.loads(args.context_file.read_text(encoding="utf-8"))
                level = release_level_from_context(context)
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                raise VersionSyncError("incomplete or invalid GitHub release-selection proof") from exc
            if args.command == "release-level":
                print(level)
            else:
                if context["pull_request"].get("merged") is not True:
                    raise VersionSyncError("historical reporting requires a merged PR")
                actual_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
                if actual_sha != context["pull_request"]["merge_commit_sha"]:
                    raise VersionSyncError("historical release proof belongs to a different merge")
                check_versions(ROOT)
                print(check_release_transition(base, candidate, level))
        else:
            parser.error(f"unsupported command: {args.command}")
    except VersionSyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
