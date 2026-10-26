"""Start/stop the single ordinary local dev application without preparing data."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, cast

from scripts.dev_verification import (
    CUT_METADATA,
    ENVIRONMENT_RECORD,
    IMAGE,
    ROOT,
    environment_inputs,
    freeze_source,
    host_operation,
    source_inputs,
)


def _inspect(*names: str) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]], json.loads(subprocess.check_output(["docker", "inspect", *names], text=True, timeout=15))
    )


def _inside_store(target: str) -> bool:
    # Linux treats // as /, while posixpath intentionally preserves it.
    target = posixpath.normpath("/" + target.lstrip("/"))
    return target == "/var/lib/onlyalpha" or target.startswith("/var/lib/onlyalpha/")


def deployment_attestation(
    record: dict[str, Any],
    artifact: Path,
    application_network: dict[str, Any],
    postgres: dict[str, Any],
    database_network: dict[str, Any],
    image: str,
) -> dict[str, str]:
    """Admit observed resources; declarations and environment claims do not attest them."""
    labels = record.get("Config", {}).get("Labels", {})
    runtime = "/workspace/" + artifact.relative_to(ROOT).as_posix()
    mounts = record.get("Mounts", [])

    def bind(target: str, source: Path) -> bool:
        selected = [m for m in mounts if m.get("Destination") == target]
        return (
            len(selected) == 1
            and selected[0].get("Type") == "bind"
            and selected[0].get("RW") is False
            and selected[0].get("Source") in {str(source), "/host_mnt" + str(source)}
        )

    if (
        labels.get("com.docker.compose.project") != "onlyalpha-dev"
        or labels.get("com.docker.compose.service") != "dev"
        or record.get("Image") != image
        or not record.get("State", {}).get("Running")
    ):
        raise ValueError("DEV_CONTAINER_ATTESTATION_INVALID")
    if not bind("/workspace", ROOT / ".test-cache/dev-product-source") or not bind(runtime, artifact):
        raise ValueError("DEV_ARTIFACT_MOUNT_INVALID")
    stores = [m for m in mounts if _inside_store(m.get("Destination", ""))]
    if (
        len(stores) != 1
        or stores[0].get("Destination") != "/var/lib/onlyalpha"
        or stores[0].get("Type") != "volume"
        or stores[0].get("Name") != "onlyalpha-dev-user-data"
        or stores[0].get("RW") is not True
    ):
        raise ValueError("DEV_APPLICATION_BUSINESS_STORE_REFUSED")
    settings = record.get("NetworkSettings", {})
    if settings.get("Ports") != {"5173/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5173"}]}:
        raise ValueError("DEV_PUBLICATION_ATTESTATION_INVALID")
    selected = settings.get("Networks", {})
    if set(selected) != {"onlyalpha-dev-application", "onlyalpha-dev-database"}:
        raise ValueError("DEV_NETWORK_ATTESTATION_INVALID")
    app = selected["onlyalpha-dev-application"]
    db = selected["onlyalpha-dev-database"]
    pg = postgres.get("NetworkSettings", {}).get("Networks", {}).get("onlyalpha-dev-database", {})
    gateways = application_network.get("IPAM", {}).get("Config", [])
    if (
        app.get("NetworkID") != application_network.get("Id")
        or db.get("NetworkID") != database_network.get("Id")
        or pg.get("NetworkID") != database_network.get("Id")
        or len(gateways) != 1
        or app.get("Gateway") != gateways[0].get("Gateway")
    ):
        raise ValueError("DEV_NETWORK_ATTESTATION_INVALID")
    for value in (app.get("IPAddress"), app.get("Gateway"), pg.get("IPAddress")):
        address = ipaddress.ip_address(value)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError("DEV_ADDRESS_ATTESTATION_INVALID")
    if app["IPAddress"] == app["Gateway"] or pg["IPAddress"] == db.get("IPAddress"):
        raise ValueError("DEV_ADDRESS_ATTESTATION_INVALID")
    return {
        "container_id": record["Id"],
        "image_id": image,
        "local_address": app["IPAddress"],
        "gateway": app["Gateway"],
        "publication": "127.0.0.1:5173",
        "postgres_peer": pg["IPAddress"] + ":5432",
        "runtime_root": runtime,
    }


def prepare_native() -> Path:
    """Build before the dev lifecycle reservation and health budget, with its own frozen receipt."""
    output = ROOT / "test-results/native-workstation-build-host" / str(uuid.uuid4())
    output.mkdir(parents=True)
    with (output / "build.log").open("x") as log:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/dev_verification.py"),
                "run",
                "--",
                "python",
                "scripts/native_workstation_build.py",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    evidence = ROOT / "test-results/dev-verification"
    receipt = json.loads((evidence / "last-outcome.json").read_text())
    for name in ("last-outcome.json", "source-inputs.json", "container-inputs.json"):
        shutil.copyfile(evidence / name, output / name)
    if result.returncode != 0 or receipt.get("completed") is not True or receipt.get("command_exit") != 0:
        raise ValueError("DEV_NATIVE_BUILD_FAILED")
    operation = receipt["operation_id"]
    if not isinstance(operation, str) or str(uuid.UUID(operation)) != operation:
        raise ValueError("DEV_NATIVE_BUILD_ID_INVALID")
    artifact = ROOT / "test-results/native-workstation" / operation
    artifact_parameters(artifact)
    return artifact


def artifact_parameters(artifact: Path | None) -> tuple[Path, dict[str, Any]]:
    from scripts.native_workstation_build import verify_artifacts

    if (
        artifact is None
        or artifact.parent != ROOT / "test-results/native-workstation"
        or str(uuid.UUID(artifact.name)) != artifact.name
    ):
        raise ValueError("DEV_NATIVE_ARTIFACT_REQUIRED")
    runtime = Path("/workspace/test-results/native-workstation") / artifact.name
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    return artifact, verify_artifacts(artifact, source_inputs(ROOT), version, runtime_root=runtime)


def start_stop(mode: str, artifact: Path | None = None) -> int:
    if os.environ.get("ONLYALPHA_COMPOSE_NAMESPACE", "onlyalpha-dev") != "onlyalpha-dev":
        raise ValueError("DEV_PROJECT_REFUSED")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("ONLYALPHA_")}
    environment.update(ONLYALPHA_COMPOSE_NAMESPACE="onlyalpha-dev", ONLYALPHA_DEV_EXISTING_USER_DATA="true")
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        "onlyalpha-dev",
        "-f",
        str(ROOT / "deploy/docker-compose.dev.yml"),
        "--profile",
        "dev",
    ]
    with host_operation(ROOT, "dev-" + mode) as reservation:
        reservation["completed"] = True
        ids = subprocess.check_output(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.docker.compose.project=onlyalpha-dev",
                "--filter",
                "label=com.docker.compose.service=dev",
            ],
            text=True,
            timeout=15,
        ).split()
        if len(ids) > 1:
            raise ValueError("DEV_APPLICATION_IDENTITY_AMBIGUOUS")
        records = _inspect(*ids) if ids else []
        for record in records:
            source = next((m for m in record["Mounts"] if m["Destination"] == "/workspace"), None)
            if source is None or source["Source"] not in {
                str(ROOT / ".test-cache/dev-product-source"),
                "/host_mnt" + str(ROOT / ".test-cache/dev-product-source"),
            }:
                raise ValueError("DEV_APPLICATION_WORKTREE_REFUSED")
            store = [m for m in record["Mounts"] if _inside_store(m["Destination"])]
            if len(store) != 1 or (
                store[0].get("Destination") != "/var/lib/onlyalpha"
                or store[0].get("Type") != "volume"
                or store[0].get("Name") != "onlyalpha-dev-user-data"
                or store[0].get("RW") is not True
            ):
                raise ValueError("DEV_APPLICATION_BUSINESS_STORE_REFUSED")
            host = record.get("HostConfig", {})
            if any(_inside_store(target) for target in host.get("Tmpfs", {})) or any(
                _inside_store(m["Target"])
                and (m["Target"] != "/var/lib/onlyalpha" or m.get("VolumeOptions", {}).get("Subpath"))
                for m in host.get("Mounts", [])
            ):
                raise ValueError("DEV_APPLICATION_BUSINESS_STORE_REFUSED")
        if mode == "stop":
            if not records:
                return 0
            reservation["completed"] = False
            result = subprocess.run([*compose, "stop", "dev"], env=environment, check=False)
            if result.returncode == 0 and not _inspect(records[0]["Id"])[0]["State"]["Running"]:
                reservation["completed"] = True
            return result.returncode
        if records and records[0]["State"]["Running"]:
            raise ValueError("DEV_ALREADY_RUNNING_STOP_BEFORE_SOURCE_REFRESH")
        consumers = subprocess.check_output(
            ["docker", "ps", "-q", "--filter", "volume=onlyalpha-dev-user-data"], text=True, timeout=15
        ).split()
        if consumers:
            raise ValueError("DEV_BUSINESS_STORE_ALREADY_IN_USE")
        pinned_images = re.findall(
            r"image: ((?:postgres|clickhouse/clickhouse-server):[^\s]+@sha256:[0-9a-f]{64})",
            (ROOT / "deploy/docker-compose.dev.yml").read_text(),
        )
        if len(pinned_images) != 2:
            raise ValueError("DEV_DATABASE_IMAGE_CONTRACT_INVALID")
        postgres_record = None
        for index, (name, volume) in enumerate((("postgres", "postgres-data"), ("clickhouse", "clickhouse-data"))):
            record = _inspect(f"onlyalpha-dev-{name}-1")[0]
            if name == "postgres":
                postgres_record = record
            images = json.loads(
                subprocess.check_output(["docker", "image", "inspect", pinned_images[index]], text=True, timeout=15)
            )
            if (
                record["Config"]["Labels"].get("com.docker.compose.project") != "onlyalpha-dev"
                or record["Config"]["Labels"].get("com.docker.compose.service") != name
                or record["Image"] != images[0]["Id"]
                or record["State"].get("Health", {}).get("Status") != "healthy"
                or [m["Name"] for m in record["Mounts"] if m["Type"] == "volume"] != ["onlyalpha-dev-" + volume]
            ):
                raise ValueError("DEV_EXISTING_DATABASE_REQUIRED")
        # Existing business volume only: never create/adopt a new or historical store.
        subprocess.run(
            ["docker", "volume", "inspect", "onlyalpha-dev-user-data"],
            stdout=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
        image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], text=True, timeout=15))[0]
        environment["ONLYALPHA_DEV_TOOL_IMAGE_ID"] = image["Id"]
        # Same canonical topology, but existing resources are references here, not
        # desired resources for Compose to reconcile (e.g. after label changes).
        networks = {}
        for name in ("database", "application"):
            expected = "onlyalpha-dev-" + name
            network = json.loads(
                subprocess.check_output(["docker", "network", "inspect", expected], text=True, timeout=15)
            )[0]
            if (
                network["Name"] != expected
                or network["Labels"].get("com.docker.compose.project") != "onlyalpha-dev"
                or network["Labels"].get("com.docker.compose.network") != name
                or network["Driver"] != "bridge"
                or network["Internal"] != (name == "database")
            ):
                raise ValueError("DEV_EXISTING_NETWORK_REQUIRED")
            networks[name] = network
        artifact, manifest = artifact_parameters(artifact)
        environment["ONLYALPHA_NATIVE_ARTIFACT_ROOT"] = "/workspace/" + artifact.relative_to(ROOT).as_posix()
        environment["ONLYALPHA_NATIVE_ARTIFACT_SOURCE"] = str(artifact)
        inputs = freeze_source(ROOT, reservation["operation_id"], product=True)
        if manifest["source_inputs"] != inputs:
            raise ValueError("DEV_NATIVE_ARTIFACT_INPUT_CHANGED")
        # Docker cannot create a nested bind destination beneath the read-only
        # source mount. Prepare only its empty, exact artifact mountpoint first.
        mountpoint = ROOT / ".test-cache/dev-product-source"
        for part in artifact.relative_to(ROOT).parts:
            mountpoint /= part
            if mountpoint.is_symlink() or (mountpoint.exists() and not mountpoint.is_dir()):
                raise ValueError("DEV_NATIVE_ARTIFACT_MOUNTPOINT_INVALID")
            mountpoint.mkdir(exist_ok=True)
        canonical_path = "deploy/docker-compose.dev.yml"
        canonical_bytes = (ROOT / ".test-cache/dev-product-source" / canonical_path).read_bytes()
        if hashlib.sha256(canonical_bytes).hexdigest() != inputs[canonical_path]:
            raise ValueError("DEV_CANONICAL_COMPOSE_INPUT_CHANGED")
        # No second topology/file is created. Only resource ownership in the
        # canonical resolved input is narrowed to preserve observed dev identities.
        compose[compose.index("-f") + 1] = "-"
        compose += ["--project-directory", str(ROOT / "deploy")]
        config = json.loads(
            subprocess.check_output(
                [*compose, "config", "--format", "json"],
                input=canonical_bytes.decode("utf-8"),
                env=environment,
                text=True,
                timeout=15,
            )
        )
        # Compose declarations alone do not prove the observed container mount.
        # Reject a changed/anonymous/bind store instead of treating it as an upgrade.
        if config.get("volumes", {}).get("user-data") != {
            "name": "onlyalpha-dev-user-data",
            "external": True,
        }:
            raise ValueError("DEV_APPLICATION_BUSINESS_STORE_REFUSED")
        service = config.get("services", {}).get("dev", {})
        stores = [m for m in service.get("volumes", []) if _inside_store(m.get("target", ""))]
        if len(stores) != 1 or (
            stores[0].get("target") != "/var/lib/onlyalpha"
            or stores[0].get("type") != "volume"
            or stores[0].get("source") != "user-data"
            or stores[0].get("read_only", False) is not False
            or stores[0].get("volume", {}).get("nocopy") is not True
            or stores[0].get("volume", {}).get("subpath")
            or any(_inside_store(target.split(":", 1)[0]) for target in service.get("tmpfs", []))
        ):
            raise ValueError("DEV_APPLICATION_BUSINESS_STORE_REFUSED")
        for name in ("database", "application"):
            expected = "onlyalpha-dev-" + name
            if config["networks"][name]["name"] != expected:
                raise ValueError("DEV_EXISTING_NETWORK_REQUIRED")
            config["networks"][name] = {"name": expected, "external": True}
        if source_inputs(ROOT) != inputs:
            raise ValueError("DEV_CURRENT_SOURCE_CHANGED_DURING_STARTUP")
        reservation["completed"] = False
        launched = subprocess.run(
            [
                *compose,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "dev",
            ],
            env=environment,
            input=json.dumps(config),
            text=True,
            check=False,
        )
        if launched.returncode != 0:
            return launched.returncode
        ids = subprocess.check_output(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=onlyalpha-dev",
                "--filter",
                "label=com.docker.compose.service=dev",
            ],
            text=True,
            timeout=15,
        ).split()
        if len(ids) != 1 or postgres_record is None:
            raise ValueError("DEV_APPLICATION_IDENTITY_AMBIGUOUS")
        record = _inspect(ids[0])[0]
        attestation = deployment_attestation(
            record, artifact, networks["application"], postgres_record, networks["database"], image["Id"]
        )
        attestation["artifact_manifest_sha256"] = hashlib.sha256((artifact / "manifest.json").read_bytes()).hexdigest()
        temporary = artifact.parent / (".deployment-" + artifact.name + ".pending")
        with temporary.open("x") as published:
            published.write(json.dumps(attestation, sort_keys=True) + "\n")
        temporary.chmod(0o600)
        temporary.replace(artifact / "deployment.json")
        deadline = time.monotonic() + 60
        while True:
            observed = _inspect(record["Id"])[0]
            if not observed["State"].get("Running"):
                raise ValueError("DEV_NATIVE_STARTUP_FAILED")
            status = observed["State"].get("Health", {}).get("Status")
            if status == "healthy":
                break
            if status == "unhealthy" or time.monotonic() >= deadline:
                raise ValueError("DEV_NATIVE_STARTUP_UNAVAILABLE")
            threading.Event().wait(0.2)
        if source_inputs(ROOT) != inputs:
            raise ValueError("DEV_CURRENT_SOURCE_CHANGED_DURING_STARTUP")
        reservation["completed"] = True
        return 0


def inside() -> int:
    if ROOT != Path("/workspace") or not Path("/.dockerenv").is_file() or not (ROOT / CUT_METADATA).is_file():
        raise ValueError("DEV_CONTAINED_COMPOSITION_REQUIRED")
    if environment_inputs(ROOT) != json.loads(ENVIRONMENT_RECORD.read_text()):
        raise ValueError("DEV_ENVIRONMENT_REBUILD_REQUIRED")
    from scripts.native_workstation_build import verify_artifacts

    artifact = Path(os.environ["ONLYALPHA_NATIVE_ARTIFACT_ROOT"])
    if (
        artifact.parent != Path("/workspace/test-results/native-workstation")
        or str(uuid.UUID(artifact.name)) != artifact.name
    ):
        raise ValueError("DEV_NATIVE_ARTIFACT_REQUIRED")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    manifest = verify_artifacts(artifact, source_inputs(ROOT), version)
    # Host inspection can only attest assigned interfaces after Docker starts
    # the container. Await that one protected deployment record within a fixed
    # infrastructure startup budget; no default addresses or authentication.
    deadline = time.monotonic() + 20
    deployment = artifact / "deployment.json"
    while not deployment.exists():
        if time.monotonic() >= deadline:
            raise ValueError("DEV_DEPLOYMENT_ATTESTATION_MISSING")
        threading.Event().wait(0.05)
    if deployment.is_symlink() or deployment.stat().st_size > 32768:
        raise ValueError("DEV_DEPLOYMENT_ATTESTATION_INVALID")
    attestation = json.loads(deployment.read_text())
    if (
        set(attestation)
        != {
            "container_id",
            "image_id",
            "local_address",
            "gateway",
            "publication",
            "postgres_peer",
            "runtime_root",
            "artifact_manifest_sha256",
        }
        or attestation["runtime_root"] != str(artifact)
        or attestation["artifact_manifest_sha256"]
        != hashlib.sha256((artifact / "manifest.json").read_bytes()).hexdigest()
        or os.environ.get("HOSTNAME") != attestation["container_id"][:12]
    ):
        raise ValueError("DEV_DEPLOYMENT_ATTESTATION_INVALID")
    # Verify the host-observed address is assigned in this network namespace.
    import fcntl
    import socket
    import struct

    addresses = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as interface:
        for _, name in socket.if_nameindex():
            try:
                raw = fcntl.ioctl(interface.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
                addresses.add(socket.inet_ntoa(raw[20:24]))
            except OSError:
                continue  # Interfaces without an IPv4 address cannot attest it.
    if attestation["local_address"] not in addresses or attestation["publication"] != "127.0.0.1:5173":
        raise ValueError("DEV_DEPLOYMENT_ATTESTATION_INVALID")
    from psycopg.conninfo import conninfo_to_dict

    pg = conninfo_to_dict(os.environ["ONLYALPHA_POSTGRES_DSN"])
    pg_user = pg.get("user")
    pg_database = pg.get("dbname")
    if (
        pg.get("host") != "postgres"
        or pg.get("port", "5432") != "5432"
        or pg.get("sslmode") != "disable"
        or not isinstance(pg_user, str)
        or not pg_user
        or not isinstance(pg_database, str)
        or not pg_database
    ):
        raise ValueError("DEV_POSTGRES_CONFIGURATION_INVALID")
    environment = dict(os.environ)
    for name in ("ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT", "ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT_FILE"):
        environment.pop(name, None)
    environment.update(
        ONLYALPHA_NATIVE_DEPLOYMENT="CONTAINED_DEVELOPMENT",
        ONLYALPHA_NATIVE_LOCAL_ADDRESS=attestation["local_address"],
        ONLYALPHA_NATIVE_GATEWAY=attestation["gateway"],
        ONLYALPHA_NATIVE_PUBLICATION=attestation["publication"],
        ONLYALPHA_NATIVE_POSTGRES_PEER=attestation["postgres_peer"],
        ONLYALPHA_NATIVE_POSTGRES_USER=pg_user,
        ONLYALPHA_NATIVE_POSTGRES_DATABASE=pg_database,
        ONLYALPHA_NATIVE_SCHEMA=str(artifact / "schema"),
        ONLYALPHA_NATIVE_WEB_ASSETS=str(artifact / "web"),
        ONLYALPHA_NATIVE_ALGORITHMS=str(artifact / "algorithms"),
        ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT_FILE=str(artifact / "algorithm-artifact.sha256"),
        ONLYALPHA_NATIVE_SOURCE_TRUST="/etc/ssl/certs/ca-certificates.crt",
    )
    if manifest["build_environment"] != {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"}:
        raise ValueError("DEV_NATIVE_WEB_BUILD_INVALID")
    executable = str(artifact / "bin/onlyalpha-backend")
    os.execve(executable, [executable, "--user-data-root", "/var/lib/onlyalpha"], environment)
    raise AssertionError("exec returned")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("start", "stop", "inside"))
    args = parser.parse_args()
    if os.environ.get("ONLYALPHA_COMPOSE_NAMESPACE", "onlyalpha-dev") != "onlyalpha-dev":
        raise ValueError("DEV_PROJECT_REFUSED")
    return (
        inside() if args.mode == "inside" else start_stop(args.mode, prepare_native() if args.mode == "start" else None)
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error))
        raise SystemExit(2) from error
