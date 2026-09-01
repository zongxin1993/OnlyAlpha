"""Deterministic derivation of Funding market facts into Accounting facts."""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.account.enums import OnlyAccountEconomicCashflowType
from onlyalpha.account.models import OnlyAccountEconomicCashflow
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier
from onlyalpha.market.economics import OnlyCompiledFundingPolicy
from onlyalpha.position.enums import OnlyPositionSide
from onlyalpha.position.models import OnlyPositionSnapshot


def only_derive_funding_cashflow(
    *,
    runtime_id: OnlyRuntimeId,
    account_id: OnlyAccountId,
    position: OnlyPositionSnapshot,
    funding: OnlyFundingRateFact,
    valuation: OnlyReferencePriceFact,
    multiplier: OnlyMultiplier,
    currency: OnlyCurrency,
    policy: OnlyCompiledFundingPolicy,
) -> OnlyAccountEconomicCashflow:
    if position.key.instrument_id != funding.instrument_id or funding.instrument_id != valuation.instrument_id:
        raise ValueError("FUNDING_SCOPE_CONFLICT")
    if funding.funding_time != valuation.ts_event:
        raise ValueError("FUNDING_REFERENCE_BOUNDARY_CONFLICT")
    funding_nanos = OnlyTimestamp.from_datetime(funding.funding_time).unix_nanos
    interval_nanos = policy.interval_seconds * 1_000_000_000
    boundary_offset_nanos = policy.boundary_offset_seconds * 1_000_000_000
    if (funding_nanos - boundary_offset_nanos) % interval_nanos != 0:
        raise ValueError("FUNDING_INTERVAL_BOUNDARY_CONFLICT")
    if valuation.kind is not policy.valuation_price_kind:
        raise ValueError("FUNDING_REFERENCE_KIND_CONFLICT")
    notional = valuation.value.value * position.total_quantity.value * multiplier.value
    signed = notional * funding.rate
    long_pays = policy.long_pays_positive_rate
    payer = (
        position.position_side is OnlyPositionSide.LONG
        if long_pays
        else position.position_side is OnlyPositionSide.SHORT
    )
    amount = -signed if payer else signed
    quantum = Decimal(1).scaleb(-currency.precision)
    amount = amount.quantize(quantum, rounding=ROUND_HALF_EVEN)
    identity_payload = "\x1f".join(
        (
            str(runtime_id),
            str(account_id),
            funding.fact_id,
            str(position.position_id),
            position.position_side.value,
            str(position.total_quantity.value),
            valuation.fact_id,
            str(multiplier.value),
            currency.code,
            str(currency.precision),
            repr(policy.canonical_identity()),
        )
    )
    cashflow_id = f"FUND-{hashlib.sha256(identity_payload.encode()).hexdigest()}"
    return OnlyAccountEconomicCashflow(
        cashflow_id,
        runtime_id,
        account_id,
        OnlyAccountEconomicCashflowType.FUNDING,
        OnlyMoney(amount, currency),
        OnlyTimestamp.from_datetime(funding.funding_time),
        funding.fact_id,
        str(funding.instrument_id),
    )


__all__ = ["only_derive_funding_cashflow"]
