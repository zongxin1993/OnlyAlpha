from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dev


def _host(monkeypatch, tmp_path: Path, *, running: bool = False, consumer: bool = False):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/docker-compose.dev.yml").write_text(
        "image: postgres:18@sha256:" + "a" * 64 + "\nimage: clickhouse/clickhouse-server:26@sha256:" + "b" * 64
    )
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    reservation = {"operation_id": "test-operation", "completed": False}
    calls = []

    @contextmanager
    def operation(*args):
        yield reservation

    def output(command, **kwargs):
        calls.append(command)
        if "config" in command:
            return json.dumps(
                {
                    "volumes": {"user-data": {"name": "onlyalpha-dev-user-data", "external": True}},
                    "services": {
                        "dev": {
                            "volumes": [
                                {
                                    "type": "volume",
                                    "source": "user-data",
                                    "target": "/var/lib/onlyalpha",
                                    "volume": {"nocopy": True},
                                }
                            ]
                        }
                    },
                    "networks": {
                        name: {"name": "onlyalpha-dev-" + name, "internal": name == "database"}
                        for name in ("database", "application")
                    },
                }
            )
        if "network" in command:
            name = command[-1].removeprefix("onlyalpha-dev-")
            return json.dumps(
                [
                    {
                        "Name": command[-1],
                        "Driver": "bridge",
                        "Internal": name == "database",
                        "Labels": {"com.docker.compose.project": "onlyalpha-dev", "com.docker.compose.network": name},
                    }
                ]
            )
        if command[:2] == ["docker", "ps"]:
            return (
                "consumer" if consumer and "volume=onlyalpha-dev-user-data" in command else "dev-id" if running else ""
            )
        return json.dumps(
            [
                {
                    "Id": "sha256:"
                    + ("a" if "postgres:" in command[-1] else "b" if "clickhouse/" in command[-1] else "c") * 64
                }
            ]
        )

    def inspect(name):
        if name == "dev-id":
            return [
                {
                    "Id": name,
                    "State": {"Running": True},
                    "Mounts": [
                        {"Destination": "/workspace", "Source": str(tmp_path / ".test-cache/dev-product-source")},
                        {
                            "Destination": "/var/lib/onlyalpha",
                            "Type": "volume",
                            "Name": "onlyalpha-dev-user-data",
                            "RW": True,
                        },
                    ],
                }
            ]
        service = "postgres" if "postgres" in name else "clickhouse"
        return [
            {
                "Config": {
                    "Labels": {"com.docker.compose.project": "onlyalpha-dev", "com.docker.compose.service": service}
                },
                "Image": "sha256:" + ("a" if service == "postgres" else "b") * 64,
                "State": {"Health": {"Status": "healthy"}},
                "Mounts": [{"Type": "volume", "Name": "onlyalpha-dev-" + service + "-data"}],
            }
        ]

    def run(command, **kwargs):
        calls.append(command)
        if "up" in command:
            configuration = json.loads(kwargs["input"])
            assert configuration["networks"] == {
                name: {"name": "onlyalpha-dev-" + name, "external": True} for name in ("database", "application")
            }
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dev, "host_operation", operation)
    monkeypatch.setattr(dev, "_inspect", inspect)
    monkeypatch.setattr(dev.subprocess, "check_output", output)
    monkeypatch.setattr(dev.subprocess, "run", run)

    def source_inputs(root):
        return {
            "deploy/docker-compose.dev.yml": hashlib.sha256(
                (root / "deploy/docker-compose.dev.yml").read_bytes()
            ).hexdigest()
        }

    def capture(root, operation, **kwargs):
        path = root / ".test-cache/dev-product-source/deploy/docker-compose.dev.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / "deploy/docker-compose.dev.yml").read_bytes())
        return source_inputs(root)

    monkeypatch.setattr(dev, "source_inputs", source_inputs)
    monkeypatch.setattr(dev, "freeze_source", capture)
    _native_artifact_precondition(monkeypatch, tmp_path, source_inputs, calls)
    return calls, reservation


def _native_artifact_precondition(monkeypatch, root: Path, source_inputs, calls) -> None:
    """Provide the new already-built artifact without replacing lifecycle guards.

    Artifact content/source/path failures are independently exercised in
    test_native_workstation_artifacts; actual attestation admission is NOT mocked.
    """
    artifact = root / "test-results/native-workstation/11111111-1111-4111-8111-111111111111"
    artifact.mkdir(parents=True)
    (artifact / "manifest.json").write_text("{}")
    native_id = "d" * 64
    started = False
    original_output, original_inspect, original_run = dev.subprocess.check_output, dev._inspect, dev.subprocess.run

    def output(command, **kwargs):
        if started and command[:2] == ["docker", "ps"] and "label=com.docker.compose.service=dev" in command:
            calls.append(command)
            return native_id
        result = original_output(command, **kwargs)
        if command[:3] == ["docker", "network", "inspect"]:
            records = json.loads(result)
            role = command[-1].removeprefix("onlyalpha-dev-")
            records[0].update(
                Id="network-" + role,
                IPAM={"Config": [{"Gateway": "172.20.0.1" if role == "application" else "172.18.0.1"}]},
            )
            return json.dumps(records)
        return result

    def inspect(name):
        if name == native_id:
            return [
                {
                    "Id": native_id,
                    "Image": "sha256:" + "c" * 64,
                    "Config": {
                        "Labels": {"com.docker.compose.project": "onlyalpha-dev", "com.docker.compose.service": "dev"}
                    },
                    "State": {"Running": True, "Health": {"Status": "healthy"}},
                    "Mounts": [
                        {
                            "Destination": "/workspace",
                            "Type": "bind",
                            "Source": str(root / ".test-cache/dev-product-source"),
                            "RW": False,
                        },
                        {
                            "Destination": "/workspace/" + artifact.relative_to(root).as_posix(),
                            "Type": "bind",
                            "Source": str(artifact),
                            "RW": False,
                        },
                        {
                            "Destination": "/var/lib/onlyalpha",
                            "Type": "volume",
                            "Name": "onlyalpha-dev-user-data",
                            "RW": True,
                        },
                    ],
                    "NetworkSettings": {
                        "Ports": {"5173/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5173"}]},
                        "Networks": {
                            "onlyalpha-dev-application": {
                                "NetworkID": "network-application",
                                "IPAddress": "172.20.0.2",
                                "Gateway": "172.20.0.1",
                            },
                            "onlyalpha-dev-database": {"NetworkID": "network-database", "IPAddress": "172.18.0.5"},
                        },
                    },
                }
            ]
        records = original_inspect(name)
        if name == "onlyalpha-dev-postgres-1":
            records[0]["NetworkSettings"] = {
                "Networks": {"onlyalpha-dev-database": {"NetworkID": "network-database", "IPAddress": "172.18.0.2"}}
            }
        return records

    def run(command, **kwargs):
        nonlocal started
        result = original_run(command, **kwargs)
        if "up" in command and result.returncode == 0:
            started = True
        return result

    monkeypatch.setattr(dev, "artifact_parameters", lambda _: (artifact, {"source_inputs": source_inputs(root)}))
    monkeypatch.setattr(dev.subprocess, "check_output", output)
    monkeypatch.setattr(dev, "_inspect", inspect)
    monkeypatch.setattr(dev.subprocess, "run", run)


def test_start_uses_existing_store_one_project_and_never_builds_or_prepares_data(monkeypatch, tmp_path: Path) -> None:
    calls, reservation = _host(monkeypatch, tmp_path)
    captures = []
    capture = dev.freeze_source
    monkeypatch.setattr(
        dev, "freeze_source", lambda *args, **kwargs: captures.append(kwargs) or capture(*args, **kwargs)
    )
    assert dev.start_stop("start") == 0
    assert captures == [{"product": True}] and reservation["completed"]
    start = next(command for command in calls if "up" in command)
    assert start[:8] == [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        "onlyalpha-dev",
        "-f",
        "-",
    ]
    assert start[-1] == "dev" and all(arg in start for arg in ("--no-deps", "--no-build", "never"))
    assert not any(arg in start for arg in ("bootstrap", "market-data-bootstrap", "build", "run", "down"))


@pytest.mark.parametrize("running,consumer", [(True, False), (False, True)])
def test_active_application_or_other_business_store_consumer_refuses_source_refresh(
    monkeypatch, tmp_path: Path, running, consumer
) -> None:
    calls, _ = _host(monkeypatch, tmp_path, running=running, consumer=consumer)
    monkeypatch.setattr(dev, "freeze_source", lambda *args, **kwargs: pytest.fail("must refuse before refresh"))
    with pytest.raises(ValueError, match="DEV_ALREADY_RUNNING|DEV_BUSINESS_STORE_ALREADY_IN_USE"):
        dev.start_stop("start")
    assert not any("up" in command for command in calls)


def test_unknown_stop_keeps_lifecycle_fence(monkeypatch, tmp_path: Path) -> None:
    _, reservation = _host(monkeypatch, tmp_path, running=True)
    assert dev.start_stop("stop") == 0
    assert reservation["completed"] is False  # command success alone is not stopped-process proof


def test_signalled_startup_keeps_unknown_fence_after_submission(monkeypatch, tmp_path: Path) -> None:
    _, reservation = _host(monkeypatch, tmp_path)
    captures = []
    capture = dev.freeze_source
    monkeypatch.setattr(
        dev, "freeze_source", lambda *args, **kwargs: captures.append(kwargs) or capture(*args, **kwargs)
    )
    original_run = dev.subprocess.run

    def interrupted(command, **kwargs):
        return SimpleNamespace(returncode=-15) if "up" in command else original_run(command, **kwargs)

    monkeypatch.setattr(dev.subprocess, "run", interrupted)
    assert dev.start_stop("start") == -15
    assert captures == [{"product": True}]
    assert reservation["completed"] is False


def test_container_composition_cannot_run_on_standalone_host(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev.subprocess, "run", lambda *a, **k: pytest.fail("no build or API start"))
    with pytest.raises(ValueError, match="DEV_CONTAINED_COMPOSITION_REQUIRED"):
        dev.inside()


@pytest.mark.parametrize("mutation", ["name", "project", "role", "driver", "internal"])
def test_unproved_existing_network_refuses_start_before_source_refresh(
    monkeypatch, tmp_path: Path, mutation: str
) -> None:
    calls, _ = _host(monkeypatch, tmp_path)
    original = dev.subprocess.check_output

    def changed(command, **kwargs):
        result = original(command, **kwargs)
        if "network" in command:
            records = json.loads(result)
            record = records[0]
            if mutation in {"project", "role"}:
                key = "project" if mutation == "project" else "network"
                record["Labels"]["com.docker.compose." + key] = "other"
            else:
                record[{"name": "Name", "driver": "Driver", "internal": "Internal"}[mutation]] = "other"
            return json.dumps(records)
        return result

    monkeypatch.setattr(dev.subprocess, "check_output", changed)
    monkeypatch.setattr(dev, "freeze_source", lambda *args, **kwargs: pytest.fail("must refuse before refresh"))
    with pytest.raises(ValueError, match="DEV_EXISTING_NETWORK_REQUIRED"):
        dev.start_stop("start")
    assert not any("up" in command for command in calls)


def test_foreign_project_refused_before_any_docker_operation(monkeypatch) -> None:
    monkeypatch.setenv("ONLYALPHA_COMPOSE_NAMESPACE", "parallel-dev")
    monkeypatch.setattr(dev.subprocess, "check_output", lambda *a, **k: pytest.fail("no Docker IO"))
    with pytest.raises(ValueError, match="DEV_PROJECT_REFUSED"):
        dev.start_stop("start")


def test_canonical_resolution_uses_captured_bytes_and_live_change_refuses_submission(
    monkeypatch, tmp_path: Path
) -> None:
    calls, _ = _host(monkeypatch, tmp_path)
    path = tmp_path / "deploy/docker-compose.dev.yml"
    captured = path.read_text()
    original = dev.subprocess.check_output

    def changed(command, **kwargs):
        if "config" in command:
            assert command[command.index("-f") + 1] == "-"
            assert kwargs["input"] == captured
            assert (tmp_path / ".test-cache/dev-product-source/deploy/docker-compose.dev.yml").read_text() == captured
            path.write_text(captured + "\n# configuration changed during resolution")
        return original(command, **kwargs)

    monkeypatch.setattr(dev.subprocess, "check_output", changed)
    with pytest.raises(ValueError, match="DEV_CURRENT_SOURCE_CHANGED_DURING_STARTUP"):
        dev.start_stop("start")
    assert not any("up" in command for command in calls)


def test_missing_business_store_never_recreates_or_initializes_it(monkeypatch, tmp_path: Path) -> None:
    calls, _ = _host(monkeypatch, tmp_path)
    original = dev.subprocess.run

    def missing(command, **kwargs):
        if command[:3] == ["docker", "volume", "inspect"]:
            raise dev.subprocess.CalledProcessError(1, command)
        return original(command, **kwargs)

    monkeypatch.setattr(dev.subprocess, "run", missing)
    monkeypatch.setattr(dev, "freeze_source", lambda *args, **kwargs: pytest.fail("no capture without existing store"))
    with pytest.raises(dev.subprocess.CalledProcessError):
        dev.start_stop("start")
    assert not any("up" in command or "config" in command for command in calls)


@pytest.mark.parametrize(
    "mutation",
    ["name", "external", "type", "source", "readonly", "nocopy", "missing", "duplicate", "shadow", "subpath", "tmpfs"],
)
def test_source_upgrade_cannot_replace_durable_store(monkeypatch, tmp_path: Path, mutation: str) -> None:
    calls, _ = _host(monkeypatch, tmp_path)
    original = dev.subprocess.check_output

    def changed(command, **kwargs):
        result = original(command, **kwargs)
        if "config" in command:
            config = json.loads(result)
            mount = config["services"]["dev"]["volumes"][0]
            if mutation == "name":
                config["volumes"]["user-data"]["name"] = "other-store"
            elif mutation == "external":
                config["volumes"]["user-data"]["external"] = False
            elif mutation in {"type", "source"}:
                mount[mutation] = "other"
            elif mutation == "readonly":
                mount["read_only"] = True
            elif mutation == "nocopy":
                del mount["volume"]
            elif mutation == "missing":
                config["services"]["dev"]["volumes"] = []
            elif mutation == "shadow":
                config["services"]["dev"]["volumes"].append(
                    {
                        "type": "bind",
                        "source": "/other",
                        "target": "/var/lib/onlyalpha/research/artifacts",
                    }
                )
            elif mutation == "subpath":
                mount["volume"]["subpath"] = "other"
            elif mutation == "tmpfs":
                config["services"]["dev"]["tmpfs"] = ["/var/lib/onlyalpha/research:rw"]
            else:
                config["services"]["dev"]["volumes"].append(dict(mount))
            return json.dumps(config)
        return result

    monkeypatch.setattr(dev.subprocess, "check_output", changed)
    with pytest.raises(ValueError, match="DEV_APPLICATION_BUSINESS_STORE_REFUSED"):
        dev.start_stop("start")
    assert not any("up" in command for command in calls)


@pytest.mark.parametrize("mode", ["start", "stop"])
@pytest.mark.parametrize(
    "mutation", ["missing", "name", "type", "writable", "duplicate", "shadow", "subpath", "tmpfs", "declared-shadow"]
)
def test_observed_application_mount_must_match_not_just_compose(
    monkeypatch, tmp_path: Path, mode: str, mutation: str
) -> None:
    calls, _ = _host(monkeypatch, tmp_path, running=True)
    original = dev._inspect

    def changed(name):
        records = original(name)
        if name == "dev-id":
            mounts = records[0]["Mounts"]
            store = mounts[1]
            if mutation == "missing":
                mounts.pop()
            elif mutation == "duplicate":
                mounts.append(dict(store))
            elif mutation == "shadow":
                mounts.append({"Type": "bind", "Destination": "/var/lib/onlyalpha/research/artifacts"})
            elif mutation == "subpath":
                records[0]["HostConfig"] = {
                    "Mounts": [
                        {
                            "Target": "/var/lib/onlyalpha",
                            "Type": "volume",
                            "VolumeOptions": {"Subpath": "other"},
                        }
                    ]
                }
            elif mutation == "tmpfs":
                records[0]["HostConfig"] = {"Tmpfs": {"/var/lib/onlyalpha/research/artifacts": "rw"}}
            elif mutation == "declared-shadow":
                records[0]["HostConfig"] = {
                    "Mounts": [
                        {
                            "Target": "/var/lib/onlyalpha/research/artifacts",
                            "Type": "tmpfs",
                        }
                    ]
                }
            else:
                store[{"name": "Name", "type": "Type", "writable": "RW"}[mutation]] = "other"
        return records

    monkeypatch.setattr(dev, "_inspect", changed)
    with pytest.raises(ValueError, match="DEV_APPLICATION_BUSINESS_STORE_REFUSED"):
        dev.start_stop(mode)
    assert not any("up" in command or "stop" in command for command in calls)


@pytest.mark.parametrize(
    "target",
    [
        "/var/lib/onlyalpha/research/artifacts",
        "//var/lib/onlyalpha/research/artifacts",
        "///var/lib/onlyalpha/research/artifacts",
        "/var/lib/onlyalpha/./research/artifacts",
        "/var/lib/onlyalpha/research/../research/artifacts",
    ],
)
@pytest.mark.parametrize(
    "surface", ["compose-shadow", "compose-tmpfs", "observed-shadow", "observed-tmpfs", "declared-shadow"]
)
def test_linux_path_alias_cannot_shadow_retained_history(
    monkeypatch, tmp_path: Path, target: str, surface: str
) -> None:
    observed = not surface.startswith("compose")
    calls, _ = _host(monkeypatch, tmp_path, running=observed)
    original_output, original_inspect = dev.subprocess.check_output, dev._inspect

    def changed_output(command, **kwargs):
        result = original_output(command, **kwargs)
        if "config" in command:
            config = json.loads(result)
            service = config["services"]["dev"]
            if surface == "compose-shadow":
                service["volumes"].append({"type": "bind", "source": "/other", "target": target})
            else:
                service["tmpfs"] = [target + ":rw"]
            return json.dumps(config)
        return result

    def changed_inspect(name):
        records = original_inspect(name)
        if name == "dev-id":
            if surface == "observed-shadow":
                records[0]["Mounts"].append({"Type": "bind", "Destination": target})
            elif surface == "observed-tmpfs":
                records[0]["HostConfig"] = {"Tmpfs": {target: "rw"}}
            else:
                records[0]["HostConfig"] = {"Mounts": [{"Type": "tmpfs", "Target": target}]}
        return records

    monkeypatch.setattr(dev.subprocess, "check_output", changed_output)
    monkeypatch.setattr(dev, "_inspect", changed_inspect)
    with pytest.raises(ValueError, match="DEV_APPLICATION_BUSINESS_STORE_REFUSED"):
        dev.start_stop("start")
    assert not any("up" in command or "stop" in command for command in calls)
