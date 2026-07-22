"""Compiled market rules and the sole Runtime market-rule entry point."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from onlyalpha.domain.enums import OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTradingDay, only_require_utc
from onlyalpha.market.models import (
    OnlyInstrumentReferenceSnapshot,
    OnlyLiquidityModel,
    OnlyMarginModel,
    OnlyMarketPositionMode,
    OnlyMatchingModel,
    OnlyPositionAccountingModel,
    OnlyPositionEffect,
    OnlyPriceRule,
    OnlyQuantityRule,
    OnlySettlementContext,
    OnlySettlementModel,
    OnlyShortSellingRule,
    OnlySlippageModel,
    OnlyTradingDayAdvancer,
    OnlyTradingSessionModel,
)
from onlyalpha.market.registry import OnlyMarketProfileRegistry, OnlyMarketProfileRequest, OnlyResolvedMarketProfile


class OnlyMarketRuleStage(StrEnum):
    PRE_TRADE = "PRE_TRADE"
    MATCH_TIME = "MATCH_TIME"
    TRADE_APPLICATION = "TRADE_APPLICATION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    FEE = "FEE"


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketRuleIdentity:
    profile_id: str
    profile_version: str
    trading_day: date
    runtime_mode: OnlyRuntimeMode
    instrument_id: str
    venue: str
    reference_fingerprint: str
    resolved_profile_fingerprint: str
    compiled_rules_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketRules:
    """Immutable executable projection; it intentionally contains no Profile."""

    identity: OnlyCompiledMarketRuleIdentity
    session_policy: OnlyTradingSessionModel
    price_policy: OnlyPriceRule
    quantity_policy: OnlyQuantityRule
    position_policy: OnlyPositionAccountingModel
    short_policy: OnlyShortSellingRule
    settlement_policy: OnlySettlementModel
    margin_policy: OnlyMarginModel | None
    market_fee_schedule_id: str
    liquidity_policy: OnlyLiquidityModel
    slippage_policy: OnlySlippageModel
    matching_policy: OnlyMatchingModel


@dataclass(frozen=True, slots=True)
class OnlyMarketRuleCompilationContext:
    resolved_profile: OnlyResolvedMarketProfile
    reference: OnlyInstrumentReferenceSnapshot
    trading_day: OnlyTradingDay
    runtime_mode: OnlyRuntimeMode


class OnlyMarketRuleCompiler:
    """Compile configuration Profiles into deterministic Runtime policies."""

    def compile(self, context: OnlyMarketRuleCompilationContext) -> OnlyCompiledMarketRules:
        resolved = context.resolved_profile
        profile = resolved.profile
        reference = context.reference
        if reference.market_profile_id is not profile.profile_id:
            raise ValueError("instrument reference market profile differs from resolved profile")
        if reference.asset_class not in profile.asset_classes:
            raise ValueError("instrument asset class is unsupported by resolved market profile")
        if reference.venue != str(reference.venue):  # pragma: no cover - defensive normalization guard
            raise ValueError("instrument reference venue must be stable text")
        payload = {
            "resolved": resolved.resolved_rules_fingerprint,
            "reference": reference.content_fingerprint,
            "instrument": reference.instrument_id,
            "venue": reference.venue,
            "trading_day": context.trading_day.value.isoformat(),
            "runtime_mode": context.runtime_mode.value,
            "rules": _normalize(
                {
                    "session": asdict(profile.session_model),
                    "price": asdict(profile.price_rule),
                    "quantity": asdict(profile.quantity_rule),
                    "position": asdict(profile.position_model),
                    "short": asdict(profile.short_selling_rule),
                    "settlement": asdict(profile.settlement_model),
                    "margin": None if profile.margin_model is None else asdict(profile.margin_model),
                    "market_fee_schedule_id": profile.market_fee_schedule_id,
                    "liquidity": asdict(profile.liquidity_model),
                    "slippage": asdict(profile.slippage_model),
                    "matching": asdict(profile.matching_model),
                }
            ),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identity = OnlyCompiledMarketRuleIdentity(
            profile_id=profile.profile_id.value,
            profile_version=resolved.resolved_version,
            trading_day=context.trading_day.value,
            runtime_mode=context.runtime_mode,
            instrument_id=reference.instrument_id,
            venue=reference.venue,
            reference_fingerprint=reference.content_fingerprint,
            resolved_profile_fingerprint=resolved.resolved_rules_fingerprint,
            compiled_rules_fingerprint=fingerprint,
        )
        return OnlyCompiledMarketRules(
            identity,
            profile.session_model,
            profile.price_rule,
            profile.quantity_rule,
            profile.position_model,
            profile.short_selling_rule,
            profile.settlement_model,
            profile.margin_model,
            profile.market_fee_schedule_id,
            profile.liquidity_model,
            profile.slippage_model,
            profile.matching_model,
        )


@dataclass(frozen=True, slots=True)
class OnlyPreTradeMarketContext:
    instrument_id: str
    side: OnlyOrderSide
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    trading_day: OnlyTradingDay
    available_quantity: Decimal = Decimal(0)
    available_cash: Decimal = Decimal(0)
    available_margin: Decimal = Decimal(0)
    previous_close: Decimal | None = None
    position_effect: OnlyPositionEffect = OnlyPositionEffect.AUTO

    def __post_init__(self) -> None:
        only_require_utc(self.timestamp, "pre-trade timestamp")


@dataclass(frozen=True, slots=True)
class OnlyMarketOrderDecision:
    accepted: bool
    reason_code: str | None
    rule_code: str
    normalized_price: Decimal
    normalized_quantity: Decimal
    position_effect: OnlyPositionEffect
    required_cash: Decimal
    required_position: Decimal
    required_margin: Decimal
    compiled_identity: OnlyCompiledMarketRuleIdentity
    details: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class OnlyMatchTimeMarketContext:
    instrument_id: str
    side: OnlyOrderSide
    order_quantity: Decimal
    remaining_quantity: Decimal
    timestamp: datetime
    trading_day: OnlyTradingDay
    reference_price: Decimal
    bar_volume: Decimal | None = None
    consumed_liquidity: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class OnlyMarketMatchDecision:
    matched: bool
    unfilled_reason: str | None
    reference_price: Decimal
    fill_price: Decimal | None
    fill_quantity: Decimal
    remaining_liquidity: Decimal | None
    compiled_identity: OnlyCompiledMarketRuleIdentity


@dataclass(frozen=True, slots=True)
class OnlyPositionInstruction:
    instrument_id: str
    position_side: str
    position_effect: OnlyPositionEffect
    quantity: Decimal
    price: Decimal
    settlement_bucket: str
    source_order_id: str
    source_trade_id: str


@dataclass(frozen=True, slots=True)
class OnlySettlementRuntimeInstruction:
    instruction_id: str
    instrument_id: str
    source_trade_id: str
    asset_quantity: Decimal
    cash_amount: Decimal
    asset_available_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
    account_id: str = ""
    source_order_id: str = ""


@dataclass(frozen=True, slots=True)
class OnlyMarginInstruction:
    action: str
    account_id: str
    instrument_id: str
    currency: str
    amount: Decimal
    maintenance_required: Decimal
    source_order_id: str
    source_trade_id: str


@dataclass(frozen=True, slots=True)
class OnlyCashInstruction:
    currency: str
    amount: Decimal
    available_on: OnlyTradingDay
    settle_notional: bool = True


@dataclass(frozen=True, slots=True)
class OnlyTradeApplicationRequest:
    instrument_id: str
    order_id: str
    trade_id: str
    account_id: str
    side: OnlyOrderSide
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    trading_day: OnlyTradingDay
    position_effect: OnlyPositionEffect = OnlyPositionEffect.AUTO


@dataclass(frozen=True, slots=True)
class OnlyTradeApplicationInstruction:
    position_instruction: OnlyPositionInstruction
    settlement_instruction: OnlySettlementRuntimeInstruction
    margin_instruction: OnlyMarginInstruction | None
    cash_instruction: OnlyCashInstruction
    compiled_identity: OnlyCompiledMarketRuleIdentity


class OnlyPreTradeMarketRulePort(Protocol):
    def position_mode(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyMarketPositionMode: ...

    def evaluate_pre_trade(self, context: OnlyPreTradeMarketContext) -> OnlyMarketOrderDecision: ...


class OnlyMatchTimeMarketRulePort(Protocol):
    def evaluate_match_time(self, context: OnlyMatchTimeMarketContext) -> OnlyMarketMatchDecision: ...


class OnlyTradeInstructionPort(Protocol):
    def build_trade_instruction(self, request: OnlyTradeApplicationRequest) -> OnlyTradeApplicationInstruction: ...

    def compiled_rules(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyCompiledMarketRules: ...


OnlyReferenceProvider = Callable[[str, OnlyTradingDay], OnlyInstrumentReferenceSnapshot]


class OnlyMarketRuleEngine(OnlyPreTradeMarketRulePort, OnlyMatchTimeMarketRulePort, OnlyTradeInstructionPort):
    """Controlled Runtime service. Business components never receive Profiles."""

    def __init__(
        self,
        *,
        registry: OnlyMarketProfileRegistry,
        compiler: OnlyMarketRuleCompiler,
        request: OnlyMarketProfileRequest,
        runtime_mode: OnlyRuntimeMode,
        references: Mapping[str, OnlyInstrumentReferenceSnapshot] | OnlyReferenceProvider,
        advance_trading_day: OnlyTradingDayAdvancer,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._request = request
        self._runtime_mode = runtime_mode
        self._references = references
        self._advance_trading_day = advance_trading_day
        self._cache: dict[tuple[str, date, str], OnlyCompiledMarketRules] = {}
        self._decisions: list[OnlyMarketOrderDecision | OnlyMarketMatchDecision] = []

    @property
    def decisions(self) -> tuple[OnlyMarketOrderDecision | OnlyMarketMatchDecision, ...]:
        return tuple(self._decisions)

    @property
    def compiled_identities(self) -> tuple[OnlyCompiledMarketRuleIdentity, ...]:
        """Stable public query projection for collectors and artifacts."""
        return tuple(item.identity for _, item in sorted(self._cache.items(), key=lambda pair: pair[0]))

    def compiled_rules(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyCompiledMarketRules:
        reference = self._reference(instrument_id, trading_day)
        key = (instrument_id, trading_day.value, reference.content_fingerprint)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        resolved = self._registry.resolve(
            self._request,
            effective_on=trading_day.value,
            reference_source=reference.source,
            reference_version=reference.source_version,
            reference_fingerprint=reference.content_fingerprint,
        )
        compiled = self._compiler.compile(
            OnlyMarketRuleCompilationContext(resolved, reference, trading_day, self._runtime_mode)
        )
        self._cache[key] = compiled
        return compiled

    def evaluate_pre_trade(self, context: OnlyPreTradeMarketContext) -> OnlyMarketOrderDecision:
        rules = self.compiled_rules(context.instrument_id, context.trading_day)
        reference = self._reference(context.instrument_id, context.trading_day)
        reason: str | None = None
        session = rules.session_policy.state_at(context.timestamp.astimezone(ZoneInfo(rules.session_policy.timezone)))
        if not session.allows_orders:
            reason = f"SESSION_{session.phase.value}"
        elif reference.status != "ACTIVE" or reference.suspended:
            reason = "INSTRUMENT_NOT_TRADABLE"
        else:
            reason = rules.quantity_policy.validate(
                reference,
                context.side,
                context.quantity,
                context.price,
                context.available_quantity,
            )
        if reason is None and (context.price <= 0 or context.price % reference.tick_size != 0):
            reason = "INVALID_PRICE_TICK"
        limits = rules.price_policy.price_limits(context.previous_close)
        if reason is None and limits is not None and not limits[0] <= context.price <= limits[1]:
            reason = "OUTSIDE_DAILY_PRICE_LIMIT"
        effect = self._position_effect(rules, context)
        required_position = (
            context.quantity
            if context.side is OnlyOrderSide.SELL and effect is not OnlyPositionEffect.OPEN
            else Decimal(0)
        )
        if reason is None and required_position > context.available_quantity:
            reason = (
                "ASSET_NOT_AVAILABLE_T1" if context.available_quantity < context.quantity else "INSUFFICIENT_POSITION"
            )
        notional = context.price * context.quantity * reference.contract_multiplier
        required_cash = (
            notional if context.side is OnlyOrderSide.BUY and effect is not OnlyPositionEffect.CLOSE else Decimal(0)
        )
        required_margin = Decimal(0)
        if rules.margin_policy is not None and effect is OnlyPositionEffect.OPEN:
            required_margin = rules.margin_policy.requirement(
                context.price, context.quantity, reference.contract_multiplier
            ).initial_margin
            if reason is None and required_margin > context.available_margin:
                reason = "INSUFFICIENT_MARGIN"
        if reason is None and required_cash > context.available_cash:
            reason = "INSUFFICIENT_CASH"
        decision = OnlyMarketOrderDecision(
            accepted=reason is None,
            reason_code=reason,
            rule_code="PRE_TRADE_MARKET_RULES",
            normalized_price=context.price,
            normalized_quantity=context.quantity,
            position_effect=effect,
            required_cash=required_cash,
            required_position=required_position,
            required_margin=required_margin,
            compiled_identity=rules.identity,
        )
        self._decisions.append(decision)
        return decision

    def position_mode(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyMarketPositionMode:
        """Expose the compiled position identity without leaking the compiled rule container."""

        return self.compiled_rules(instrument_id, trading_day).position_policy.mode

    def evaluate_match_time(self, context: OnlyMatchTimeMarketContext) -> OnlyMarketMatchDecision:
        rules = self.compiled_rules(context.instrument_id, context.trading_day)
        reference = self._reference(context.instrument_id, context.trading_day)
        capacity = rules.liquidity_policy.capacity(context.bar_volume, context.consumed_liquidity)
        quantity = context.remaining_quantity if capacity is None else min(context.remaining_quantity, capacity)
        price = rules.slippage_policy.apply(context.reference_price, context.side, reference.tick_size)
        reason = None
        if quantity <= 0:
            reason = "LIQUIDITY_EXHAUSTED"
        elif price <= 0 or price % reference.tick_size != 0:
            reason = "FINAL_PRICE_TICK_INVALID"
        decision = OnlyMarketMatchDecision(
            matched=reason is None,
            unfilled_reason=reason,
            reference_price=context.reference_price,
            fill_price=None if reason is not None else price,
            fill_quantity=Decimal(0) if reason is not None else quantity,
            remaining_liquidity=None if capacity is None else max(capacity - quantity, Decimal(0)),
            compiled_identity=rules.identity,
        )
        self._decisions.append(decision)
        return decision

    def build_trade_instruction(self, request: OnlyTradeApplicationRequest) -> OnlyTradeApplicationInstruction:
        rules = self.compiled_rules(request.instrument_id, request.trading_day)
        reference = self._reference(request.instrument_id, request.trading_day)
        effect = request.position_effect
        if effect is OnlyPositionEffect.AUTO:
            effect = OnlyPositionEffect.OPEN if request.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
        notional = request.price * request.quantity * reference.contract_multiplier
        settlement = rules.settlement_policy.on_execution(
            OnlySettlementContext(
                request.trade_id,
                request.account_id,
                request.instrument_id,
                request.side,
                request.quantity,
                notional,
                request.timestamp,
                request.trading_day,
            ),
            self._advance_trading_day,
        )
        margin = None
        if rules.margin_policy is not None:
            requirement = rules.margin_policy.requirement(
                request.price, request.quantity, reference.contract_multiplier
            )
            margin = OnlyMarginInstruction(
                "OCCUPY" if effect is OnlyPositionEffect.OPEN else "RELEASE",
                request.account_id,
                request.instrument_id,
                reference.currency,
                requirement.initial_margin,
                requirement.maintenance_margin,
                request.order_id,
                request.trade_id,
            )
        position_side = (
            "SHORT"
            if (request.side is OnlyOrderSide.SELL and effect is OnlyPositionEffect.OPEN)
            or (request.side is OnlyOrderSide.BUY and effect is not OnlyPositionEffect.OPEN)
            else "LONG"
        )
        position = OnlyPositionInstruction(
            request.instrument_id,
            position_side,
            effect,
            request.quantity,
            request.price,
            "AVAILABLE" if settlement.asset_available_day == request.trading_day else "PENDING",
            request.order_id,
            request.trade_id,
        )
        settlement_instruction = OnlySettlementRuntimeInstruction(
            settlement.instruction_id,
            request.instrument_id,
            request.trade_id,
            settlement.asset_quantity,
            settlement.cash_amount,
            settlement.asset_available_day,
            settlement.cash_available_day,
            settlement.cash_available_day,
            settlement.legal_settlement_day,
            request.account_id,
            request.order_id,
        )
        settles_notional = rules.margin_policy is None
        cash_sign = Decimal(-1) if request.side is OnlyOrderSide.BUY else Decimal(1)
        return OnlyTradeApplicationInstruction(
            position,
            settlement_instruction,
            margin,
            OnlyCashInstruction(
                reference.currency,
                cash_sign * notional if settles_notional else Decimal(0),
                settlement.cash_available_day,
                settles_notional,
            ),
            rules.identity,
        )

    def _reference(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyInstrumentReferenceSnapshot:
        if callable(self._references):
            return self._references(instrument_id, trading_day)
        try:
            return self._references[instrument_id]
        except KeyError as exc:
            raise KeyError(f"market reference not registered: {instrument_id}") from exc

    @staticmethod
    def _position_effect(rules: OnlyCompiledMarketRules, context: OnlyPreTradeMarketContext) -> OnlyPositionEffect:
        if context.position_effect is not OnlyPositionEffect.AUTO:
            return context.position_effect
        if rules.position_policy.mode is OnlyMarketPositionMode.LONG_ONLY:
            return OnlyPositionEffect.OPEN if context.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
        return OnlyPositionEffect.OPEN

    def build_order_margin_instruction(
        self,
        request: OnlyTradeApplicationRequest,
    ) -> OnlyMarginInstruction | None:
        """Build a submission-time reservation from the compiled margin policy."""

        rules = self.compiled_rules(request.instrument_id, request.trading_day)
        if rules.margin_policy is None or request.position_effect is not OnlyPositionEffect.OPEN:
            return None
        reference = self._reference(request.instrument_id, request.trading_day)
        requirement = rules.margin_policy.requirement(
            request.price,
            request.quantity,
            reference.contract_multiplier,
        )
        return OnlyMarginInstruction(
            "RESERVE",
            request.account_id,
            request.instrument_id,
            reference.currency,
            requirement.initial_margin,
            requirement.maintenance_margin,
            request.order_id,
            request.trade_id,
        )


def only_instrument_reference(
    instrument: OnlyInstrument,
    *,
    profile_id: object,
    source: str = "CONFIG",
    board: str | None = None,
    st_status: bool = False,
) -> OnlyInstrumentReferenceSnapshot:
    """Build the runtime reference projection from the canonical Instrument model."""

    from onlyalpha.market.models import OnlyMarketProfileId

    effective_from = instrument.effective_from or datetime(1970, 1, 1, tzinfo=UTC)
    fingerprint_payload = {
        "instrument": repr(instrument),
        "profile": str(profile_id),
        "board": board,
        "st": st_status,
    }
    fingerprint = hashlib.sha256(
        json.dumps(_normalize(fingerprint_payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return OnlyInstrumentReferenceSnapshot(
        instrument_id=str(instrument.instrument_id),
        asset_class=instrument.asset_class,
        venue=str(instrument.venue),
        market_profile_id=OnlyMarketProfileId(str(profile_id)),
        currency=instrument.settlement_currency.code,
        effective_from=effective_from,
        effective_to=instrument.effective_to,
        source=source,
        source_version=str(instrument.version),
        content_fingerprint=fingerprint,
        base_currency=None if instrument.base_currency is None else instrument.base_currency.code,
        quote_currency=instrument.quote_currency.code,
        settlement_currency=instrument.settlement_currency.code,
        status=instrument.status.value,
        price_precision=instrument.price_precision,
        quantity_precision=instrument.quantity_precision,
        tick_size=instrument.tick_size.value,
        quantity_step=instrument.step_size.value,
        minimum_quantity=None if instrument.minimum_quantity is None else instrument.minimum_quantity.value,
        maximum_quantity=None if instrument.maximum_quantity is None else instrument.maximum_quantity.value,
        minimum_notional=None if instrument.minimum_notional is None else instrument.minimum_notional.amount,
        maximum_notional=None if instrument.maximum_notional is None else instrument.maximum_notional.amount,
        lot_size=None if instrument.lot_size is None else instrument.lot_size.value,
        contract_multiplier=instrument.contract_multiplier.value,
        board=board,
        st_status=st_status,
        trading_calendar_id=None if instrument.trading_calendar_id is None else str(instrument.trading_calendar_id),
    )


def _normalize(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return value
