import json
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.document import OnlyClusterConfigError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
)
from onlyalpha.runtime.defaults import only_default_engine_services


def _payload() -> dict[str, object]:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    return json.loads(json.dumps(dict(config.normalized_payload)))


SOURCE_PATH = Path("tests/fixtures/legacy_macd/cluster.json")


def test_old_combined_fee_schema_is_rejected() -> None:
    payload = _payload()
    payload["market"]["fees"] = {}  # type: ignore[index]

    with pytest.raises(OnlyClusterConfigError, match=r"UNKNOWN_FIELD: \$\.market\.fees"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_unknown_market_fee_pack_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["market"]["fee_pack"] = {"pack_id": "UNKNOWN", "pack_version": "1"}  # type: ignore[index]
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fee-unknown"), tmp_path))
    engine.add_cluster(config)

    result = engine.run()

    assert result.status == "FAILED"
    assert any("MARKET_FEE_PACK_NOT_INSTALLED" in failure for failure in result.failures)


def test_missing_broker_fee_contract_is_rejected_by_config_schema() -> None:
    payload = _payload()
    del payload["accounts"][0]["broker_fee_contract"]  # type: ignore[index]
    with pytest.raises(OnlyClusterConfigError, match=r"\$\.accounts\[0\]\.broker_fee_contract"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_missing_reconciliation_policy_is_rejected_by_config_schema() -> None:
    payload = _payload()
    del payload["accounts"][0]["fee_reconciliation_policy"]  # type: ignore[index]
    with pytest.raises(OnlyClusterConfigError, match=r"fee_reconciliation_policy"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_unknown_reconciliation_policy_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["fee_reconciliation_policy"] = {  # type: ignore[index]
        "policy_id": "UNKNOWN",
        "policy_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("reconciliation-policy-unknown"), tmp_path))
    engine.add_cluster(config)
    result = engine.run()
    assert result.status == "FAILED"
    assert any("FEE_RECONCILIATION_POLICY_NOT_INSTALLED" in failure for failure in result.failures)


def test_custom_reconciliation_policy_is_selected_by_backtest_factory(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["fee_reconciliation_policy"] = {  # type: ignore[index]
        "policy_id": "CUSTOM_STRICT",
        "policy_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    currency = config.accounts[0].initial_cash.currency
    policy = OnlyFeeReconciliationPolicy.create(
        policy_id="CUSTOM_STRICT",
        policy_version="1",
        currency=currency,
        materiality_threshold=OnlyMoney(Decimal("0.00"), currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.BLOCK,
    )
    services = only_default_engine_services()
    services.fee_reconciliation_policies.register(policy)
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId("reconciliation-policy-custom"), tmp_path),
        services=services,
    )
    engine.add_cluster(config)

    engine.initialize()
    try:
        assert engine.runtimes[0].config.fee_reconciliation_policy is policy
    finally:
        engine.stop()


def test_unknown_broker_fee_contract_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "UNKNOWN",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-unknown"), tmp_path))
    engine.add_cluster(config)
    result = engine.run()
    assert result.status == "FAILED"
    assert any("BROKER_FEE_CONTRACT_NOT_INSTALLED" in failure for failure in result.failures)


def test_broker_fee_contract_must_match_actual_broker_authority(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "MINIQMT_SIMULATION_ZERO_BROKER_FEES",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-incompatible"), tmp_path))
    engine.add_cluster(config)
    result = engine.run()
    assert result.status == "FAILED"
    assert any("BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE" in failure for failure in result.failures)
