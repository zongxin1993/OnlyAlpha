"""Guard the maintained deployment against reviving retired Python services."""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_no_published_python_business_activation() -> None:
    forbidden = {
        "onlyalpha-http-server",
        "onlyalpha-agent",
        "onlyalpha-research-worker",
        "onlyalpha-backtest-worker",
    }
    assert not (ROOT / "packages/backend/pyproject.toml").exists()
    for relative in (
        "pyproject.toml",
        "packages/onlyalpha-agent-orchestrator/pyproject.toml",
        "packages/onlyalpha-runtime-generation-manager/pyproject.toml",
    ):
        project = tomllib.loads((ROOT / relative).read_text())["project"]
        assert not forbidden.intersection(project.get("scripts", {})), relative
        assert not {
            "onlyalpha.runtime_generation_work_authority",
            "onlyalpha.calculation_generation_context",
        }.intersection(project.get("entry-points", {})), relative


def test_sole_dev_topology_has_no_retired_business_or_provisioning_chain() -> None:
    compose = yaml.safe_load((ROOT / "deploy/docker-compose.dev.yml").read_text())
    assert set(compose["services"]) == {"postgres", "clickhouse", "test", "validation", "dev"}
    assert set(compose["volumes"]) == {"postgres-data", "clickhouse-data", "user-data", "agent-state", "agent-locks"}
    assert compose["services"]["dev"]["ports"] == ["127.0.0.1:5173:5173"]
    assert "depends_on" not in compose["services"]["dev"]
    assert all("ports" not in compose["services"][name] for name in ("postgres", "clickhouse", "test", "validation"))


def test_runtime_image_cannot_inherit_or_copy_python_reference_backend() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.dev").read_text()
    stages = re.split(r"(?m)^FROM ", dockerfile)
    runtime = [part for part in stages if re.match(r"[^\n]+ AS runtime\n", part)]
    assert len(runtime) == 1
    stage = runtime[0]
    assert stage.startswith("python:3.12.12-slim-bookworm@sha256:")
    assert "uv sync" not in stage
    assert "COPY ." not in stage and "COPY --chown=onlyalpha:onlyalpha . ." not in stage
    for line in stage.splitlines():
        if line.startswith("WORKDIR "):
            assert not shlex.split(line)[1].startswith("/workspace")
        elif line.startswith("COPY "):
            arguments = [part for part in shlex.split(line)[1:] if not part.startswith("--")]
            assert not arguments[-1].startswith("/workspace")
            for source in arguments[:-1]:
                if source.startswith("/workspace"):
                    assert source == "/workspace/packages/frontend/dist"
    assert 'ENTRYPOINT ["/opt/onlyalpha/bin/onlyalpha-backend"]' in stage
    copies = [shlex.split(line)[1:] for line in stage.splitlines() if line.startswith("COPY ")]
    assert copies == [
        ["--from=runtime-assembly", "/opt/onlyalpha", "/opt/onlyalpha"],
        [
            "--from=runtime-inputs",
            "/source/scripts/runtime_artifacts.py",
            "/usr/local/lib/onlyalpha/runtime_artifacts.py",
        ],
    ]
    assert " AS reference-tools" in dockerfile
    assert "FROM reference-tools AS test" in dockerfile


def test_runtime_algorithm_artifact_uses_the_existing_exact_sdk_builder() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.dev").read_text()
    assert "FROM reference-tools AS algorithm-installation" in dockerfile
    assert "scripts/build_algorithm_sdk.py" in dockerfile
    assert "--install /opt/onlyalpha/algorithms" in dockerfile
    runtime = dockerfile.split(" AS runtime\n", 1)[1]
    assert "COPY --from=runtime-assembly /opt/onlyalpha /opt/onlyalpha" in runtime
    assembly = dockerfile.split(" AS runtime-assembly\n", 1)[1].split("\nFROM ", 1)[0]
    assert "FROM algorithm-installation AS runtime-assembly" in dockerfile
    assert "COPY --from=native-service /onlyalpha-backend /opt/onlyalpha/bin/onlyalpha-backend" in assembly
    assert "COPY --from=web-assets /workspace/packages/frontend/dist /opt/onlyalpha/web" in assembly
    assert "scripts/runtime_build.py seal" in assembly
    assert "scripts/runtime_build.py preflight" in dockerfile
