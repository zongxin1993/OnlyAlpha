"""Pure retained-proof contracts share identities without loading execution."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

pytestmark = pytest.mark.contract


def test_generation_identity_import_does_not_load_runtime_or_private_execution() -> None:
    source = """
import importlib.abc
import sys

forbidden = ('onlyalpha.runtime', 'onlyalpha.application', 'onlyalpha_runtime_generation_manager',
             'onlyalpha.quant_assets.private_factor_execution',
             'onlyalpha.quant_assets.example_seed')

class RejectExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(forbidden):
            raise AssertionError('executable import: ' + fullname)

sys.meta_path.insert(0, RejectExecution())
from onlyalpha.generation_identity import OnlyRuntimeGenerationManifest
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.quant_assets.exact_catalog import only_project_exact_catalog_context
from onlyalpha.quant_assets import OnlyPrivateFactorProviderSnapshotV1
from onlyalpha.quant_assets.private_factor_provider_snapshot import OnlyPrivateFactorProviderSnapshotV1 as Snapshot
assert Snapshot is OnlyPrivateFactorProviderSnapshotV1
assert not any(name.startswith(forbidden) for name in sys.modules)
"""
    completed = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_old_and_neutral_imports_are_the_same_canonical_class_objects() -> None:
    from onlyalpha import generation_identity
    from onlyalpha.quant_assets import private_factor_execution, private_factor_provider_snapshot
    from onlyalpha.runtime import generation

    for name in generation.__all__:
        assert getattr(generation, name) is getattr(generation_identity, name)
    for name in ("OnlyPrivateFactorProviderSnapshotEntryV1", "OnlyPrivateFactorProviderSnapshotV1"):
        assert getattr(private_factor_execution, name) is getattr(private_factor_provider_snapshot, name)
    from onlyalpha.application import catalog_context
    from onlyalpha.quant_assets import exact_catalog

    for name in exact_catalog.__all__:
        assert getattr(catalog_context, name) is getattr(exact_catalog, name)


def test_private_snapshot_round_trip_preserves_existing_fingerprint_domain() -> None:
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.quant_assets.private_factor_provider_snapshot import (
        OnlyPrivateFactorProviderSnapshotEntryV1,
        OnlyPrivateFactorProviderSnapshotV1,
    )

    entry = OnlyPrivateFactorProviderSnapshotEntryV1(
        "private.factor.identity",
        "1",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        1,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "8" * 64,
        "9" * 64,
    )
    snapshot = OnlyPrivateFactorProviderSnapshotV1((entry,))
    assert snapshot.snapshot_fingerprint == only_canonical_fingerprint(
        {"contract": "ONLYALPHA_PRIVATE_FACTOR_PROVIDER_SNAPSHOT_V1", "entries": [entry.to_dict()]}
    )
    assert OnlyPrivateFactorProviderSnapshotV1.from_dict(snapshot.to_dict()) == snapshot


@pytest.mark.parametrize(
    "field",
    (
        "factor_id",
        "semantic_version",
        "factor_api_version",
        "source_sha256",
        "revision_fingerprint",
        "equivalence_evidence_fingerprint",
    ),
)
def test_private_snapshot_entry_rejects_malformed_identity_proof(field):
    from onlyalpha.quant_assets.private_factor_provider_snapshot import OnlyPrivateFactorProviderSnapshotEntryV1

    entry = OnlyPrivateFactorProviderSnapshotEntryV1(
        "private.factor.identity",
        "1",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        1,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "8" * 64,
        "9" * 64,
    )
    payload = entry.to_dict()
    payload[field] = True if field == "factor_api_version" else "malformed identity"
    with pytest.raises(ValueError):
        OnlyPrivateFactorProviderSnapshotEntryV1.from_dict(payload)


def test_private_snapshot_reader_does_not_normalize_noncanonical_retained_entries():
    from onlyalpha.quant_assets.private_factor_provider_snapshot import (
        OnlyPrivateFactorProviderSnapshotEntryV1,
        OnlyPrivateFactorProviderSnapshotV1,
    )

    entry = OnlyPrivateFactorProviderSnapshotEntryV1(
        "private.factor.alpha",
        "1",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        1,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "8" * 64,
        "9" * 64,
    )
    snapshot = OnlyPrivateFactorProviderSnapshotV1((entry, replace(entry, factor_id="private.factor.beta")))
    payload = snapshot.to_dict()
    payload["entries"].reverse()
    with pytest.raises(ValueError):
        OnlyPrivateFactorProviderSnapshotV1.from_dict(payload)
