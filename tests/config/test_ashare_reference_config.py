import json
from copy import deepcopy

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder
from onlyalpha.runtime.planning import OnlyRuntimePlanner

CONFIG = "examples/configs/tushare_daily_backtest.yaml"


def _payload() -> dict[str, object]:
    config = OnlyClusterRunConfig.load(CONFIG)
    return json.loads(json.dumps(dict(config.normalized_payload)))


def test_explicit_ashare_schema_is_canonical_and_order_independent() -> None:
    payload = _payload()
    first = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    records = payload["reference_data"]["ashare_instruments"]
    payload["reference_data"]["ashare_instruments"] = list(reversed(records))
    second = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    assert first.reference_data.reference_registry_fingerprint == second.reference_data.reference_registry_fingerprint
    assert OnlyRuntimeEnvironmentBuilder().build(first) == OnlyRuntimeEnvironmentBuilder().build(second)


@pytest.mark.parametrize("field", ["board", "st_status", "suspended", "previous_close"])
def test_legacy_loose_ashare_fields_are_rejected(field: str) -> None:
    payload = _payload()
    payload["reference_data"]["instruments"][0][field] = False
    with pytest.raises(ValueError, match="ashare_instruments"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.pop("previous_close"),
        lambda record: record.__setitem__("previous_close", 10.0),
        lambda record: record.__setitem__("board", "UNKNOWN"),
        lambda record: record.__setitem__("suspended", None),
    ],
)
def test_incomplete_or_invalid_ashare_config_fails_closed(mutation) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    mutation(payload["reference_data"]["ashare_instruments"][0])
    with pytest.raises((ValueError, TypeError)):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


def test_missing_and_conflicting_runtime_reference_fail_before_assembly() -> None:
    payload = _payload()
    payload["reference_data"]["ashare_instruments"] = []
    with pytest.raises(ValueError, match="REFERENCE_NOT_FOUND"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)

    payload = _payload()
    duplicate = deepcopy(payload["reference_data"]["ashare_instruments"][0])
    duplicate["previous_close"] = "9.99"
    duplicate.pop("record_fingerprint")
    payload["reference_data"]["ashare_instruments"].append(duplicate)
    with pytest.raises(ValueError, match="REFERENCE_RUNTIME_CONFLICT|REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


def test_different_reference_identity_does_not_share_runtime() -> None:
    left_payload = _payload()
    right_payload = deepcopy(left_payload)
    right_payload["cluster"]["cluster_id"] = "other-cluster"
    right_payload["reference_data"]["ashare_instruments"][0]["previous_close"] = "9.99"
    right_payload["reference_data"]["ashare_instruments"][0].pop("record_fingerprint")
    left = OnlyClusterRunConfig.from_mapping(left_payload, source_path=CONFIG)
    right = OnlyClusterRunConfig.from_mapping(right_payload, source_path=CONFIG)
    plan = OnlyRuntimePlanner().plan(OnlyEngineId("reference-test"), (left, right))
    assert len(plan.runtime_plans) == 2
