import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.config import (
    OnlyBrokerFeeContractConfig,
    OnlyClusterConfigError,
    OnlyClusterRunConfig,
    OnlyFeeReconciliationPolicyConfig,
)
from onlyalpha.core.errors import OnlyDuplicateIdError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyClusterLoadError, OnlyClusterRemovalPolicy, OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.engine.infrastructure import OnlyResourceConfigurationConflict
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.fee.models import OnlyBrokerFeeAccountScope, OnlyBrokerFeeAccountScopeType
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
)
from onlyalpha.runtime.defaults import only_default_engine_services

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def _engine(tmp_path: Path) -> OnlyEngine:
    return OnlyEngine(OnlyEngineConfig(OnlyEngineId("test-engine"), tmp_path))


def test_add_duplicate_and_remove_cluster(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    handle = engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    assert str(handle.cluster_id) == "macd-demo"
    with pytest.raises(OnlyDuplicateIdError):
        engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    removed = engine.remove_cluster(handle.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert removed.success
    assert not engine.snapshot().clusters


def test_shared_resources_are_reference_counted(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    second = engine.add_cluster(OnlyClusterRunConfig.load(FAST_CONFIG))
    counts = dict(engine.snapshot().resource_reference_counts)
    assert counts["broker:virtual-main"] == 2
    first_result = engine.remove_cluster(first.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert "broker:virtual-main" not in first_result.released_resources
    second_result = engine.remove_cluster(second.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert "broker:virtual-main" in second_result.released_resources


def test_resource_configuration_conflict_rolls_back(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    baseline = OnlyClusterRunConfig.load(FAST_CONFIG)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["brokers"][0]["extensions"]["slippage"] = {
        "type": "FIXED",
        "price_offset": "0.01",
    }
    conflicting = OnlyClusterRunConfig.from_mapping(payload, source_path=FAST_CONFIG)
    before = engine.snapshot()
    with pytest.raises(OnlyResourceConfigurationConflict, match="RESOURCE_CONFIGURATION_CONFLICT"):
        engine.add_cluster(conflicting)
    assert engine.snapshot() == before


def test_same_account_with_different_broker_contract_fails_globally(tmp_path: Path) -> None:
    services = only_default_engine_services()
    alternate = OnlyBrokerFeeContract.create(
        contract_id="ALTERNATE_CONTRACT",
        contract_version="1",
        broker_id="virtual",
        account_scope=OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS),
    )
    services.assembler.components.broker_fee_contracts.register(alternate)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("account-contract-conflict"), tmp_path), services=services)
    engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    second = OnlyClusterRunConfig.load(FAST_CONFIG)
    second = replace(
        second,
        accounts=(
            replace(
                second.accounts[0],
                broker_fee_contract=OnlyBrokerFeeContractConfig(alternate.contract_id, alternate.contract_version),
            ),
        ),
    )
    before = engine.snapshot()
    with pytest.raises(OnlyResourceConfigurationConflict, match=r"account:backtest-account\[existing=.*requested="):
        engine.add_cluster(second)
    assert engine.snapshot() == before


def test_same_account_with_different_reconciliation_policy_fails_globally(tmp_path: Path) -> None:
    services = only_default_engine_services()
    second = OnlyClusterRunConfig.load(FAST_CONFIG)
    currency = second.accounts[0].initial_cash.currency
    policy = OnlyFeeReconciliationPolicy.create(
        policy_id="ALTERNATE_POLICY",
        policy_version="1",
        currency=currency,
        materiality_threshold=OnlyMoney(Decimal("0.00"), currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.BLOCK,
    )
    services.assembler.components.fee_reconciliation_policies.register(policy)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("account-policy-conflict"), tmp_path), services=services)
    engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    second = replace(
        second,
        accounts=(
            replace(
                second.accounts[0],
                fee_reconciliation_policy=OnlyFeeReconciliationPolicyConfig(policy.policy_id, policy.policy_version),
            ),
        ),
    )
    before = engine.snapshot()
    with pytest.raises(OnlyResourceConfigurationConflict, match=r"account:backtest-account\[existing=.*requested="):
        engine.add_cluster(second)
    assert engine.snapshot() == before


def test_legacy_dynamic_strategy_configuration_is_rejected_before_resource_registration(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    baseline = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"]["class_path"] = "missing.plugin:OnlyMissingStrategy"
    before = engine.snapshot()
    with pytest.raises(OnlyClusterConfigError, match="LEGACY_STRATEGY_CONFIGURATION_UNSUPPORTED"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    assert engine.snapshot() == before


def test_failed_composition_leaves_no_contract_authority_residue(tmp_path: Path) -> None:
    baseline = OnlyClusterRunConfig.load(CONFIG)
    contract_id = "ATOMIC_COMPOSITION_TEST"
    first_contract = OnlyBrokerFeeContract.create(
        contract_id=contract_id,
        contract_version="1",
        broker_id="virtual",
        account_scope=OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS),
    )
    corrected_contract = OnlyBrokerFeeContract.create(
        contract_id=contract_id,
        contract_version="1",
        broker_id="virtual",
        account_scope=OnlyBrokerFeeAccountScope(
            OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT,
            baseline.accounts[0].account_id,
        ),
    )
    selection = OnlyBrokerFeeContractConfig(contract_id, "1")
    selected_accounts = (replace(baseline.accounts[0], broker_fee_contract=selection),)
    invalid = replace(
        baseline,
        accounts=selected_accounts,
        factors=(replace(baseline.factors[0], factor_path="missing.plugin:OnlyMissingFactor"),),
        broker_fee_contract_authorities=(first_contract,),
    )
    corrected = replace(
        baseline,
        accounts=selected_accounts,
        broker_fee_contract_authorities=(corrected_contract,),
    )
    services = only_default_engine_services()
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("atomic-composition"), tmp_path), services=services)

    with pytest.raises(ModuleNotFoundError):
        engine.add_cluster(invalid)
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_NOT_INSTALLED"):
        services.assembler.components.broker_fee_contracts.require(contract_id, "1")
    assert not engine.snapshot().clusters
    assert not engine.snapshot().resource_reference_counts

    engine.add_cluster(corrected)
    assert (
        services.assembler.components.broker_fee_contracts.require(contract_id, "1").fingerprint
        == corrected_contract.fingerprint
    )


def test_running_backtest_dynamic_add_is_structured_error(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.add_cluster(OnlyClusterRunConfig.load(CONFIG))
    engine.state = engine.state.RUNNING
    with pytest.raises(OnlyClusterLoadError, match="DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED") as captured:
        engine.add_cluster(OnlyClusterRunConfig.load(FAST_CONFIG))
    assert captured.value.code == "DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE"


def test_missing_cluster_remove_is_non_destructive(tmp_path: Path) -> None:
    result = _engine(tmp_path).remove_cluster(OnlyClusterId("missing"), policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert not result.success
    assert result.code == "CLUSTER_NOT_FOUND"
