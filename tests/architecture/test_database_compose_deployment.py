from __future__ import annotations

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
    assert test["services"]["postgres16-upgrade-source"]["image"].startswith("postgres:16.10@sha256:")
    assert "ports" not in test["services"]["postgres16-upgrade-source"]
    assert test["networks"]["database"]["internal"] is True


def test_acceptance_runs_inside_compose_against_private_service_dns() -> None:
    test = _yaml("compose.test.yaml")
    acceptance = test["services"]["acceptance"]
    assert acceptance["build"] == {
        "context": "../..",
        "dockerfile": "deploy/compose/Dockerfile.acceptance",
        "target": "acceptance",
    }
    assert acceptance["restart"] == "no"
    environment = acceptance["environment"]
    assert "@onlyalpha-postgres:5432/onlyalpha_test" in environment["ONLYALPHA_TEST_POSTGRES_DSN"]
    assert environment["ONLYALPHA_TEST_CLICKHOUSE_URL"] == "http://onlyalpha-clickhouse:8123"
    assert set(acceptance["depends_on"]) == {
        "postgres",
        "postgres16-upgrade-source",
        "clickhouse",
    }

    dockerfile = (DEPLOY / "Dockerfile.acceptance").read_text(encoding="utf-8")
    assert "FROM ghcr.io/astral-sh/uv:0.10.5@sha256:" in dockerfile
    assert "FROM python:3.12.12-slim-bookworm@sha256:" in dockerfile
    assert "postgresql-client-18=18.6-1.pgdg12+2" in dockerfile
    assert "--no-dev --group compose-acceptance" in dockerfile
    assert "--no-editable" not in dockerfile
    assert "UV_NO_SYNC=1" in dockerfile

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "**/.env" in dockerignore
    assert "**/.env.*" in dockerignore


def test_compose_templates_keep_production_secrets_out_and_acceptance_is_canonical() -> None:
    production = (DEPLOY / ".env.production.example").read_text(encoding="utf-8")
    test = (DEPLOY / ".env.test.example").read_text(encoding="utf-8")
    runner = (DEPLOY / "run-acceptance.sh").read_text(encoding="utf-8")
    assert "change-me" in production
    assert "onlyalpha_test" not in production
    assert "ONLYALPHA_TEST_POSTGRES_DSN=" not in test
    assert "ONLYALPHA_TEST_CLICKHOUSE_URL=" not in test
    assert "docker compose" in runner
    assert "run --rm acceptance" in runner
    assert "uv run" not in runner

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
