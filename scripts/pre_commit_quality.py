from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

PYTHON_SUFFIXES = {".py", ".pyi"}

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "dist-ci",
}

FULL_RUFF_TARGETS = (
    "src",
    "tests",
    "examples",
    "packages",
    "tools",
)

GLOBAL_CONFIGURATION_FILES = {
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".pre-commit-config.yaml",
}


@dataclass(frozen=True)
class MypyScope:
    name: str
    config_file: str
    source_path: str
    trigger_paths: tuple[str, ...]


MYPY_SCOPES = (
    MypyScope(
        name="Core",
        config_file="pyproject.toml",
        source_path="src/onlyalpha",
        trigger_paths=(
            "src/onlyalpha",
            "tests",
            "examples",
            "tools",
        ),
    ),
    MypyScope(
        name="Tushare",
        config_file=("packages/provider/onlyalpha-plugin-tushare/pyproject.toml"),
        source_path=("packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare"),
        trigger_paths=("packages/provider/onlyalpha-plugin-tushare",),
    ),
    # MypyScope(
    #     name="MiniQMT",
    #     config_file=("packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml"),
    #     source_path=("packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt"),
    #     trigger_paths=("packages/provider/onlyalpha-plugin-miniqmt",),
    # ),
)


def normalize_path(value: str) -> str:
    """Convert an incoming filename to a repository-relative POSIX path."""
    path = Path(value)

    if path.is_absolute():
        try:
            path = path.resolve().relative_to(ROOT)
        except ValueError:
            return path.resolve().as_posix()

    return PurePosixPath(path).as_posix().removeprefix("./")


def is_under_path(path: str, prefix: str) -> bool:
    normalized_prefix = prefix.rstrip("/")
    return path == normalized_prefix or path.startswith(f"{normalized_prefix}/")


def is_excluded(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(part in EXCLUDED_DIRECTORY_NAMES for part in parts)


def is_existing_python_file(path: str) -> bool:
    if is_excluded(path):
        return False

    candidate = ROOT / Path(path)

    return candidate.is_file() and candidate.suffix.lower() in PYTHON_SUFFIXES


def available_full_ruff_targets() -> list[str]:
    return [target for target in FULL_RUFF_TARGETS if (ROOT / target).exists()]


def executable(name: str) -> str:
    resolved = shutil.which(name)

    if resolved is None:
        raise RuntimeError(
            f"Required executable {name!r} was not found. Run `uv sync --all-packages --all-groups` first."
        )

    return resolved


def print_command(command: Sequence[str]) -> None:
    rendered = subprocess.list2cmdline(list(command))
    print(f"\n> {rendered}", flush=True)


def run_command(command: Sequence[str]) -> int:
    print_command(command)

    completed = subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
    )

    return completed.returncode


def resolve_mypy_scopes(
    changed_paths: Sequence[str],
    *,
    check_all: bool,
) -> list[MypyScope]:
    if check_all:
        return list(MYPY_SCOPES)

    global_configuration_changed = any(
        path in GLOBAL_CONFIGURATION_FILES or path.endswith("/pyproject.toml") for path in changed_paths
    )

    if global_configuration_changed:
        return list(MYPY_SCOPES)

    selected: list[MypyScope] = []

    for scope in MYPY_SCOPES:
        if any(is_under_path(path, trigger) for path in changed_paths for trigger in scope.trigger_paths):
            selected.append(scope)

    return selected


def run_ruff(targets: Sequence[str]) -> int:
    if not targets:
        print("\nRuff: no Python files require checking.")
        return 0

    ruff = executable("ruff")

    # 第一步：自动修复可修复的 lint 问题，例如导入顺序。
    #
    # 该步骤即使仍有不可自动修复的问题，也继续执行格式化；
    # 最后的 ruff check 会给出最终结果。
    run_command(
        [
            ruff,
            "check",
            "--fix",
            "--force-exclude",
            "--",
            *targets,
        ]
    )

    # 第二步：格式化代码。
    format_result = run_command(
        [
            ruff,
            "format",
            "--force-exclude",
            "--",
            *targets,
        ]
    )

    # 第三步：确认没有残留 lint 问题。
    check_result = run_command(
        [
            ruff,
            "check",
            "--force-exclude",
            "--",
            *targets,
        ]
    )

    if format_result != 0:
        return format_result

    return check_result


def run_mypy(scopes: Sequence[MypyScope]) -> int:
    if not scopes:
        print("\nMypy: no affected package requires checking.")
        return 0

    mypy = executable("mypy")
    failed_scopes: list[str] = []

    for scope in scopes:
        config_path = ROOT / scope.config_file
        source_path = ROOT / scope.source_path

        if not config_path.is_file():
            print(
                f"\nMypy {scope.name}: missing config file: {scope.config_file}",
                file=sys.stderr,
            )
            failed_scopes.append(scope.name)
            continue

        if not source_path.exists():
            print(
                f"\nMypy {scope.name}: missing source path: {scope.source_path}",
                file=sys.stderr,
            )
            failed_scopes.append(scope.name)
            continue

        cache_directory = ROOT / ".mypy_cache" / "pre-commit" / scope.name.lower()

        result = run_command(
            [
                mypy,
                "--config-file",
                scope.config_file,
                "--cache-dir",
                str(cache_directory),
                scope.source_path,
            ]
        )

        if result != 0:
            failed_scopes.append(scope.name)

    if failed_scopes:
        print(
            "\nMypy failed scopes: " + ", ".join(failed_scopes),
            file=sys.stderr,
        )
        return 1

    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run OnlyAlpha pre-commit Ruff formatting and package-aware Mypy checks.")
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="check the complete monorepo",
    )

    parser.add_argument(
        "filenames",
        nargs="*",
        help="filenames supplied by pre-commit",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    changed_paths = sorted({normalize_path(filename) for filename in arguments.filenames})

    if arguments.all:
        ruff_targets = available_full_ruff_targets()
    else:
        ruff_targets = [path for path in changed_paths if is_existing_python_file(path)]

    mypy_scopes = resolve_mypy_scopes(
        changed_paths,
        check_all=arguments.all,
    )

    print("OnlyAlpha local quality gate")
    print("============================")
    print(f"Mode: {'complete repository' if arguments.all else 'changed files'}")

    if changed_paths:
        print("Changed paths:")
        for path in changed_paths:
            print(f"  - {path}")

    print("Mypy scopes:")
    if mypy_scopes:
        for scope in mypy_scopes:
            print(f"  - {scope.name}")
    else:
        print("  - none")

    try:
        ruff_result = run_ruff(ruff_targets)
        mypy_result = run_mypy(mypy_scopes)
    except RuntimeError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    if ruff_result != 0 or mypy_result != 0:
        print("\nOnlyAlpha local quality gate failed.", file=sys.stderr)
        return 1

    print("\nOnlyAlpha local quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
