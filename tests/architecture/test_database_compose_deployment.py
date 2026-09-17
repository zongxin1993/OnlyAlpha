from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
COMPOSE_PATH = DEPLOY / "docker-compose.dev.yml"


def _compose() -> dict[str, object]:
    value = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_deploy_contains_only_the_single_development_topology() -> None:
    compose_files = tuple(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.y*ml")
        if "compose" in path.name.casefold() or path.name.startswith("docker-compose")
    )
    assert compose_files == ("deploy/docker-compose.dev.yml",)
    dockerfiles = tuple(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("Dockerfile*")
        if path.name != "Dockerfile.dev.dockerignore"
    )
    assert dockerfiles == ("deploy/Dockerfile.dev",)
    assert (DEPLOY / "Dockerfile.dev.dockerignore").is_file()
    assert (DEPLOY / "run-web-e2e.sh").is_file()
    assert not (ROOT / "Dockerfile.dev").exists()


def test_dev_compose_has_pinned_private_databases_and_zero_config_defaults() -> None:
    compose = _compose()
    services = compose["services"]
    assert isinstance(services, dict)
    assert {"postgres", "clickhouse", "bootstrap", "api", "web", "research-worker", "backtest-worker", "agent"} <= set(
        services
    )
    postgres = services["postgres"]
    clickhouse = services["clickhouse"]
    assert postgres["image"].startswith("postgres:18.6@sha256:")
    assert clickhouse["image"].startswith("clickhouse/clickhouse-server:26.3@sha256:")
    assert "ports" not in postgres and "ports" not in clickhouse
    assert postgres["environment"] == {
        "POSTGRES_USER": "onlyalpha",
        "POSTGRES_PASSWORD": "onlyalpha",
        "POSTGRES_DB": "${ONLYALPHA_POSTGRES_DB:-onlyalpha}",
    }
    assert clickhouse["environment"]["CLICKHOUSE_USER"] == "onlyalpha"
    assert clickhouse["environment"]["CLICKHOUSE_PASSWORD"] == "onlyalpha"
    assert compose["networks"]["database"]["internal"] is True
    assert set(compose["volumes"]) == {
        "postgres-data",
        "clickhouse-data",
        "user-data",
        "agent-state",
        "agent-locks",
    }
    assert compose["name"] == "${ONLYALPHA_COMPOSE_NAMESPACE:-onlyalpha-dev}"
    for resource in (*compose["networks"].values(), *compose["volumes"].values()):
        assert "${ONLYALPHA_COMPOSE_NAMESPACE:-onlyalpha-dev}" in resource["name"]


def test_all_compose_services_use_the_deploy_owned_dockerfile() -> None:
    services = _compose()["services"]
    assert isinstance(services, dict)
    for service in services.values():
        if "build" in service:
            assert service["build"] == {
                "context": "..",
                "dockerfile": "deploy/Dockerfile.dev",
                **({"target": service["build"]["target"]} if "target" in service["build"] else {}),
            }


def test_playwright_and_fixture_are_application_boundary_profile_services() -> None:
    services = _compose()["services"]
    playwright = services["playwright"]
    fixture = services["web-e2e-fixture"]
    assert playwright["profiles"] == ["web-e2e"]
    assert fixture["profiles"] == ["web-e2e"]
    assert playwright["build"]["target"] == "playwright"
    assert fixture["build"]["target"] == "test"
    assert playwright["networks"] == ["application"]
    assert fixture["networks"] == ["database"]
    assert playwright["environment"] == {"CI": "1", "PLAYWRIGHT_BASE_URL": "http://web:5173"}
    assert playwright["init"] is True
    assert playwright["depends_on"]["web"]["condition"] == "service_healthy"
    assert playwright["depends_on"]["web-e2e-fixture"]["condition"] == "service_completed_successfully"
    for forbidden in (
        "ONLYALPHA_POSTGRES_DSN",
        "ONLYALPHA_CLICKHOUSE_URL",
        "ONLYALPHA_CLICKHOUSE_USER",
        "ONLYALPHA_CLICKHOUSE_PASSWORD",
        "DOCKER_HOST",
    ):
        assert forbidden not in playwright["environment"]
    assert services["web"]["environment"]["ONLYALPHA_WEB_API_TARGET"] == "http://api:8000"


def test_bootstrap_is_the_only_schema_mutation_startup_and_api_waits_for_it() -> None:
    compose = _compose()
    services = compose["services"]
    bootstrap = services["bootstrap"]
    api = services["api"]
    assert bootstrap["command"] == ["python", "scripts/bootstrap.py"]
    assert set(bootstrap["depends_on"]) == {"postgres", "clickhouse"}
    assert all(item["condition"] == "service_healthy" for item in bootstrap["depends_on"].values())
    assert api["depends_on"]["bootstrap"]["condition"] == "service_completed_successfully"
    assert api["command"][-4:] == ["--host", "0.0.0.0", "--port", "8000"]
    assert api["ports"] == ["${ONLYALPHA_HTTP_PORT:-8000}:8000"]


def test_web_and_workers_use_the_same_zero_config_topology() -> None:
    services = _compose()["services"]
    web = services["web"]
    assert web["environment"] == {"ONLYALPHA_WEB_API_TARGET": "http://api:8000"}
    assert web["ports"] == ["${ONLYALPHA_WEB_PORT:-5173}:5173"]
    assert web["depends_on"]["api"]["condition"] == "service_healthy"
    for name in ("research-worker", "backtest-worker"):
        assert services[name]["depends_on"]["bootstrap"]["condition"] == "service_completed_successfully"
    agent = services["agent"]
    assert "--model-api-url" not in agent["command"]
    assert "--model-token-file" not in agent["command"]
    assert agent["depends_on"]["api"]["condition"] == "service_healthy"


def test_test_service_is_a_profile_of_the_canonical_topology_and_isolated() -> None:
    test = _compose()["services"]["test"]
    assert test["profiles"] == ["test"]
    assert test["entrypoint"] == ["python", "scripts/compose_test.py"]
    assert test["environment"]["ONLYALPHA_POSTGRES_DSN"].endswith("/${ONLYALPHA_POSTGRES_DB:-onlyalpha}_test")
    assert "onlyalpha_test" not in test["environment"]["ONLYALPHA_TEST_CLICKHOUSE_URL"]
    assert test["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert test["depends_on"]["clickhouse"]["condition"] == "service_healthy"


def test_dev_dockerfile_builds_python_and_web_targets_without_business_credentials() -> None:
    dockerfile = (DEPLOY / "Dockerfile.dev").read_text(encoding="utf-8")
    assert "FROM python:3.12.12-slim-bookworm@sha256:" in dockerfile
    assert "FROM node:24-bookworm-slim AS web" in dockerfile
    assert "FROM runtime AS test" in dockerfile
    assert "FROM web AS playwright" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "npx playwright install --with-deps chromium" in dockerfile
    assert "uv sync --frozen --all-packages --no-dev" in dockerfile
    assert "python scripts/embed_build_provenance.py" in dockerfile
    for forbidden in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "MODEL_TOKEN", "CONTROL_TOKEN"):
        assert forbidden not in dockerfile


def test_env_template_is_optional_and_contains_only_host_overrides() -> None:
    env = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    assert "ONLYALPHA_WEB_PORT=5173" in env
    assert "ONLYALPHA_HTTP_PORT=8000" in env
    for forbidden in (
        "POSTGRES_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "MODEL_API",
        "MODEL_TOKEN",
        "AGENT_CONTROL",
        "PRODUCT_TOKEN",
    ):
        assert forbidden not in env


def test_ci_validates_and_runs_the_canonical_topology() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "-f deploy/docker-compose.dev.yml" in workflow
    assert "docker compose" in workflow
    for forbidden in (
        "deploy/compose/",
        "compose.production.yaml",
        "compose.acceptance.yaml",
        "run-acceptance.sh",
        ".env.production.example",
    ):
        assert forbidden not in workflow


def test_web_e2e_runner_isolated_and_artifact_safe() -> None:
    runner = (DEPLOY / "run-web-e2e.sh").read_text(encoding="utf-8")
    assert 'export ONLYALPHA_COMPOSE_NAMESPACE="onlyalpha-web-e2e-$$"' in runner
    assert "onlyalpha_web_e2e" in runner
    assert "ONLYALPHA_WEB_E2E_ARTIFACTS_DIR" in runner
    assert "up -d --build --wait" in runner
    assert "run --build --rm playwright" in runner
    assert "compose --profile web-e2e down -v --remove-orphans" in runner
    assert "--abort-on-container-exit" not in runner
