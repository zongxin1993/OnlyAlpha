"""Start/stop the single ordinary local dev application without preparing data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from scripts.dev_verification import (
    CUT_METADATA,
    ENVIRONMENT_RECORD,
    IMAGE,
    ROOT,
    WEB,
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


def start_stop(mode: str) -> int:
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
        for index, (name, volume) in enumerate((("postgres", "postgres-data"), ("clickhouse", "clickhouse-data"))):
            record = _inspect(f"onlyalpha-dev-{name}-1")[0]
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
        inputs = freeze_source(ROOT, reservation["operation_id"], product=True)
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
                "--wait",
                "--wait-timeout",
                "60",
                "dev",
            ],
            env=environment,
            input=json.dumps(config),
            text=True,
            check=False,
        )
        reservation["completed"] = launched.returncode >= 0
        if source_inputs(ROOT) != inputs:
            raise ValueError("DEV_CURRENT_SOURCE_CHANGED_DURING_STARTUP")
        return launched.returncode


def inside() -> int:
    if ROOT != Path("/workspace") or not Path("/.dockerenv").is_file() or not (ROOT / CUT_METADATA).is_file():
        raise ValueError("DEV_CONTAINED_COMPOSITION_REQUIRED")
    if environment_inputs(ROOT) != json.loads(ENVIRONMENT_RECORD.read_text()):
        raise ValueError("DEV_ENVIRONMENT_REBUILD_REQUIRED")
    subprocess.run(
        ["npx", "--no-install", "vite", "build", "--outDir", "/tmp/onlyalpha-web", "--emptyOutDir"],
        cwd=ROOT / WEB,
        check=True,
    )
    from onlyalpha_http_server.main import main

    return main(
        [
            "--user-data-root",
            "/var/lib/onlyalpha",
            "--dev-web-root",
            "/tmp/onlyalpha-web",
            "--host",
            "0.0.0.0",
            "--port",
            "5173",
        ],
        _contained_dev=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("start", "stop", "inside"))
    args = parser.parse_args()
    return inside() if args.mode == "inside" else start_stop(args.mode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error))
        raise SystemExit(2) from error
