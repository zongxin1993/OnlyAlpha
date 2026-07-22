"""The sole deterministic resolver for market, broker and reported fees."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.models import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeAuthority,
    OnlyFeeBreakdown,
    OnlyFeeCalculationRequest,
    OnlyFeeComponent,
    OnlyFeeConfigurationMode,
    OnlyFeeInstruction,
    OnlyFeeStatus,
    OnlyFeeType,
)
from onlyalpha.fee.schedules import OnlyBrokerFeeSchedule, OnlyMarketFeeSchedule


@dataclass(frozen=True, slots=True)
class OnlyFeeEstimate:
    expected_fee: OnlyFeeBreakdown
    maximum_fee: OnlyFeeBreakdown
    reservation_fee: OnlyMoney


class OnlyFeeEngine:
    """Combines fee sources once; it never reads Runtime-managed state."""

    def estimate(
        self,
        request: OnlyFeeCalculationRequest,
        *,
        market_schedule: OnlyMarketFeeSchedule | None,
        broker_schedule: OnlyBrokerFeeSchedule | None,
        market_mode: OnlyFeeConfigurationMode,
        broker_mode: OnlyFeeConfigurationMode,
        safety_buffer: Decimal = Decimal(0),
    ) -> OnlyFeeEstimate:
        breakdown = self._model_breakdown(
            request, market_schedule, broker_schedule, market_mode, broker_mode, OnlyFeeStatus.ESTIMATED
        )
        if safety_buffer < 0:
            raise ValueError("fee safety buffer cannot be negative")
        reservation = OnlyMoney(breakdown.total.amount + safety_buffer, request.currency)
        return OnlyFeeEstimate(breakdown, breakdown, reservation)

    def resolve_trade_fee(
        self,
        request: OnlyFeeCalculationRequest,
        *,
        runtime_mode: OnlyRuntimeMode,
        market_schedule: OnlyMarketFeeSchedule | None,
        broker_schedule: OnlyBrokerFeeSchedule | None,
        market_mode: OnlyFeeConfigurationMode,
        broker_mode: OnlyFeeConfigurationMode,
    ) -> OnlyFeeBreakdown:
        if runtime_mode in {OnlyRuntimeMode.BACKTEST, OnlyRuntimeMode.PAPER}:
            return self._model_breakdown(
                request, market_schedule, broker_schedule, market_mode, broker_mode, OnlyFeeStatus.CONFIRMED
            )
        if request.broker_fee_reporting_mode is OnlyBrokerFeeReportingMode.ALL_IN and request.reported_fee is not None:
            return self._reported_all_in(request, OnlyFeeStatus.CONFIRMED)
        if (
            request.broker_fee_reporting_mode is OnlyBrokerFeeReportingMode.DETAILED
            and request.reported_breakdown is not None
        ):
            return self._with_status(request.reported_breakdown, OnlyFeeStatus.CONFIRMED)
        if (
            request.broker_fee_reporting_mode is OnlyBrokerFeeReportingMode.COMMISSION_ONLY
            and request.reported_fee is not None
        ):
            market = self._model_breakdown(
                request, market_schedule, None, market_mode, OnlyFeeConfigurationMode.NONE, OnlyFeeStatus.CONFIRMED
            )
            reported = self._reported_all_in(request, OnlyFeeStatus.CONFIRMED)
            return self._breakdown(request, market.components + reported.components, OnlyFeeStatus.CONFIRMED)
        return self._model_breakdown(
            request, market_schedule, broker_schedule, market_mode, broker_mode, OnlyFeeStatus.PROVISIONAL
        )

    def instruction(
        self,
        request: OnlyFeeCalculationRequest,
        breakdown: OnlyFeeBreakdown,
        created_at: datetime,
        calculation_source: str,
    ) -> OnlyFeeInstruction:
        only_require_utc(created_at, "fee instruction created_at")
        key = f"fee:{request.runtime_id}:{request.trade_id}:{breakdown.status.value}"
        instruction_id = hashlib.sha256(key.encode()).hexdigest()
        return OnlyFeeInstruction(
            instruction_id,
            request.runtime_id,
            request.cluster_id,
            request.account_id,
            request.order_id,
            request.trade_id,
            breakdown,
            calculation_source,
            created_at,
            key,
        )

    def _model_breakdown(
        self,
        request: OnlyFeeCalculationRequest,
        market_schedule: OnlyMarketFeeSchedule | None,
        broker_schedule: OnlyBrokerFeeSchedule | None,
        market_mode: OnlyFeeConfigurationMode,
        broker_mode: OnlyFeeConfigurationMode,
        status: OnlyFeeStatus,
    ) -> OnlyFeeBreakdown:
        components: tuple[OnlyFeeComponent, ...] = ()
        if market_mode is not OnlyFeeConfigurationMode.NONE:
            if market_schedule is None:
                raise ValueError("market fee configuration requires a resolved schedule")
            components += market_schedule.calculate(
                notional=request.notional.amount,
                quantity=request.quantity,
                side=request.side,
                offset=request.offset,
                liquidity_role=request.liquidity_role,
                status=status,
                currency=request.currency,
            )
        if broker_mode is not OnlyFeeConfigurationMode.NONE:
            if broker_mode is OnlyFeeConfigurationMode.REPORTED:
                # In live mode this is intentionally provisional until a report arrives.
                if request.reported_fee is not None:
                    components += self._reported_all_in(request, status).components
            else:
                if broker_schedule is None:
                    raise ValueError("broker fee configuration requires a resolved schedule")
                components += broker_schedule.calculate(
                    notional=request.notional.amount,
                    quantity=request.quantity,
                    side=request.side,
                    offset=request.offset,
                    liquidity_role=request.liquidity_role,
                    status=status,
                    currency=request.currency,
                )
        return self._breakdown(request, components, status)

    @staticmethod
    def _breakdown(
        request: OnlyFeeCalculationRequest, components: tuple[OnlyFeeComponent, ...], status: OnlyFeeStatus
    ) -> OnlyFeeBreakdown:
        return OnlyFeeBreakdown(
            request.currency,
            components,
            OnlyMoney(sum((x.amount.amount for x in components), Decimal(0)), request.currency),
            status,
        )

    @staticmethod
    def _reported_all_in(request: OnlyFeeCalculationRequest, status: OnlyFeeStatus) -> OnlyFeeBreakdown:
        if request.reported_fee is None:
            raise ValueError("reported all-in fee requires reported_fee")
        component = OnlyFeeComponent(
            fee_type=OnlyFeeType.OTHER,
            authority=OnlyFeeAuthority.BROKER,
            amount=request.reported_fee,
            status=status,
            source_id=request.broker_id,
            metadata={"reported": True, "reporting_mode": request.broker_fee_reporting_mode.value},
        )
        return OnlyFeeBreakdown(request.currency, (component,), request.reported_fee, status)

    @staticmethod
    def _with_status(breakdown: OnlyFeeBreakdown, status: OnlyFeeStatus) -> OnlyFeeBreakdown:
        components = tuple(
            OnlyFeeComponent(
                item.fee_type,
                item.authority,
                item.amount,
                status,
                item.source_id,
                item.schedule_id,
                item.schedule_version,
                item.effective_date,
                item.metadata,
            )
            for item in breakdown.components
        )
        return OnlyFeeBreakdown(breakdown.currency, components, breakdown.total, status)
