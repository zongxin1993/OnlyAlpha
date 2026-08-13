import json

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.runtime.persistence.lease import OnlyRuntimeStateLease, OnlyRuntimeStateLeaseAlreadyHeld

pytestmark = [pytest.mark.unit, pytest.mark.sim_recovery]


def test_runtime_state_lease_is_exclusive_and_released_on_close(tmp_path) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    first = OnlyRuntimeStateLease(tmp_path, runtime_id)
    metadata = json.loads(first.path.read_text(encoding="utf-8"))
    assert metadata["runtime_id"] == str(runtime_id)
    assert metadata["runtime_instance_id"] == first.owner.runtime_instance_id

    with pytest.raises(OnlyRuntimeStateLeaseAlreadyHeld, match="RUNTIME_STATE_LEASE_ALREADY_HELD") as caught:
        OnlyRuntimeStateLease(tmp_path, runtime_id)
    assert caught.value.code == "RUNTIME_STATE_LEASE_ALREADY_HELD"

    first.close()
    second = OnlyRuntimeStateLease(tmp_path, runtime_id)
    assert second.owner.runtime_instance_id != first.owner.runtime_instance_id
    second.close()
    second.close()


def test_runtime_instance_identity_is_diagnostic_only(tmp_path) -> None:
    lease = OnlyRuntimeStateLease(tmp_path, OnlyRuntimeId("stable-runtime"))
    try:
        assert "stable-runtime" not in lease.owner.runtime_instance_id
        assert lease.path.name == "runtime.lock"
    finally:
        lease.close()
