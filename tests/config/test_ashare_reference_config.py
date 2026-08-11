import json
from copy import deepcopy

import pytest
from onlyalpha_market_cn_ashare.factory import OnlyCnAshareMarketProductFactory

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.market.product import OnlyMarketProductResolutionContext
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from tests.runtime_support.market_product import _NoResources

CONFIG = "examples/configs/tushare_daily_backtest.yaml"


def _payload() -> dict[str, object]:
    config = OnlyClusterRunConfig.load(CONFIG)
    return json.loads(json.dumps(dict(config.normalized_payload)))


def _resolve(config: OnlyClusterRunConfig):  # type: ignore[no-untyped-def]
    return OnlyCnAshareMarketProductFactory().resolve(config.market, OnlyMarketProductResolutionContext(_NoResources()))


def test_explicit_ashare_schema_is_canonical_and_order_independent() -> None:
    payload = _payload()
    first = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    records = payload["market"]["config"]["references"]
    payload["market"]["config"]["references"] = list(reversed(records))
    second = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    first_binding = _resolve(first)
    second_binding = _resolve(second)
    assert first_binding.composition_identity == second_binding.composition_identity
    assert OnlyRuntimeEnvironmentBuilder().build(first, first_binding) == OnlyRuntimeEnvironmentBuilder().build(
        second, second_binding
    )


@pytest.mark.parametrize("field", ["board", "st_status", "suspended", "previous_close"])
def test_legacy_loose_ashare_fields_are_rejected(field: str) -> None:
    payload = _payload()
    payload["reference_data"]["instruments"][0][field] = False
    with pytest.raises(ValueError, match=field):
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
    mutation(payload["market"]["config"]["references"][0])
    with pytest.raises((ValueError, TypeError)):
        _resolve(OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG))


def test_missing_and_conflicting_runtime_reference_fail_before_assembly() -> None:
    payload = _payload()
    payload["market"]["config"]["references"] = []
    with pytest.raises(ValueError, match="references must be a non-empty array"):
        _resolve(OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG))

    payload = _payload()
    duplicate = deepcopy(payload["market"]["config"]["references"][0])
    duplicate["previous_close"] = "9.99"
    duplicate.pop("record_fingerprint", None)
    payload["market"]["config"]["references"].append(duplicate)
    with pytest.raises(ValueError, match="REFERENCE_RUNTIME_CONFLICT|REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        _resolve(OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG))


def test_different_reference_identity_does_not_share_runtime() -> None:
    left_payload = _payload()
    right_payload = deepcopy(left_payload)
    right_payload["cluster"]["cluster_id"] = "other-cluster"
    right_payload["market"]["config"]["references"][0]["previous_close"] = "9.99"
    right_payload["market"]["config"]["references"][0].pop("record_fingerprint", None)
    left = OnlyClusterRunConfig.from_mapping(left_payload, source_path=CONFIG)
    right = OnlyClusterRunConfig.from_mapping(right_payload, source_path=CONFIG)
    plan = OnlyRuntimePlanner().plan(
        OnlyEngineId("reference-test"),
        (left, right),
        {left.cluster_id: _resolve(left), right.cluster_id: _resolve(right)},
    )
    assert len(plan.runtime_plans) == 2
