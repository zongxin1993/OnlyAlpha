from onlyalpha_gateway_protocol import canonical_test_mutation_fingerprint


def test_transport_metadata_does_not_change_canonical_test_command_fingerprint() -> None:
    payload = "canonical-intent"
    expected = canonical_test_mutation_fingerprint(payload)
    assert expected == "600188cc7b50710f869ea91c9ef9d420ae956ec3b607f5fa5cf0745077bd44b2"

    for _correlation_id, _gateway_instance_id, _deadline in (
        ("attempt-a", "instance-a", 1.0),
        ("attempt-b", "instance-b", 30.0),
    ):
        assert canonical_test_mutation_fingerprint(payload) == expected

    assert canonical_test_mutation_fingerprint("different-intent") != expected


def test_artifact_wire_identity_is_independent_of_legacy_backend() -> None:
    import subprocess
    import sys

    source = """
import importlib.abc
import sys
class NoBackend(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "onlyalpha" or fullname.startswith("onlyalpha."):
            raise AssertionError("undeclared legacy backend dependency: " + fullname)
sys.meta_path.insert(0, NoBackend())
from onlyalpha_gateway_protocol.distribution import (
    OnlyDistributionArtifactManifest as Manifest,
    OnlyDistributionArtifactRole as Role,
    OnlyArtifactSourceProvenanceAuthority as Provenance,
)
import hashlib
import json
assert {name for name in sys.modules if name == "onlyalpha_gateway_protocol" or name.startswith("onlyalpha_gateway_protocol.")} == {"onlyalpha_gateway_protocol", "onlyalpha_gateway_protocol.distribution"}
payload = {
    "schema_version": 1, "role": "CORE", "source_provenance_authority": "ONLYALPHA_GIT",
    "source_repository": "OnlyAlpha", "source_revision": "1" * 40,
    "distribution_name": "onlyalpha", "distribution_version": "0.11.1",
    "artifact_logical_name": "onlyalpha-0.11.1-py3-none-any.whl",
    "artifact_sha256": "a" * 64, "artifact_size": 1,
    "tested_core_execution_fingerprint": None, "provider_id": None,
    "provider_version": None, "provider_content_fingerprint": None,
    "assets": [], "implementations": [],
}
manifest = Manifest(Role.CORE, Provenance.ONLYALPHA_GIT, "OnlyAlpha", "1" * 40,
                    "onlyalpha", "0.11.1", "onlyalpha-0.11.1-py3-none-any.whl", "a" * 64, 1)
assert manifest.to_dict(include_fingerprint=False) == payload
expected = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
assert manifest.manifest_fingerprint == expected
assert Manifest.from_dict(manifest.to_dict()) == manifest
bad = manifest.to_dict()
bad["source_repository"] = "研究"
try:
    Manifest.from_dict(bad)
except ValueError:
    pass
else:
    raise AssertionError("noncanonical wire identity accepted")
"""
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_gateway_exports_keep_their_original_client_identities() -> None:
    from importlib import import_module

    import onlyalpha_gateway_protocol as protocol

    for name in protocol.__all__:
        module = {"PROTOCOL_MAJOR": ".constants", "canonical_test_mutation_fingerprint": ".identity"}.get(
            name, ".client"
        )
        assert getattr(protocol, name) is getattr(import_module(module, protocol.__name__), name)
