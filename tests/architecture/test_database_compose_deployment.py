from __future__ import annotations

import tomllib
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
        for path in DEPLOY.rglob("*.y*ml")
        if "compose" in path.name.casefold() or path.name.startswith("docker-compose")
    )
    assert compose_files == ("deploy/docker-compose.dev.yml",)
    dockerfiles = tuple(
        path.relative_to(ROOT).as_posix()
        for path in DEPLOY.rglob("Dockerfile*")
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
    assert set(services) == {"postgres", "clickhouse", "test", "validation", "dev"}
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


def test_local_debugging_has_no_separate_read_only_deployment_or_preflight() -> None:
    compose = _compose()
    services = compose["services"]
    assert isinstance(services, dict)
    assert not {
        "operator-bootstrap",
        "operator-api",
        "operator-setup",
        "operator-web",
        "dev-read-preflight",
    } & set(services)
    volumes = compose["volumes"]
    assert isinstance(volumes, dict)
    assert "existing-user-data" not in volumes
    for script in ("local_operator.py", "operator_setup.py", "dev_workspace_preflight.py"):
        assert not (ROOT / "scripts" / script).exists()
    assert not (DEPLOY / "run-local-operator.sh").exists()


def test_business_deployment_does_not_activate_deferred_services_or_seed_user_goals() -> None:
    services = _compose()["services"]
    assert not {
        "bootstrap",
        "api",
        "web",
        "research-worker",
        "backtest-worker",
        "agent",
        "market-data-bootstrap",
        "web-e2e-fixture",
        "binance-probe-fixture",
        "agent-provider-fixture",
        "playwright",
    }.intersection(services)
    assert "depends_on" not in services["dev"]
    assert services["dev"]["networks"] == ["database", "application"]
    assert services["validation"]["networks"] == ["database"]
    assert "ports" not in services["validation"]
    assert services["validation"]["environment"]["ONLYALPHA_POSTGRES_DSN"].endswith("_test")


def test_ordinary_dev_reuses_fixed_dependencies_without_any_preparation_chain() -> None:
    compose = _compose()
    services = compose["services"]
    assert isinstance(services, dict)
    dev = services["dev"]
    assert dev["profiles"] == ["dev"]
    assert dev["image"] == "${ONLYALPHA_DEV_TOOL_IMAGE_ID:-onlyalpha-browser-test:dev}"
    assert dev["command"] == ["python", "-m", "scripts.dev", "inside"]
    assert dev["ports"] == ["127.0.0.1:5173:5173"]
    assert "depends_on" not in dev and "build" not in dev
    assert (
        dev["environment"]["ONLYALPHA_POSTGRES_DSN"]
        == "postgresql://onlyalpha:onlyalpha@postgres:5432/onlyalpha?sslmode=disable"
    )
    assert dev["environment"]["VITE_ONLYALPHA_LOCAL_SESSION"] == "true"
    assert {m["source"] for m in dev["volumes"] if m["type"] == "volume"} == {"user-data"}
    assert dev["volumes"][0]["source"] == "../.test-cache/dev-product-source"
    assert all(m["read_only"] for m in dev["volumes"] if m["type"] != "volume")
    assert compose["volumes"]["user-data"]["external"] == "${ONLYALPHA_DEV_EXISTING_USER_DATA:-false}"


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
    assert "FROM reference-tools AS test" in dockerfile
    assert "FROM web AS playwright" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "npx playwright install --with-deps chromium" in dockerfile
    assert "uv sync --frozen --all-packages --no-dev --group compose-acceptance" in dockerfile
    assert "python scripts/embed_build_provenance.py" in dockerfile
    for forbidden in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "MODEL_TOKEN", "CONTROL_TOKEN"):
        assert forbidden not in dockerfile


def test_compose_acceptance_group_contains_local_verification_toolchain() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["dependency-groups"]["compose-acceptance"]
    assert {
        "import-linter>=2.13",
        "mypy>=1.15",
        "ruff>=0.11",
        "types-grpcio==1.0.0.20250703",
        "types-protobuf==6.30.2.20250809",
    } <= set(dependencies)


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


def test_web_e2e_runner_reuses_the_frozen_native_validation_entry() -> None:
    runner = (DEPLOY / "run-web-e2e.sh").read_text(encoding="utf-8")
    assert "scripts/dev_verification.py run -- python scripts/native_web_e2e.py" in runner
    for forbidden in ("down -v", "compose run", "--profile web-e2e", "ONLYALPHA_COMPOSE_NAMESPACE="):
        assert forbidden not in runner


def test_local_test_runner_uses_only_the_isolated_canonical_test_profile() -> None:
    runner_path = DEPLOY / "run-tests.sh"
    assert runner_path.is_file()
    runner = runner_path.read_text(encoding="utf-8")
    assert 'export ONLYALPHA_COMPOSE_NAMESPACE="onlyalpha-test-$$"' in runner
    assert "ONLYALPHA_POSTGRES_DB=onlyalpha_test_environment" in runner
    assert "ONLYALPHA_CLICKHOUSE_DATABASE=onlyalpha_test_environment" in runner
    assert 'docker compose -p "$ONLYALPHA_COMPOSE_NAMESPACE" -f "$COMPOSE_FILE"' in runner
    assert "compose --profile test run --build --rm" in runner
    assert 'test "$@"' in runner
    assert '"$ROOT/test-results:/workspace/test-results"' in runner
    assert "compose --profile test down -v --remove-orphans" in runner
    assert 'docker image rm "${ONLYALPHA_COMPOSE_NAMESPACE}-test"' in runner
    assert "\ndocker-compose " not in runner
