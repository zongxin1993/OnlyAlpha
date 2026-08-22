from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.research.operations.deployment import (
    SEMANTIC_STORE_IDENTITY_FILE,
    OnlyResearchDeploymentCoherenceVerifier,
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchFrozenDeploymentCheck,
    OnlyResearchSemanticStoreId,
    OnlyResearchSemanticStoreIdentity,
)

pytestmark = pytest.mark.contract


class _Binding:
    def __init__(self, store_id: OnlyResearchSemanticStoreId) -> None:
        self.store_id = store_id

    def load_semantic_store_id(self) -> OnlyResearchSemanticStoreId:
        return self.store_id


def test_empty_semantic_root_initializes_one_stable_immutable_identity(tmp_path: Path) -> None:
    identity = OnlyResearchSemanticStoreIdentity(tmp_path / "research")
    initialized = identity.initialize()

    assert identity.initialize() == initialized
    assert identity.load_verified() == initialized
    assert json.loads(identity.path.read_text()) == {"schema_version": 1, "store_id": str(initialized)}
    assert tuple(item.name for item in identity.path.parent.iterdir()) == (SEMANTIC_STORE_IDENTITY_FILE,)


def test_non_empty_semantic_root_without_identity_refuses_adoption(tmp_path: Path) -> None:
    root = tmp_path / "research"
    (root / "datasets").mkdir(parents=True)

    with pytest.raises(OnlyResearchDeploymentError) as raised:
        OnlyResearchSemanticStoreIdentity(root).initialize()

    assert raised.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_NOT_EMPTY
    assert not (root / SEMANTIC_STORE_IDENTITY_FILE).exists()


@pytest.mark.parametrize(
    ("payload", "code"),
    (
        ("not-json", OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT),
        (
            '{"schema_version":2,"store_id":"00000000-0000-4000-8000-000000000001"}',
            OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_UNSUPPORTED,
        ),
        (
            '{"extra":true,"schema_version":1,"store_id":"00000000-0000-4000-8000-000000000001"}',
            OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT,
        ),
    ),
)
def test_identity_metadata_corruption_and_unknown_schema_fail_closed(
    tmp_path: Path,
    payload: str,
    code: OnlyResearchDeploymentErrorCode,
) -> None:
    root = tmp_path / "research"
    root.mkdir()
    (root / SEMANTIC_STORE_IDENTITY_FILE).write_text(payload)

    with pytest.raises(OnlyResearchDeploymentError) as raised:
        OnlyResearchSemanticStoreIdentity(root).load_verified()

    assert raised.value.code is code


def test_same_namespace_through_different_local_paths_is_compatible(tmp_path: Path) -> None:
    physical = tmp_path / "physical" / "research"
    store_id = OnlyResearchSemanticStoreIdentity(physical).initialize()
    mounted = tmp_path / "mounted-research"
    mounted.symlink_to(physical, target_is_directory=True)

    # A mount point itself may be a symlink in this local representation; resolve it as deployment wiring.
    verifier = OnlyResearchDeploymentCoherenceVerifier(
        OnlyResearchSemanticStoreIdentity(mounted.resolve()),
        _Binding(store_id),
    )
    assert verifier.verify() == store_id


def test_wrong_namespace_fails_and_frozen_process_check_cannot_dynamically_rebind(tmp_path: Path) -> None:
    identity = OnlyResearchSemanticStoreIdentity(tmp_path / "research")
    local = identity.initialize()
    binding = _Binding(OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000099"))
    verifier = OnlyResearchDeploymentCoherenceVerifier(identity, binding)
    frozen = OnlyResearchFrozenDeploymentCheck(verifier)

    with pytest.raises(OnlyResearchDeploymentError) as mismatch:
        verifier.verify()
    assert mismatch.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH

    binding.store_id = local
    assert verifier.verify() == local
    with pytest.raises(OnlyResearchDeploymentError) as still_frozen:
        frozen.assert_compatible()
    assert still_frozen.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH
