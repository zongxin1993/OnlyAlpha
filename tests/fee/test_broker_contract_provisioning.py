import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_plugin_cn_ashare.fee_pack import only_cn_a_share_market_fee_pack

from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.fee import (
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeContractDocumentLoader,
    OnlyBrokerFeeContractRegistry,
    OnlyFeeBasisValues,
    OnlyFeeCalculationScope,
    OnlyFeeEngine,
    OnlyFeePolicyResolution,
    OnlyFeeReconciliationComponentIdentity,
    OnlyFeeSubject,
    OnlyFeeType,
    OnlyLocalFeeFinality,
    OnlyOrderFeeAccrualAuthority,
    OnlyOrderFeeAccrualState,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
    OnlyResolvedFeePolicySet,
    OnlyTradeFeeAssessmentRequest,
)
from onlyalpha.fee.evidence import OnlyExternalFeeComponent, OnlyExternalFeeEvidence, OnlyExternalFeeEvidenceMode
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.reconciliation import (
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyFeeReconciliationStatus,
    OnlyLocalFeeReconciliationComponent,
)
from onlyalpha.fee.reconciliation_policy import only_standard_fee_reconciliation_policy
from onlyalpha.fee.schedules import OnlyMarketFeeApplicabilityContext


def _document() -> dict[str, object]:
    return {
        "schema_version": "1",
        "contract_id": "BROKER-A:ACCOUNT-001:CASH-EQUITY-COMMISSION",
        "contract_version": "2025.01",
        "broker_id": "broker-a",
        "account_scope": {"scope_type": "EXACT_ACCOUNT", "account_id": "ACCOUNT-001"},
        "schedules": [
            {
                "schedule_id": "BROKER_A_CASH_EQUITY_COMMISSION",
                "version": "1",
                "effective_from": "2025-01-01",
                "currency": {"code": "CNY", "precision": 2},
                "source": "BROKER_CONTRACT:BROKER-A:ACCOUNT-001:CASH-EQUITY-COMMISSION:2025.01",
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


def test_strict_exact_account_contract_provisions_to_registry() -> None:
    registry = OnlyBrokerFeeContractRegistry()
    contract = OnlyBrokerFeeContractDocumentLoader.install(_document(), registry)
    assert registry.require(contract.contract_id, contract.contract_version) == contract
    assert contract.account_scope.scope_type is OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT
    assert contract.account_scope.account_id == OnlyAccountId("ACCOUNT-001")
    rule = contract.schedules[0].rules[0]
    assert rule.fee_type is OnlyFeeType.BROKER_COMMISSION
    assert rule.calculation_scope is OnlyFeeCalculationScope.ORDER_CUMULATIVE
    assert rule.minimum == Decimal("5.00")


def test_valid_all_account_contract_is_supported() -> None:
    document = _document()
    document["account_scope"] = {"scope_type": "ALL_ACCOUNTS"}
    contract = OnlyBrokerFeeContractDocumentLoader.load(document)
    assert contract.account_scope.scope_type is OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS
    contract.validate_compatibility(broker_id="broker-a", account_id=OnlyAccountId("ANY-ACCOUNT"))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"schema_version": "2"}), "schema_version"),
        (lambda value: value.update({"unknown": True}), "unknown field"),
        (lambda value: value.update({"broker_id": ""}), "broker_id"),
        (lambda value: value["account_scope"].update({"account_id": ""}), "account_id"),
        (lambda value: value["schedules"][0]["currency"].update({"code": "USD"}), "must be CNY"),
        (lambda value: value["schedules"][0].update({"source": "manual"}), "source must equal"),
        (lambda value: value["schedules"][0]["rules"][0].update({"rate": 0.0003}), "quoted Decimal"),
        (lambda value: value["schedules"][0]["rules"][0].update({"authority": "MARKET"}), "Broker-owned"),
        (lambda value: value["schedules"][0].update({"source": "BROKER_CONTRACT:WRONG:1"}), "source must equal"),
    ],
)
def test_invalid_contract_documents_fail_closed(mutate, message: str) -> None:
    value = deepcopy(_document())
    mutate(value)
    with pytest.raises(ValueError, match=message):
        OnlyBrokerFeeContractDocumentLoader.load(value)


def test_duplicate_and_fingerprint_conflicts_fail_closed() -> None:
    registry = OnlyBrokerFeeContractRegistry()
    first = OnlyBrokerFeeContractDocumentLoader.install(_document(), registry)
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_DUPLICATE_VERSION"):
        registry.register(first)
    changed = _document()
    changed["schedules"][0]["rules"][0]["rate"] = "0.0004"
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT"):
        registry.register(OnlyBrokerFeeContractDocumentLoader.load(changed))


def test_wrong_broker_account_and_unknown_contract_fail_closed() -> None:
    contract = OnlyBrokerFeeContractDocumentLoader.load(_document())
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE"):
        contract.validate_compatibility(broker_id="broker-b", account_id=OnlyAccountId("ACCOUNT-001"))
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE"):
        contract.validate_compatibility(broker_id="broker-a", account_id=OnlyAccountId("ACCOUNT-002"))
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_NOT_INSTALLED"):
        OnlyBrokerFeeContractRegistry().require(contract.contract_id, contract.contract_version)


def _commission_assessment(
    cumulative_notional: str,
    trade_id: str,
    *,
    document: dict[str, object] | None = None,
    fill_notional: str = "10000.00",
):
    contract = OnlyBrokerFeeContractDocumentLoader.load(document or _document())
    schedule = contract.schedules[0]
    market_pack = only_cn_a_share_market_fee_pack()
    day = OnlyTradingDay(date(2025, 7, 1))
    market_context = OnlyMarketFeeApplicabilityContext(
        day,
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("600000.XSHG"),
    )
    market_schedules = tuple(
        item
        for item in market_pack.schedules
        if item.matches(market_context) and any(rule.fee_type is OnlyFeeType.TRANSFER_FEE for rule in item.rules)
    )
    currency = OnlyCurrency("CNY", 2)
    account = OnlyAccountId("ACCOUNT-001")
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    scope = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_product_id="CN_A_SHARE_CASH",
        market="CN_A_SHARE",
        venue="XSHG",
        instrument_class="CASH",
        broker_id="broker-a",
        account_id=account,
        instrument_id=instrument,
        charge_currency=currency,
    )
    timestamp = OnlyTimestamp(datetime(2025, 7, 1, tzinfo=UTC))
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId("runtime-a"),
        account_id=account,
        cluster_id=OnlyClusterId("cluster-a"),
        order_id=OnlyOrderId("order-a"),
        instrument_id=instrument,
        market_product_id="CN_A_SHARE_CASH",
        market_product_version="2025.1",
        market_fee_pack=market_pack.identity,
        broker_fee_contract=contract.identity,
        applicability_scope=scope,
        order_fixed_schedules=(schedule.identity,),
        fill_effective_families=tuple(item.family_identity for item in market_schedules),
        charge_currency=currency,
        bound_at=timestamp,
    )
    policies = OnlyResolvedFeePolicySet.create(
        tuple(
            policy
            for resolved_schedule in (*market_schedules, schedule)
            for policy in resolved_schedule.resolved_policies()
        )
    )
    resolution = OnlyFeePolicyResolution.create(
        binding_fingerprint=binding.fingerprint,
        market_fee_pack=market_pack.identity,
        broker_fee_contract=contract.identity,
        scope_fingerprint=scope.fingerprint,
        resolved_schedules=tuple(item.identity for item in (*market_schedules, schedule)),
        policies=policies,
        trading_day=day,
    )
    cumulative = OnlyMoney(Decimal(cumulative_notional), currency)
    fill = OnlyFeeBasisValues(OnlyMoney(Decimal(fill_notional), currency), Decimal("1000"), Decimal(0))
    cumulative_basis = OnlyFeeBasisValues(cumulative, Decimal("1000"), Decimal(0))
    assessment = OnlyFeeEngine().assess_trade(
        OnlyTradeFeeAssessmentRequest(
            OnlyFeeSubject(
                binding.runtime_id,
                binding.account_id,
                binding.cluster_id,
                binding.order_id,
                binding.instrument_id,
            ),
            OnlyTradeId(trade_id),
            fill,
            cumulative_basis,
            day,
            None,
            OnlyLocalFeeFinality.MODEL_CONFIRMED,
            binding,
            resolution,
        )
    )
    return assessment, binding, cumulative, timestamp


def _commission_increments(
    cumulative_notionals: tuple[str, ...], *, document: dict[str, object]
) -> tuple[Decimal, ...]:
    authority = OnlyOrderFeeAccrualAuthority()
    state = None
    previous = Decimal(0)
    increments = []
    for index, cumulative_text in enumerate(cumulative_notionals, start=1):
        cumulative = Decimal(cumulative_text)
        assessment, binding, cumulative_money, timestamp = _commission_assessment(
            cumulative_text,
            f"matrix-trade-{index}",
            document=document,
            fill_notional=str(cumulative - previous),
        )
        state, application = authority.apply(
            state,
            assessment,
            cumulative_fill_quantity=OnlyQuantity(Decimal(index * 1000), 0),
            cumulative_fill_notional=cumulative_money,
            updated_at=timestamp,
            order_fixed_policy_fingerprint=binding.fingerprint,
        )
        commission = next(
            item for item in application.components if item.identity.fee_type is OnlyFeeType.BROKER_COMMISSION
        )
        increments.append(commission.amount.amount)
        previous = cumulative
    return tuple(increments)


def test_minimum_commission_reference_matrix() -> None:
    payload = json.loads(Path("tests/reference_data/cn_a_share_fee_vectors.json").read_text(encoding="utf-8"))
    for vector in payload["broker_commission_vectors"]:
        document = _document()
        document["schedules"][0]["rules"][0]["rate"] = vector["rate"]
        document["schedules"][0]["rules"][0]["minimum"] = vector["minimum"]
        expected = tuple(Decimal(item) for item in vector["expected_increments"])
        assert _commission_increments(tuple(vector["cumulative_notionals"]), document=document) == expected, vector[
            "vector_id"
        ]


def test_production_components_reconcile_broker_commission_difference_only() -> None:
    assessment, _, _, timestamp = _commission_assessment("10000.00", "reconciliation-trade")
    local = tuple(
        OnlyLocalFeeReconciliationComponent(
            OnlyFeeReconciliationComponentIdentity(
                component.identity.fee_type,
                component.identity.authority,
                component.identity.economic_direction,
                component.identity.rule_id,
            ),
            component.target_amount,
        )
        for component in assessment.components
    )
    external = tuple(
        OnlyExternalFeeComponent.create(
            component.component_identity,
            OnlyMoney(
                component.amount.amount
                + (Decimal("0.50") if component.component_identity.fee_type is OnlyFeeType.BROKER_COMMISSION else 0),
                component.amount.currency,
            ),
        )
        for component in local
    )
    evidence = OnlyExternalFeeEvidence.create(
        broker_id="broker-a",
        account_id=assessment.subject.account_id,
        scope=OnlyExternalFeeEvidenceScope.trade(OnlyTradeId("reconciliation-trade")),
        mode=OnlyExternalFeeEvidenceMode.DETAILED,
        external_reference="broker-a-trade-fees",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=OnlyMoney(
            sum((component.amount.amount for component in external), Decimal(0)), local[0].amount.currency
        ),
        reported_components=external,
        effective_at=timestamp,
        received_at=timestamp,
    )
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            local,
            (),
            None,
            only_standard_fee_reconciliation_policy(local[0].amount.currency),
        )
    )
    assert decision.status is OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT
    assert len(decision.adjustments) == 1
    assert decision.adjustments[0].component_identity.fee_type is OnlyFeeType.BROKER_COMMISSION
    assert decision.adjustments[0].amount.amount == Decimal("0.50")
    transfer = next(
        row for row in decision.component_reconciliations if row.component_identity.fee_type is OnlyFeeType.TRANSFER_FEE
    )
    assert transfer.difference.amount == Decimal(0)


def _run_three_fill_product(*, restore_between: bool):
    authority = OnlyOrderFeeAccrualAuthority()
    state = None
    increments = []
    applications = []
    for index, cumulative in enumerate(("10000.00", "20000.00", "30000.00"), start=1):
        assessment, binding, cumulative_money, timestamp = _commission_assessment(cumulative, f"trade-{index}")
        state, application = authority.apply(
            state,
            assessment,
            cumulative_fill_quantity=OnlyQuantity(Decimal(index * 1000), 0),
            cumulative_fill_notional=cumulative_money,
            updated_at=timestamp,
            order_fixed_policy_fingerprint=binding.fingerprint,
        )
        component_amounts = {item.identity.fee_type: item.amount.amount for item in application.components}
        increments.append(component_amounts[OnlyFeeType.BROKER_COMMISSION])
        assert component_amounts[OnlyFeeType.TRANSFER_FEE] == Decimal("0.10")
        applications.append(application)
        if restore_between and index < 3:
            state = OnlyOrderFeeAccrualState.from_json(state.to_json())
    assert state is not None
    return state, tuple(applications), tuple(increments)


@pytest.mark.recovery
def test_minimum_commission_multifill_a_b_c_recovery_matches_uninterrupted() -> None:
    state, applications, increments = _run_three_fill_product(restore_between=True)
    assert increments == (Decimal("5.00"), Decimal("1.00"), Decimal("3.00"))
    assert state.cumulative_charges.amount == Decimal("9.30")
    baseline_state, baseline_applications, baseline_increments = _run_three_fill_product(restore_between=False)
    assert state == baseline_state
    assert applications == baseline_applications
    assert increments == baseline_increments

    duplicate, binding, cumulative_money, timestamp = _commission_assessment("30000.00", "trade-3")
    with pytest.raises(ValueError, match="FEE_APPLICATION_DUPLICATE_TRADE"):
        OnlyOrderFeeAccrualAuthority().apply(
            state,
            duplicate,
            cumulative_fill_quantity=OnlyQuantity(Decimal("3000"), 0),
            cumulative_fill_notional=cumulative_money,
            updated_at=timestamp,
            order_fixed_policy_fingerprint=binding.fingerprint,
        )
