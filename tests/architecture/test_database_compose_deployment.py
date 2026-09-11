from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/compose"


def _yaml(name: str) -> dict[str, object]:
    value = yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_compose_base_is_pinned_persistent_private_and_has_no_host_ports() -> None:
    compose = _yaml("compose.yaml")
    services = compose["services"]
    assert isinstance(services, dict)
    postgres = services["postgres"]
    clickhouse = services["clickhouse"]
    assert postgres["image"].startswith("postgres:18.6@sha256:")
    assert clickhouse["image"].startswith("clickhouse/clickhouse-server:26.3@sha256:")
    assert "ports" not in postgres and "ports" not in clickhouse
    assert postgres["environment"]["POSTGRES_PASSWORD"].startswith("${ONLYALPHA_POSTGRES_PASSWORD:?")
    assert clickhouse["environment"]["CLICKHOUSE_PASSWORD"].startswith("${ONLYALPHA_CLICKHOUSE_PASSWORD:?")
    assert compose["networks"]["database"]["internal"] is True
    assert set(compose["volumes"]) == {
        "postgres-data",
        "clickhouse-data",
        "clickhouse-hot",
        "clickhouse-cold",
    }


def test_compose_production_and_test_overrides_have_distinct_safety_contracts() -> None:
    production = _yaml("compose.production.yaml")
    test = _yaml("compose.test.yaml")
    for service in ("postgres", "clickhouse"):
        assert production["services"][service]["restart"] == "unless-stopped"
        assert production["services"][service]["logging"]["options"] == {
            "max-size": "10m",
            "max-file": "5",
        }
        assert "ports" not in test["services"][service]
    assert set(test["services"]) == {
        "operator",
        "binance-golden-provisioner",
        "postgres",
        "clickhouse",
        "acceptance",
        "acceptance-client",
    }
    assert test["networks"]["database"]["internal"] is True


def test_acceptance_runs_inside_compose_against_private_service_dns() -> None:
    test = _yaml("compose.test.yaml")
    acceptance = test["services"]["acceptance"]
    assert acceptance["build"] == {
        "context": "../..",
        "dockerfile": "deploy/compose/Dockerfile.acceptance",
        "target": "acceptance",
        "args": {"ONLYALPHA_BUILD_SOURCE_REVISION": "${ONLYALPHA_BUILD_SOURCE_REVISION:-}"},
    }
    assert acceptance["restart"] == "no"
    environment = acceptance["environment"]
    assert "@onlyalpha-postgres:5432/onlyalpha_test" in environment["ONLYALPHA_POSTGRES_DSN"]
    assert environment["ONLYALPHA_TEST_CLICKHOUSE_URL"] == "http://onlyalpha-clickhouse:8123"
    assert set(acceptance["depends_on"]) == {
        "postgres",
        "clickhouse",
    }

    dockerfile = (DEPLOY / "Dockerfile.acceptance").read_text(encoding="utf-8")
    assert "FROM ghcr.io/astral-sh/uv:0.10.5@sha256:" in dockerfile
    assert "FROM python:3.12.12-slim-bookworm@sha256:" in dockerfile
    assert "postgresql-client-18=18.6-1.pgdg12+2" in dockerfile
    assert "--no-dev --group compose-acceptance" in dockerfile
    assert "--no-editable" not in dockerfile
    assert "UV_NO_SYNC=1" in dockerfile
    assert "python scripts/embed_build_provenance.py" in dockerfile
    assert "python packages/onlyalpha-agent-orchestrator/provenance_build.py" in dockerfile
    assert "apt-get install git" not in dockerfile
    assert "COPY .git" not in dockerfile

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".git" in dockerignore.splitlines()
    assert "**/.env" in dockerignore
    assert "**/.env.*" in dockerignore


def test_compose_templates_keep_production_secrets_out_and_acceptance_is_canonical() -> None:
    production = (DEPLOY / ".env.production.example").read_text(encoding="utf-8")
    test = (DEPLOY / ".env.test.example").read_text(encoding="utf-8")
    runner = (DEPLOY / "run-acceptance.sh").read_text(encoding="utf-8")
    assert "change-me" in production
    assert "onlyalpha_test" not in production
    assert "ONLYALPHA_TEST_CLICKHOUSE_URL=" not in test
    assert "docker compose" in runner
    assert "run --rm acceptance" in runner
    assert "uv run" not in runner
    assert 'actual_revision="$(git -C "${repository_root}" rev-parse HEAD)"' in runner
    assert '"${ONLYALPHA_BUILD_SOURCE_REVISION}" != "${actual_revision}"' in runner
    assert 'ONLYALPHA_BUILD_SOURCE_REVISION="${actual_revision}"' in runner
    assert "conflicts with the repository Git HEAD" in runner

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'path = "hatch_build.py"' in pyproject

    container_runner = (DEPLOY / "container-acceptance.sh").read_text(encoding="utf-8")
    assert "scripts/test_suite.py research-postgres" in container_runner
    assert "scripts/test_suite.py market-data-clickhouse" in container_runner
    assert "scripts/test_suite.py p9-3-real-database" in container_runner


def test_ci_reuses_the_canonical_clickhouse_storage_policy() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "deploy/compose/run-acceptance.sh" in workflow
    assert "docker run --detach" not in workflow
    assert ".github/clickhouse/storage.xml" not in workflow


def test_production_entrypoint_can_only_use_the_base_and_production_override() -> None:
    deployment = (DEPLOY / "deploy-production.sh").read_text(encoding="utf-8")
    assert 'compose.yaml" -f "${deploy_dir}/compose.production.yaml' in deployment
    assert "compose.test.yaml" not in deployment
    assert "PASSWORD=(change-me)?" in deployment
    assert 'actual_revision="$(git -C "${repository_root}" rev-parse HEAD)"' in deployment
    assert '"${ONLYALPHA_BUILD_SOURCE_REVISION}" != "${actual_revision}"' in deployment
    assert 'ONLYALPHA_BUILD_SOURCE_REVISION="${actual_revision}"' in deployment
    assert "conflicts with the repository Git HEAD" in deployment
    assert "config --quiet" in deployment
    assert "pull" in deployment
    assert "up -d --wait" in deployment

    production = _yaml("compose.production.yaml")
    operator = production["services"]["operator"]
    assert operator["build"]["target"] == "operator"
    assert operator["profiles"] == ["tools"]
    assert "ports" not in operator
    assert operator["environment"]["ONLYALPHA_POSTGRES_DSN"].startswith("${ONLYALPHA_POSTGRES_DSN:?")
    assert "user-data:/var/lib/onlyalpha" in operator["volumes"]
    assert any(str(item).endswith(":/var/lib/onlyalpha-backups") for item in operator["volumes"])

    operator_runner = (DEPLOY / "run-operator.sh").read_text(encoding="utf-8")
    assert "run --rm operator" in operator_runner
    assert "compose.test.yaml" not in operator_runner
    assert "<url-encoded-password>" in operator_runner


@pytest.mark.parametrize("wrapper", ["run-acceptance.sh", "deploy-production.sh"])
@pytest.mark.parametrize(
    ("preset", "expected_code"),
    [(None, 0), ("1" * 40, 0), ("2" * 40, 2)],
)
def test_compose_wrappers_derive_and_guard_revision_transport(
    tmp_path: Path,
    wrapper: str,
    preset: str | None,
    expected_code: int,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text("#!/bin/sh\nprintf '%s\\n' '1111111111111111111111111111111111111111'\n", encoding="utf-8")
    git.chmod(0o700)
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!/bin/sh\nprintf '%s|%s\\n' \"$ONLYALPHA_BUILD_SOURCE_REVISION\" \"$*\" >> '{log}'\n",
        encoding="utf-8",
    )
    docker.chmod(0o700)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    if preset is None:
        environment.pop("ONLYALPHA_BUILD_SOURCE_REVISION", None)
    else:
        environment["ONLYALPHA_BUILD_SOURCE_REVISION"] = preset
    if wrapper == "deploy-production.sh":
        env_file = tmp_path / "production.env"
        env_file.write_text(
            "ONLYALPHA_POSTGRES_PASSWORD=secure\n"
            "ONLYALPHA_CLICKHOUSE_PASSWORD=secure\n"
            "ONLYALPHA_POSTGRES_DSN=postgresql://onlyalpha:secure@postgres:5432/onlyalpha\n",
            encoding="utf-8",
        )
        environment["ONLYALPHA_COMPOSE_ENV_FILE"] = str(env_file)
    completed = subprocess.run(
        [str(DEPLOY / wrapper)],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == expected_code, completed.stdout + completed.stderr
    invocations = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    if expected_code == 0:
        assert invocations and all(item.startswith("1" * 40 + "|") for item in invocations)
    else:
        assert "conflicts with the repository Git HEAD" in completed.stderr
        assert not any(" build " in f" {item} " for item in invocations)
