import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeContract,
    OnlyFeeBasisValues,
    OnlyFeeEngine,
    OnlyFeePolicyResolution,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyMarketFeePack,
    OnlyMarketFeePackRegistry,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
    OnlyResolvedFeePolicySet,
    OnlyTradeFeeAssessmentRequest,
)
from onlyalpha.fee.evidence import (
    OnlyExternalFeeComponent,
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyFeeReconciliationComponentIdentity,
)
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.packs.cn_a_share import (
    CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID,
    CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM,
    only_cn_a_share_production_fee_pack,
)
from onlyalpha.fee.reconciliation import (
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyFeeReconciliationStatus,
    OnlyLocalFeeReconciliationComponent,
)
from onlyalpha.fee.reconciliation_policy import only_standard_fee_reconciliation_policy
from onlyalpha.fee.schedules import OnlyMarketFeeApplicabilityContext, OnlyMarketFeeScheduleRegistry

CNY = OnlyCurrency("CNY", 2)
VECTORS = Path("tests/reference_data/cn_a_share_fee_vectors.json")


def _assessment(vector: dict[str, object]):
    pack = only_cn_a_share_production_fee_pack()
    day = OnlyTradingDay(date.fromisoformat(str(vector["trading_day"])))
    venue = str(vector["venue"])
    instrument = OnlyInstrumentId.parse(str(vector["instrument_identity"]))
    context = OnlyMarketFeeApplicabilityContext(
        day,
        str(vector["market_profile"]),
        str(vector["market"]),
        venue,
        str(vector["instrument_class"]),
        instrument,
    )
    schedules = tuple(item for item in pack.schedules if item.matches(context))
    side = OnlyOrderSide(str(vector["side"]))
    offset = OnlyOffset(str(vector["offset"]))
    applicable = tuple(item for item in schedules if any(rule.matches(side, offset, None) for rule in item.rules))
    policies = OnlyResolvedFeePolicySet.create(
        tuple(
            policy
            for schedule in applicable
            for policy in schedule.resolved_policies()
            if policy.rule.matches(side, offset, None)
        )
    )
    account = OnlyAccountId("reference-account")
    scope = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_profile_id="CN_A_SHARE_CASH",
        market="CN_A_SHARE",
        venue=venue,
        instrument_class="CASH",
        broker_id="reference-broker",
        account_id=account,
        instrument_id=instrument,
        charge_currency=CNY,
    )
    broker = OnlyBrokerFeeContract.create(
        contract_id="REFERENCE_ZERO_BROKER_FEES",
        contract_version="1",
        broker_id="reference-broker",
        account_scope=OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, account),
    )
    timestamp = OnlyTimestamp(datetime.combine(day.value, datetime.min.time(), tzinfo=UTC))
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId("reference-runtime"),
        account_id=account,
        cluster_id=OnlyClusterId("reference-cluster"),
        order_id=OnlyOrderId(str(vector["vector_id"])),
        instrument_id=instrument,
        market_profile_id="CN_A_SHARE_CASH",
        market_profile_version="2025.1",
        market_fee_pack=pack.identity,
        broker_fee_contract=broker.identity,
        applicability_scope=scope,
        order_fixed_schedules=(),
        fill_effective_families=tuple(item.family_identity for item in applicable),
        charge_currency=CNY,
        bound_at=timestamp,
    )
    resolution = OnlyFeePolicyResolution.create(
        binding_fingerprint=binding.fingerprint,
        market_fee_pack=pack.identity,
        broker_fee_contract=broker.identity,
        scope_fingerprint=scope.fingerprint,
        resolved_schedules=tuple(item.identity for item in applicable),
        policies=policies,
        trading_day=day,
    )
    notional = Decimal(str(vector["notional"]))
    quantity = Decimal(str(vector["quantity"]))
    basis = OnlyFeeBasisValues(OnlyMoney(notional, CNY), quantity, Decimal(0))
    subject = OnlyFeeSubject(
        binding.runtime_id,
        binding.account_id,
        binding.cluster_id,
        binding.order_id,
        binding.instrument_id,
    )
    return OnlyFeeEngine().assess_trade(
        OnlyTradeFeeAssessmentRequest(
            subject,
            OnlyTradeId(f"trade-{vector['vector_id']}"),
            basis,
            basis,
            day,
            None,
            OnlyLocalFeeFinality.MODEL_CONFIRMED,
            binding,
            resolution,
        )
    )


def test_pack_identity_sources_scope_and_fingerprint_are_stable() -> None:
    first = only_cn_a_share_production_fee_pack()
    second = only_cn_a_share_production_fee_pack()
    assert first == second
    assert first.pack_id == "CN_A_SHARE_PRODUCTION_MARKET_FEES"
    assert first.pack_version == "2025.06.30"
    assert first.compatible_market_profiles == ("CN_A_SHARE_CASH",)
    assert len(first.schedules) == 6
    assert all(item.currency == CNY for item in first.schedules)
    assert all(item.source in CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID for item in first.schedules)
    assert all("1970" not in item.effective_from.isoformat() for item in first.schedules)
    assert all("CURRENT" not in item.schedule_id and "LATEST" not in item.schedule_id for item in first.schedules)
    first.validate_compatibility("CN_A_SHARE_CASH")
    with pytest.raises(ValueError, match="MARKET_FEE_PACK_PROFILE_INCOMPATIBLE"):
        first.validate_compatibility("GENERIC_T0_CASH")


def test_venue_and_coverage_resolution_fail_closed() -> None:
    pack = only_cn_a_share_production_fee_pack()
    registry = OnlyMarketFeeScheduleRegistry()
    for schedule in reversed(pack.schedules):
        registry.register(schedule)
    sse_transfer = next(item for item in pack.schedules if item.schedule_id == "CN_A_SHARE_SSE_TRANSFER_FEE")
    before = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(date(2025, 6, 29)),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    with pytest.raises(ValueError, match="FEE_SCHEDULE_NOT_FOUND"):
        registry.resolve_family(sse_transfer.family_identity, before)
    on_boundary = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    assert registry.resolve_family(sse_transfer.family_identity, on_boundary) == sse_transfer
    after_boundary = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(date(2025, 7, 1)),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    assert registry.resolve_family(sse_transfer.family_identity, after_boundary) == sse_transfer
    assert not any(item.venue == "XSHE" and item.matches_scope(on_boundary) for item in pack.schedules)
    wrong_venue = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XBEI",
        "CASH",
        OnlyInstrumentId.parse("TEST.XBEI"),
    )
    assert not any(item.matches(wrong_venue) for item in pack.schedules)


def test_official_stamp_duty_boundary_and_exact_historical_identity() -> None:
    pack = only_cn_a_share_production_fee_pack()
    versions = tuple(item for item in pack.schedules if item.schedule_id == "CN_A_SHARE_SSE_STAMP_DUTY")
    assert tuple(item.version for item in versions) == ("1", "2")
    registry = OnlyMarketFeeScheduleRegistry()
    for schedule in reversed(pack.schedules):
        registry.register(schedule)
    old, new = versions
    before = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(date(2023, 8, 27)),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    boundary = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(date(2023, 8, 28)),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    after = OnlyMarketFeeApplicabilityContext(
        OnlyTradingDay(date(2023, 8, 29)),
        "CN_A_SHARE_CASH",
        "CN_A_SHARE",
        "XSHG",
        "CASH",
        OnlyInstrumentId.parse("TEST.XSHG"),
    )
    assert registry.resolve_family(old.family_identity, before) == old
    assert registry.resolve_family(old.family_identity, boundary) == new
    assert registry.resolve_family(old.family_identity, after) == new
    assert registry.resolve_version(old.identity) == old


def test_pack_selection_and_input_order_never_mean_latest() -> None:
    first = only_cn_a_share_production_fee_pack()
    reordered = OnlyMarketFeePack.create(
        pack_id=first.pack_id,
        pack_version=first.pack_version,
        compatible_market_profiles=first.compatible_market_profiles,
        schedules=tuple(reversed(first.schedules)),
    )
    assert reordered.fingerprint == first.fingerprint
    second = OnlyMarketFeePack.create(
        pack_id=first.pack_id,
        pack_version="2026.01.01",
        compatible_market_profiles=first.compatible_market_profiles,
        schedules=first.schedules,
    )
    registry = OnlyMarketFeePackRegistry()
    registry.register(second)
    registry.register(first)
    assert registry.require(first.pack_id, first.pack_version) == first


def test_independent_reference_vectors_component_by_component() -> None:
    payload = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in payload["vectors"]:
        assessment = _assessment(vector)
        actual = {item.identity.fee_type.value: str(item.target_amount.amount) for item in assessment.components}
        schedules = {
            item.identity.fee_type.value: f"{item.identity.schedule_id}@{item.identity.schedule_version}"
            for item in assessment.components
        }
        rules = {item.identity.fee_type.value: item.identity.rule_id for item in assessment.components}
        assert actual == vector["expected_components"], vector["vector_id"]
        assert schedules == vector["expected_schedule_identities"], vector["vector_id"]
        assert rules == vector["expected_rule_identities"], vector["vector_id"]
        assert str(assessment.total_charges.amount) == vector["expected_total"], vector["vector_id"]
        assert {item.identity.source_id for item in assessment.components} <= set(vector["source_ids"])


def test_production_components_reconcile_with_normalized_external_evidence() -> None:
    vector = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"][1]
    assessment = _assessment(vector)
    local = []
    external = []
    for component in assessment.components:
        identity = OnlyFeeReconciliationComponentIdentity(
            component.identity.fee_type,
            component.identity.authority,
            component.identity.economic_direction,
            component.identity.source_id,
        )
        local.append(OnlyLocalFeeReconciliationComponent(identity, component.target_amount))
        external.append(OnlyExternalFeeComponent.create(identity, component.target_amount))
    timestamp = OnlyTimestamp(datetime(2025, 6, 30, tzinfo=UTC))
    evidence = OnlyExternalFeeEvidence.create(
        broker_id="reference-broker",
        account_id=assessment.subject.account_id,
        scope=OnlyExternalFeeEvidenceScope.trade(assessment.trade_id),
        mode=OnlyExternalFeeEvidenceMode.DETAILED,
        external_reference="normalized-reference-evidence",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=assessment.total_charges,
        reported_components=tuple(external),
        effective_at=timestamp,
        received_at=timestamp,
    )
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            tuple(local),
            (),
            None,
            only_standard_fee_reconciliation_policy(CNY),
        )
    )
    assert decision.status is OnlyFeeReconciliationStatus.MATCHED
    assert decision.adjustments == ()
