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


def _inline_contract() -> dict[str, object]:
    return {
        "schema_version": "1",
        "contract_id": "VIRTUAL:BACKTEST-ACCOUNT:COMMISSION",
        "contract_version": "2025.01",
        "broker_id": "virtual",
        "account_scope": {"scope_type": "EXACT_ACCOUNT", "account_id": "backtest-account"},
        "schedules": [
            {
                "schedule_id": "VIRTUAL_BACKTEST_COMMISSION",
                "version": "1",
                "effective_from": "2025-01-01",
                "currency": {"code": "CNY", "precision": 2},
                "source": "BROKER_CONTRACT:VIRTUAL:BACKTEST-ACCOUNT:COMMISSION:2025.01",
                "rules": [
                    {
                        "rule_id": "cash-equity-commission",
                        "fee_type": "BROKER_COMMISSION",
                        "authority": "BROKER",
                        "economic_direction": "CHARGE",
                        "basis": "NOTIONAL",
                        "rate": "0.0003",
                        "calculation_scope": "ORDER_CUMULATIVE",
                        "resolution_policy": "ORDER_FIXED",
                        "minimum": "5.00",
                        "rounding_quantum": "0.01",
                        "rounding_mode": "HALF_UP",
                        "pipeline": "ROUND_THEN_BOUNDS",
                    }
                ],
            }
        ],
    }


def test_old_combined_fee_schema_is_rejected() -> None:
    payload = _payload()
    payload["market"]["fees"] = {}  # type: ignore[index]

    with pytest.raises(OnlyClusterConfigError, match=r"UNKNOWN_FIELD: \$\.market\.fees"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_legacy_market_fee_pack_selection_is_rejected_by_schema(tmp_path) -> None:
    del tmp_path
    payload = _payload()
    payload["market"]["fee_pack"] = {"pack_id": "UNKNOWN", "pack_version": "1"}  # type: ignore[index]
    with pytest.raises(OnlyClusterConfigError, match=r"UNKNOWN_FIELD: \$\.market\.fee_pack"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


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


def test_unknown_reconciliation_policy_fails_composition_without_residue(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["fee_reconciliation_policy"] = {  # type: ignore[index]
        "policy_id": "UNKNOWN",
        "policy_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("reconciliation-policy-unknown"), tmp_path))
    before = engine.snapshot()
    with pytest.raises(ValueError, match="FEE_RECONCILIATION_POLICY_NOT_INSTALLED"):
        engine.add_cluster(config)
    assert engine.snapshot() == before


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
    services.assembler.components.fee_reconciliation_policies.register(policy)
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


def test_unknown_broker_fee_contract_fails_composition_without_residue(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "UNKNOWN",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-unknown"), tmp_path))
    before = engine.snapshot()
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_NOT_INSTALLED"):
        engine.add_cluster(config)
    assert engine.snapshot() == before


def test_inline_broker_contract_is_installed_by_engine_composition(tmp_path) -> None:
    payload = _payload()
    payload["authorities"] = {"broker_fee_contracts": [_inline_contract()]}
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "VIRTUAL:BACKTEST-ACCOUNT:COMMISSION",
        "contract_version": "2025.01",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    services = only_default_engine_services()
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-inline"), tmp_path), services=services)
    engine.add_cluster(config)

    installed = services.assembler.components.broker_fee_contracts.require(
        "VIRTUAL:BACKTEST-ACCOUNT:COMMISSION", "2025.01"
    )
    assert installed == config.broker_fee_contract_authorities[0]
    assert engine.validate().valid


def test_broker_fee_contract_must_match_actual_broker_authority(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "MINIQMT_SIMULATION_ZERO_BROKER_FEES",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-incompatible"), tmp_path))
    before = engine.snapshot()
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE"):
        engine.add_cluster(config)
    assert engine.snapshot() == before
