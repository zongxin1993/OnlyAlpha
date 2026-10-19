"""Actual Python Fee Engine/accrual versus native processes, common economic values only."""

from __future__ import annotations

import copy
import json
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def python_applications(fixture: dict[str, Any]) -> list[str]:
    from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide
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
        OnlyBrokerFeeAccountScope,
        OnlyBrokerFeeAccountScopeType,
        OnlyBrokerFeeContract,
        OnlyBrokerFeeSchedule,
        OnlyFeeAuthority,
        OnlyFeeBasisValues,
        OnlyFeeCalculationBasis,
        OnlyFeeCalculationPipeline,
        OnlyFeeCalculationScope,
        OnlyFeeEconomicDirection,
        OnlyFeeEngine,
        OnlyFeeFixedTerm,
        OnlyFeeFormula,
        OnlyFeePerUnitTerm,
        OnlyFeePolicyResolution,
        OnlyFeeRateTerm,
        OnlyFeeResolutionPolicy,
        OnlyFeeRoundingMode,
        OnlyFeeRoundingPolicy,
        OnlyFeeRule,
        OnlyFeeSubject,
        OnlyFeeType,
        OnlyLocalFeeFinality,
        OnlyMarketFeePack,
        OnlyMarketFeeSchedule,
        OnlyOrderFeeApplicabilityScopeIdentity,
        OnlyOrderFeePolicyBinding,
        OnlyResolvedFeePolicySet,
        OnlyTradeFeeAssessmentRequest,
    )
    from onlyalpha.fee.accrual import OnlyOrderFeeAccrualAuthority

    scope = fixture["subject"]
    currency = OnlyCurrency(scope["currency"]["code"], scope["currency"]["precision"])
    account = OnlyAccountId(scope["account"])
    account_scope = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, account)
    instrument = OnlyInstrumentId.parse(scope["instrument"])

    def rule(row: dict[str, Any]) -> OnlyFeeRule:
        terms = []
        for term in row["terms"]:
            amount = Decimal(term["amount"])
            terms.append(
                OnlyFeeFixedTerm(amount)
                if term["kind"] == "FIXED"
                else OnlyFeeRateTerm(OnlyFeeCalculationBasis(term["basis"]), amount)
                if term["kind"] == "RATE"
                else OnlyFeePerUnitTerm(OnlyFeeCalculationBasis(term["basis"]), amount)
            )
        return OnlyFeeRule(
            row["id"],
            OnlyFeeType(row["type"]),
            OnlyFeeAuthority(row["authority"]),
            OnlyFeeEconomicDirection(row["direction"]),
            OnlyFeeFormula(tuple(terms)),
            OnlyFeeCalculationScope(row["scope"]),
            OnlyFeeResolutionPolicy(row["resolution"]),
            None if row["minimum"] is None else Decimal(row["minimum"]),
            None if row["maximum"] is None else Decimal(row["maximum"]),
            None if row["side"] is None else OnlyOrderSide(row["side"]),
            None if row["offset"] is None else OnlyOffset(row["offset"]),
            None if row["liquidity"] is None else OnlyLiquiditySide(row["liquidity"]),
            OnlyFeeRoundingPolicy(Decimal(row["quantum"]), OnlyFeeRoundingMode(row["rounding"])),
            OnlyFeeCalculationPipeline(row["pipeline"]),
        )

    market_row, broker_row = fixture["catalog"]["schedules"]
    market = OnlyMarketFeeSchedule(
        market_row["family"],
        market_row["version"],
        date.fromordinal(market_row["from"]),
        None,
        currency,
        "common reference",
        tuple(rule(r) for r in market_row["rules"]),
        scope["market"],
        scope["venue"],
        scope["instrument_class"],
    )
    broker = OnlyBrokerFeeSchedule(
        broker_row["family"],
        broker_row["version"],
        date.fromordinal(broker_row["from"]),
        None,
        currency,
        "common reference",
        tuple(rule(r) for r in broker_row["rules"]),
        scope["broker"],
        account_scope,
    )
    pack = OnlyMarketFeePack.create(
        pack_id="market-pack", pack_version="1", compatible_market_products=("GENERIC_T0_CASH",), schedules=(market,)
    )
    contract = OnlyBrokerFeeContract.create(
        contract_id="contract",
        contract_version="1",
        broker_id=scope["broker"],
        account_scope=account_scope,
        schedules=(broker,),
    )
    applicability = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_product_id="GENERIC_T0_CASH",
        market=scope["market"],
        venue=scope["venue"],
        instrument_class=scope["instrument_class"],
        broker_id=scope["broker"],
        account_id=account,
        instrument_id=instrument,
        charge_currency=currency,
    )
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId(scope["runtime"]),
        account_id=account,
        cluster_id=OnlyClusterId(scope["cluster"]),
        order_id=OnlyOrderId(scope["order"]),
        instrument_id=instrument,
        market_product_id="GENERIC_T0_CASH",
        market_product_version="1",
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        applicability_scope=applicability,
        order_fixed_schedules=(market.identity, broker.identity),
        fill_effective_families=(),
        charge_currency=currency,
        bound_at=OnlyTimestamp.from_unix_nanos(0),
    )
    policies = OnlyResolvedFeePolicySet.create((*market.resolved_policies(), *broker.resolved_policies()))
    subject = OnlyFeeSubject(binding.runtime_id, account, binding.cluster_id, binding.order_id, instrument)
    before = None
    results = []
    for step in fixture["steps"]:
        day = OnlyTradingDay(date.fromordinal(step["day"]))
        resolution = OnlyFeePolicyResolution.create(
            binding_fingerprint=binding.fingerprint,
            market_fee_pack=pack.identity,
            broker_fee_contract=contract.identity,
            scope_fingerprint=applicability.fingerprint,
            resolved_schedules=(market.identity, broker.identity),
            policies=policies,
            trading_day=day,
        )

        def basis(values: dict[str, Any]) -> OnlyFeeBasisValues:
            return OnlyFeeBasisValues(
                OnlyMoney(Decimal(values["notional"]), currency),
                Decimal(values["quantity"]),
                Decimal(values["contracts"]),
            )

        assessment = OnlyFeeEngine().assess_trade(
            OnlyTradeFeeAssessmentRequest(
                subject,
                OnlyTradeId(step["trade"]),
                basis(step["fill"]),
                basis(step["cumulative"]),
                day,
                None,
                OnlyLocalFeeFinality.MODEL_CONFIRMED,
                binding,
                resolution,
            )
        )
        before, application = OnlyOrderFeeAccrualAuthority().apply(
            before,
            assessment,
            cumulative_fill_quantity=OnlyQuantity(Decimal(step["cumulative"]["quantity"]), 0),
            cumulative_fill_notional=OnlyMoney(Decimal(step["cumulative"]["notional"]), currency),
            updated_at=OnlyTimestamp.from_unix_nanos(step["time"]),
            order_fixed_policy_fingerprint=binding.fingerprint,
        )
        results.append(f"{application.total_charges.amount:.2f}")
    return results


def cases(root: Path = ROOT) -> list[tuple[dict[str, Any], list[str]]]:
    fixture = json.loads((root / "test-data/fee/common-v1.json").read_text())
    result = []
    for case in fixture["cases"]:
        selected = copy.deepcopy(fixture)
        selected["catalog"]["schedules"][1]["rules"][0]["scope"] = case["scope"]
        assert python_applications(selected) == case["expected"]
        result.append((selected, case["expected"]))
    return result


def compare_native(root: Path, executable: Path) -> None:
    def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        result = subprocess.run(
            [str(executable)], input=json.dumps(payload), text=True, capture_output=True, check=True
        )
        decoded: dict[str, Any] = json.loads(result.stdout)
        return decoded

    for fixture, expected in cases(root):
        full = invoke({"fixture": fixture})
        assert [r["charges"] for r in full["applications"]] == expected
        first = invoke({"fixture": fixture, "count": 1})
        resumed = invoke({"fixture": fixture, "checkpoint": first["checkpoint"], "offset": 1})
        assert [r["charges"] for r in first["applications"] + resumed["applications"]] == expected
        assert resumed["checkpoint"] == full["checkpoint"]
    print("FEE_PYTHON_NATIVE_REFERENCE: PASS", flush=True)
