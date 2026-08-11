from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement
from tomlkit import parse


def _load_version_sync() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/version_sync.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_version_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERSION_SYNC = _load_version_sync()
VersionSyncError = VERSION_SYNC.VersionSyncError
check_versions = VERSION_SYNC.check_versions
rewrite_internal_requirement = VERSION_SYNC.rewrite_internal_requirement
rewrite_workspace = VERSION_SYNC.rewrite_workspace

FIXTURE_PATH = Path("tests/fixtures/external_plugins/onlyalpha_test_plugin/pyproject.toml")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _workspace(
    tmp_path: Path,
    *,
    a_name: str = "onlyalpha-market-a",
    a_version: str = "0.3.7",
    b_version: str = "0.3.7",
    b_dependencies: tuple[str, ...] = ("onlyalpha==0.3.7", "onlyalpha-market-a==0.3.7", "pandas>=2"),
    b_optional_dependencies: tuple[str, ...] = (),
    fixture_version: str = "0.1.0",
    fixture_dependency: str = "onlyalpha==0.3.7",
) -> Path:
    dependency_lines = ",\n    ".join(repr(value) for value in b_dependencies)
    optional_section = ""
    if b_optional_dependencies:
        optional_lines = ",\n    ".join(repr(value) for value in b_optional_dependencies)
        optional_section = f"\n[project.optional-dependencies]\nfeature = [\n    {optional_lines},\n]\n"

    _write(
        tmp_path / "pyproject.toml",
        """[project]
name = "onlyalpha"
version = "0.3.7"
dependencies = []

[tool.uv.workspace]
members = ["packages/a", "packages/b"]
""",
    )
    _write(tmp_path / "README.md", "| Version | `0.3.7` |\n")
    _write(
        tmp_path / "packages/a/pyproject.toml",
        f"""[project]
name = {a_name!r}
version = {a_version!r}
dependencies = ["onlyalpha==0.3.7"]
""",
    )
    _write(
        tmp_path / "packages/b/pyproject.toml",
        f"""[project]
name = "onlyalpha-plugin-b"
version = {b_version!r}
dependencies = [
    {dependency_lines},
]
{optional_section}""",
    )
    _write(
        tmp_path / FIXTURE_PATH,
        f"""[project]
name = "onlyalpha-test-plugin"
version = {fixture_version!r}
dependencies = [{fixture_dependency!r}]
""",
    )
    return tmp_path


def _failure(tmp_path: Path) -> str:
    with pytest.raises(VersionSyncError) as exc_info:
        check_versions(tmp_path)
    return str(exc_info.value)


def test_valid_workspace_release_graph_passes(tmp_path: Path) -> None:
    check_versions(_workspace(tmp_path))


def test_stale_internal_edge_fails(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_dependencies=("onlyalpha==0.3.7", "onlyalpha-market-a==0.3.6"),
    )
    message = _failure(root)
    assert "onlyalpha-market-a" in message
    assert "expected '==0.3.7'" in message
    assert "==0.3.6" in message


def test_wrong_formal_distribution_version_fails(tmp_path: Path) -> None:
    message = _failure(_workspace(tmp_path, a_version="0.3.6"))
    assert "expected version '0.3.7'" in message
    assert "found '0.3.6'" in message


@pytest.mark.parametrize("dependency", ["onlyalpha-market-a>=0.3.7", "onlyalpha-market-a"])
def test_non_exact_internal_dependency_fails(tmp_path: Path, dependency: str) -> None:
    message = _failure(_workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", dependency)))
    assert "internal dependency 'onlyalpha-market-a'" in message
    assert "expected '==0.3.7'" in message


def test_external_dependency_is_unchanged_and_valid(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", "pandas>=2"))
    check_versions(root)
    rewrite_workspace(root, "0.3.8")
    document = parse((root / "packages/b/pyproject.toml").read_text(encoding="utf-8"))
    assert list(document["project"]["dependencies"]) == ["onlyalpha==0.3.8", "pandas>=2"]


def test_dependency_groups_are_outside_release_graph(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = root / "packages/b/pyproject.toml"
    path.write_text(
        path.read_text(encoding="utf-8") + '\n[dependency-groups]\ndev = ["onlyalpha-market-a==0.1.0"]\n',
        encoding="utf-8",
    )

    check_versions(root)
    rewrite_workspace(root, "0.3.8")

    document = parse(path.read_text(encoding="utf-8"))
    assert list(document["dependency-groups"]["dev"]) == ["onlyalpha-market-a==0.1.0"]


def test_stale_optional_internal_dependency_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_optional_dependencies=("onlyalpha-market-a==0.3.6",))
    message = _failure(root)
    assert "onlyalpha-market-a" in message
    assert "==0.3.6" in message


def test_duplicate_canonical_distribution_name_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, a_name="OnlyAlpha_Plugin_B")
    message = _failure(root)
    assert "duplicate canonical distribution name 'onlyalpha-plugin-b'" in message


def test_missing_workspace_member_pyproject_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "packages/a/pyproject.toml").unlink()
    message = _failure(root)
    assert "missing workspace member pyproject.toml" in message


def test_invalid_requirement_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", "not a valid ???"))
    message = _failure(root)
    assert "invalid requirement" in message


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("name", '""', "missing project.name"),
        ("version", '"not-a-version"', "invalid project.version"),
    ],
)
def test_invalid_distribution_identity_fails(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    root = _workspace(tmp_path)
    path = root / "packages/a/pyproject.toml"
    document = parse(path.read_text(encoding="utf-8"))
    document["project"][field] = parse(f"value = {value}\n")["value"]
    path.write_text(VERSION_SYNC.dumps(document), encoding="utf-8")
    assert expected in _failure(root)


def test_fixture_version_is_independent(tmp_path: Path) -> None:
    check_versions(_workspace(tmp_path, fixture_version="99.4"))


def test_stale_fixture_reference_to_formal_distribution_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, fixture_dependency="onlyalpha==0.3.6")
    message = _failure(root)
    assert str(FIXTURE_PATH) in message
    assert "==0.3.6" in message


def test_direct_url_internal_dependency_fails(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_dependencies=("onlyalpha==0.3.7", "onlyalpha-market-a @ file:///tmp/market-a"),
    )
    message = _failure(root)
    assert "direct URL" in message


def test_rewrite_internal_requirement_preserves_extras_and_marker() -> None:
    rewritten = rewrite_internal_requirement(
        'OnlyAlpha-Market-A[foo]>=0.3; python_version >= "3.12"',
        formal_distribution_names=frozenset({"onlyalpha-market-a"}),
        version="0.3.8",
    )
    requirement = Requirement(rewritten)
    assert requirement.name == "OnlyAlpha-Market-A"
    assert requirement.extras == {"foo"}
    assert str(requirement.specifier) == "==0.3.8"
    assert str(requirement.marker) == 'python_version >= "3.12"'


def test_set_rewrites_complete_graph_and_preserves_external_dependencies(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_optional_dependencies=('onlyalpha-market-a[feature]>=0.3; python_version >= "3.12"',),
        fixture_version="7.9",
    )

    rewrite_workspace(root, "0.3.8")
    check_versions(root)

    for relative_path in (Path("pyproject.toml"), Path("packages/a/pyproject.toml"), Path("packages/b/pyproject.toml")):
        document = parse((root / relative_path).read_text(encoding="utf-8"))
        assert document["project"]["version"] == "0.3.8"

    b_document = parse((root / "packages/b/pyproject.toml").read_text(encoding="utf-8"))
    assert "onlyalpha-market-a==0.3.8" in b_document["project"]["dependencies"]
    assert "pandas>=2" in b_document["project"]["dependencies"]
    optional = Requirement(str(b_document["project"]["optional-dependencies"]["feature"][0]))
    assert optional.extras == {"feature"}
    assert str(optional.specifier) == "==0.3.8"
    assert optional.marker is not None

    fixture = parse((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    assert fixture["project"]["version"] == "7.9"
    assert list(fixture["project"]["dependencies"]) == ["onlyalpha==0.3.8"]
    assert (root / "README.md").read_text(encoding="utf-8") == "| Version | `0.3.8` |\n"


def test_set_versions_locks_then_checks_complete_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr(VERSION_SYNC.subprocess, "run", fake_run)
    VERSION_SYNC.set_versions("0.3.8", root)

    assert calls == [(["uv", "lock", "--python", "3.12"], root, True)]
    check_versions(root)
