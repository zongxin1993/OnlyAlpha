from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "packages/onlyalpha-infra-ci-runner"


def test_ci_runner_image_is_pinned_and_contains_no_project_authority() -> None:
    dockerfile = (RUNNER / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12.12-slim-bookworm@sha256:" in dockerfile
    assert "UV_DEFAULT_INDEX=${PYPI_INDEX_URL}" in dockerfile
    assert "UV_PYTHON_DOWNLOADS=never" in dockerfile
    assert "COPY toolchain.txt" in dockerfile
    assert "COPY verify-toolchain.sh" in dockerfile
    assert "COPY ." not in dockerfile
    assert ":latest" not in dockerfile
    assert "GITEA_TOKEN" not in dockerfile
    assert "ONLYALPHA_REPOSITORY_READ_TOKEN" not in dockerfile


def test_ci_runner_toolchain_versions_are_exact() -> None:
    requirements = (RUNNER / "toolchain.txt").read_text(encoding="utf-8").splitlines()
    assert requirements == [
        "hatchling==1.32.0",
        "mypy==2.3.1",
        "psycopg[binary]==3.3.5",
        "pyarrow==25.0.0",
        "pytest==9.1.1",
        "pyyaml==6.0.3",
        "ruff==0.16.5",
    ]


def test_ci_runner_keeps_candidate_builds_in_admission() -> None:
    readme = (RUNNER / "README.md").read_text(encoding="utf-8")
    assert "no OnlyAlpha source" in readme
    assert "build candidate wheels on every pull request" in readme
    assert "immutable\ndigest" in readme
