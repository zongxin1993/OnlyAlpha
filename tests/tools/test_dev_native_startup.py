"""Independent actual-container/publication/artifact attestation admission."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import dev


def _deployment(root: Path):
    artifact = root / "test-results/native-workstation/11111111-1111-4111-8111-111111111111"
    runtime = "/workspace/test-results/native-workstation/11111111-1111-4111-8111-111111111111"
    network = {"Id": "network-application", "IPAM": {"Config": [{"Gateway": "172.20.0.1"}]}}
    database_network = {"Id": "network-database"}
    postgres = {
        "NetworkSettings": {
            "Networks": {"onlyalpha-dev-database": {"NetworkID": "network-database", "IPAddress": "172.18.0.2"}}
        }
    }
    record = {
        "Id": "c" * 64,
        "Image": "sha256:" + "d" * 64,
        "Config": {"Labels": {"com.docker.compose.project": "onlyalpha-dev", "com.docker.compose.service": "dev"}},
        "State": {"Running": True},
        "Mounts": [
            {
                "Destination": "/workspace",
                "Type": "bind",
                "Source": str(root / ".test-cache/dev-product-source"),
                "RW": False,
            },
            {"Destination": runtime, "Type": "bind", "Source": str(artifact), "RW": False},
            {"Destination": "/var/lib/onlyalpha", "Type": "volume", "Name": "onlyalpha-dev-user-data", "RW": True},
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
    return artifact, record, network, postgres, database_network


def test_native_startup_attests_observed_exact_container_interfaces_and_publication(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    artifact, record, network, postgres, database = _deployment(tmp_path)
    result = dev.deployment_attestation(record, artifact, network, postgres, database, "sha256:" + "d" * 64)
    assert result["local_address"] == "172.20.0.2"
    assert result["gateway"] == "172.20.0.1"
    assert result["publication"] == "127.0.0.1:5173"
    assert result["postgres_peer"] == "172.18.0.2:5432"
    assert result["container_id"] == record["Id"]


@pytest.mark.parametrize(
    "mutation",
    ("publication", "image", "network", "gateway", "artifact-writable", "artifact-source", "source-writable", "store"),
)
def test_native_startup_never_accepts_claimed_or_foreign_resources(monkeypatch, tmp_path: Path, mutation: str) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    artifact, original, network, postgres, database = _deployment(tmp_path)
    record = copy.deepcopy(original)
    if mutation == "publication":
        record["NetworkSettings"]["Ports"]["5173/tcp"][0]["HostIp"] = "0.0.0.0"
    elif mutation == "image":
        record["Image"] = "sha256:" + "e" * 64
    elif mutation == "network":
        record["NetworkSettings"]["Networks"]["onlyalpha-dev-application"]["NetworkID"] = "other"
    elif mutation == "gateway":
        record["NetworkSettings"]["Networks"]["onlyalpha-dev-application"]["Gateway"] = "172.20.0.3"
    elif mutation == "artifact-writable":
        record["Mounts"][1]["RW"] = True
    elif mutation == "artifact-source":
        record["Mounts"][1]["Source"] = str(tmp_path / "other")
    elif mutation == "source-writable":
        record["Mounts"][0]["RW"] = True
    elif mutation == "store":
        record["Mounts"][2]["Name"] = "other"
    with pytest.raises(ValueError, match="DEV_"):
        dev.deployment_attestation(record, artifact, network, postgres, database, "sha256:" + "d" * 64)
