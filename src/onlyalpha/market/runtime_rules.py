"""Compiled market rules and the sole Runtime market-rule entry point."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType, OnlyRuntimeMode
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay, only_require_utc
from onlyalpha.market.ashare_rules import (
    only_compile_ashare_price_policy,
    only_compile_ashare_quantity_policy,
)
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyInstrumentReferenceSnapshot,
    OnlyLiquidityModel,
    OnlyMarginModel,
    OnlyMarketPositionMode,
    OnlyMarketRuleEvaluation,
    OnlyMarketRuleEvaluationStatus,
    OnlyMatchingModel,
    OnlyPositionAccountingModel,
    OnlyPositionEffect,
    OnlyPriceBandRoundingMode,
    OnlyPriceRule,
    OnlyQuantityRule,
    OnlySettlementModel,
    OnlyShortSellingRule,
    OnlySlippageModel,
    OnlyTradingDayAdvancer,
    OnlyTradingPhase,
    OnlyTradingSessionModel,
)
from onlyalpha.market.registry import OnlyMarketProfileRegistry, OnlyMarketProfileRequest, OnlyResolvedMarketProfile
from onlyalpha.reference import OnlyAshareInstrumentReference, OnlyAshareReferenceError
from onlyalpha.settlement.models import OnlySettlementSchedule, OnlySettlementScheduleRequest

_PRE_TRADE_RULE_ORDER = (
    "REFERENCE_COVERAGE",
    "REFERENCE_EFFECTIVE_RANGE",
    "EFFECTIVE_PROFILE_RESOLUTION",
    "TRADING_PHASE",
    "SUSPENSION",
    "INSTRUMENT_LIFECYCLE",
    "SUPPORTED_ORDER_TYPE",
    "SIDE_POSITION_EFFECT",
    "QUANTITY_POSITIVE",
    "BUY_SELL_MINIMUM",
    "QUANTITY_INCREMENT",
    "ODD_LOT_LIQUIDATION",
    "PRICE_POSITIVE",
    "PRICE_TICK_ALIGNMENT",
    "PREVIOUS_CLOSE_SEMANTICS",
    "DAILY_UPPER_LIMIT",
    "DAILY_LOWER_LIMIT",
    "SELLABLE_POSITION",
    "AVAILABLE_CASH",
    "DYNAMIC_PRICE_CAGE",
)


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
    price_policy: OnlyCompiledPriceBandPolicy
    quantity_policy: OnlyCompiledQuantityPolicy
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
        if profile.profile_id.value == "CN_A_SHARE_CASH":
            price_policy = only_compile_ashare_price_policy(
                profile_version=resolved.resolved_version,
                board=reference.board,
                st_status=reference.st_status,
                previous_close=reference.previous_close,
                tick_size=reference.tick_size,
            )
            quantity_policy = only_compile_ashare_quantity_policy(
                profile_version=resolved.resolved_version,
                board=reference.board,
                lot_size=reference.lot_size,
            )
        else:
            price_policy = _compile_generic_price_policy(profile.version, profile.price_rule, reference)
            quantity_policy = _compile_generic_quantity_policy(profile.quantity_rule, reference)
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
                    "price": asdict(price_policy),
                    "quantity": asdict(quantity_policy),
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
            price_policy,
            quantity_policy,
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
    unreserved_sellable_quantity: Decimal = Decimal(0)
    trade_available_cash: Decimal = Decimal(0)
    available_margin: Decimal = Decimal(0)
    position_effect: OnlyPositionEffect = OnlyPositionEffect.AUTO
    order_type: OnlyOrderType = OnlyOrderType.LIMIT

    def __post_init__(self) -> None:
        only_require_utc(self.timestamp, "pre-trade timestamp")


@dataclass(frozen=True, slots=True)
class OnlyMarketOrderDecision:
    accepted: bool
    reason_code: str | None
    evaluations: tuple[OnlyMarketRuleEvaluation, ...]
    trading_day: OnlyTradingDay
    trading_phase: OnlyTradingPhase
    timestamp: datetime
    side: OnlyOrderSide
    normalized_price: Decimal
    normalized_quantity: Decimal
    position_effect: OnlyPositionEffect
    required_cash: Decimal
    required_position: Decimal
    required_margin: Decimal
    previous_close: Decimal | None
    tick_size: Decimal
    daily_limit_rate: Decimal | None
    lower_limit: Decimal | None
    upper_limit: Decimal | None
    minimum_buy_quantity: Decimal
    buy_quantity_increment: Decimal
    sell_quantity_increment: Decimal
    dynamic_price_cage_status: OnlyMarketRuleEvaluationStatus
    compiled_identity: OnlyCompiledMarketRuleIdentity


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
class OnlyMarginInstruction:
    action: str
    account_id: str
    instrument_id: str
    currency: str
    amount: Decimal
    maintenance_required: Decimal
    source_order_id: str
    source_trade_id: str
    timestamp: OnlyTimestamp


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
    settlement_schedule: OnlySettlementSchedule
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
        reference_registry_fingerprint: str | None = None,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._request = request
        self._runtime_mode = runtime_mode
        self._references = references
        self._advance_trading_day = advance_trading_day
        self._reference_registry_fingerprint = reference_registry_fingerprint
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

    def capture_checkpoint(self) -> object:
        def identity_payload(identity: OnlyCompiledMarketRuleIdentity) -> dict[str, str]:
            return {
                "compiled_rules_fingerprint": identity.compiled_rules_fingerprint,
                "instrument_id": identity.instrument_id,
                "profile_id": identity.profile_id,
                "profile_version": identity.profile_version,
                "reference_fingerprint": identity.reference_fingerprint,
                "resolved_profile_fingerprint": identity.resolved_profile_fingerprint,
                "runtime_mode": identity.runtime_mode.value,
                "trading_day": identity.trading_day.isoformat(),
                "venue": identity.venue,
            }

        decisions: list[dict[str, object]] = []
        for item in self._decisions:
            if isinstance(item, OnlyMarketOrderDecision):
                decisions.append(
                    {
                        "accepted": item.accepted,
                        "compiled_identity": identity_payload(item.compiled_identity),
                        "daily_limit_rate": (None if item.daily_limit_rate is None else str(item.daily_limit_rate)),
                        "dynamic_price_cage_status": item.dynamic_price_cage_status.value,
                        "evaluations": [
                            {
                                "inputs": [list(pair) for pair in evaluation.inputs],
                                "reason_code": evaluation.reason_code,
                                "rule_code": evaluation.rule_code,
                                "status": evaluation.status.value,
                            }
                            for evaluation in item.evaluations
                        ],
                        "kind": "ORDER",
                        "lower_limit": None if item.lower_limit is None else str(item.lower_limit),
                        "minimum_buy_quantity": str(item.minimum_buy_quantity),
                        "normalized_price": str(item.normalized_price),
                        "normalized_quantity": str(item.normalized_quantity),
                        "position_effect": item.position_effect.value,
                        "previous_close": None if item.previous_close is None else str(item.previous_close),
                        "reason_code": item.reason_code,
                        "buy_quantity_increment": str(item.buy_quantity_increment),
                        "required_cash": str(item.required_cash),
                        "required_margin": str(item.required_margin),
                        "required_position": str(item.required_position),
                        "sell_quantity_increment": str(item.sell_quantity_increment),
                        "tick_size": str(item.tick_size),
                        "timestamp": item.timestamp.isoformat(),
                        "trading_day": item.trading_day.value.isoformat(),
                        "trading_phase": item.trading_phase.value,
                        "side": item.side.value,
                        "upper_limit": None if item.upper_limit is None else str(item.upper_limit),
                    }
                )
            else:
                decisions.append(
                    {
                        "compiled_identity": identity_payload(item.compiled_identity),
                        "fill_price": None if item.fill_price is None else str(item.fill_price),
                        "fill_quantity": str(item.fill_quantity),
                        "kind": "MATCH",
                        "matched": item.matched,
                        "reference_price": str(item.reference_price),
                        "remaining_liquidity": (
                            None if item.remaining_liquidity is None else str(item.remaining_liquidity)
                        ),
                        "unfilled_reason": item.unfilled_reason,
                    }
                )
        payload: dict[str, object] = {"schema_version": 3, "decisions": decisions}
        if self._reference_registry_fingerprint is not None:
            payload["reference_registry_fingerprint"] = self._reference_registry_fingerprint
        return payload

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
            raise ValueError("Market Rule checkpoint must contain decisions")
        if payload.get("schema_version") != 3:
            raise ValueError("CHECKPOINT_SCHEMA_UNSUPPORTED: Market Rule checkpoint requires version 3")
        if self._reference_registry_fingerprint is not None and (
            payload.get("reference_registry_fingerprint") != self._reference_registry_fingerprint
        ):
            raise ValueError("REFERENCE_FINGERPRINT_MISMATCH: checkpoint reference registry differs")

        def identity(raw: object) -> OnlyCompiledMarketRuleIdentity:
            if not isinstance(raw, dict):
                raise ValueError("Market Rule decision identity must be an object")
            restored_identity = OnlyCompiledMarketRuleIdentity(
                str(raw["profile_id"]),
                str(raw["profile_version"]),
                date.fromisoformat(str(raw["trading_day"])),
                OnlyRuntimeMode(str(raw["runtime_mode"])),
                str(raw["instrument_id"]),
                str(raw["venue"]),
                str(raw["reference_fingerprint"]),
                str(raw["resolved_profile_fingerprint"]),
                str(raw["compiled_rules_fingerprint"]),
            )
            expected = self.compiled_rules(
                restored_identity.instrument_id,
                OnlyTradingDay(restored_identity.trading_day),
            ).identity
            if expected.reference_fingerprint != restored_identity.reference_fingerprint:
                raise ValueError("REFERENCE_FINGERPRINT_MISMATCH: compiled Reference differs")
            if expected.resolved_profile_fingerprint != restored_identity.resolved_profile_fingerprint:
                raise ValueError("PROFILE_FINGERPRINT_MISMATCH: resolved Profile differs")
            if expected.compiled_rules_fingerprint != restored_identity.compiled_rules_fingerprint:
                raise ValueError("COMPILED_RULES_FINGERPRINT_MISMATCH: compiled policies differ")
            return restored_identity

        restored: list[OnlyMarketOrderDecision | OnlyMarketMatchDecision] = []
        for raw in payload["decisions"]:
            if not isinstance(raw, dict):
                raise ValueError("Market Rule decision must be an object")
            compiled_identity = identity(raw["compiled_identity"])
            if raw["kind"] == "ORDER":
                evaluation_payload = raw.get("evaluations")
                if not isinstance(evaluation_payload, list):
                    raise ValueError("Market order decision evaluations must be an array")
                evaluations: list[OnlyMarketRuleEvaluation] = []
                for evaluation in evaluation_payload:
                    if not isinstance(evaluation, dict) or not isinstance(evaluation.get("inputs"), list):
                        raise ValueError("Market order evaluation must be an object")
                    inputs: list[tuple[str, str]] = []
                    for pair in evaluation["inputs"]:
                        if not isinstance(pair, list) or len(pair) != 2:
                            raise ValueError("Market order evaluation input must be a pair")
                        inputs.append((str(pair[0]), str(pair[1])))
                    evaluations.append(
                        OnlyMarketRuleEvaluation(
                            str(evaluation["rule_code"]),
                            OnlyMarketRuleEvaluationStatus(str(evaluation["status"])),
                            None if evaluation["reason_code"] is None else str(evaluation["reason_code"]),
                            tuple(inputs),
                        )
                    )
                restored.append(
                    OnlyMarketOrderDecision(
                        bool(raw["accepted"]),
                        None if raw["reason_code"] is None else str(raw["reason_code"]),
                        tuple(evaluations),
                        OnlyTradingDay(date.fromisoformat(str(raw["trading_day"]))),
                        OnlyTradingPhase(str(raw["trading_phase"])),
                        datetime.fromisoformat(str(raw["timestamp"])),
                        OnlyOrderSide(str(raw["side"])),
                        Decimal(str(raw["normalized_price"])),
                        Decimal(str(raw["normalized_quantity"])),
                        OnlyPositionEffect(str(raw["position_effect"])),
                        Decimal(str(raw["required_cash"])),
                        Decimal(str(raw["required_position"])),
                        Decimal(str(raw["required_margin"])),
                        None if raw["previous_close"] is None else Decimal(str(raw["previous_close"])),
                        Decimal(str(raw["tick_size"])),
                        None if raw["daily_limit_rate"] is None else Decimal(str(raw["daily_limit_rate"])),
                        None if raw["lower_limit"] is None else Decimal(str(raw["lower_limit"])),
                        None if raw["upper_limit"] is None else Decimal(str(raw["upper_limit"])),
                        Decimal(str(raw["minimum_buy_quantity"])),
                        Decimal(str(raw["buy_quantity_increment"])),
                        Decimal(str(raw["sell_quantity_increment"])),
                        OnlyMarketRuleEvaluationStatus(str(raw["dynamic_price_cage_status"])),
                        compiled_identity,
                    )
                )
            elif raw["kind"] == "MATCH":
                restored.append(
                    OnlyMarketMatchDecision(
                        bool(raw["matched"]),
                        None if raw["unfilled_reason"] is None else str(raw["unfilled_reason"]),
                        Decimal(str(raw["reference_price"])),
                        None if raw["fill_price"] is None else Decimal(str(raw["fill_price"])),
                        Decimal(str(raw["fill_quantity"])),
                        None if raw["remaining_liquidity"] is None else Decimal(str(raw["remaining_liquidity"])),
                        compiled_identity,
                    )
                )
            else:
                raise ValueError("unsupported Market Rule decision kind")
        self._decisions = restored

    @property
    def checkpoint_schema_version(self) -> int:
        return 3

    def evaluate_pre_trade(self, context: OnlyPreTradeMarketContext) -> OnlyMarketOrderDecision:
        try:
            reference = self._reference(context.instrument_id, context.trading_day)
        except (KeyError, OnlyAshareReferenceError) as exc:
            return self._reference_failure_decision(context, exc)
        rules = self.compiled_rules(context.instrument_id, context.trading_day)
        session = rules.session_policy.state_at(context.timestamp.astimezone(ZoneInfo(rules.session_policy.timezone)))
        effect = self._position_effect(rules, context)
        required_position = (
            context.quantity
            if context.side is OnlyOrderSide.SELL and effect is not OnlyPositionEffect.OPEN
            else Decimal(0)
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
        evaluations: list[OnlyMarketRuleEvaluation] = []
        failed = False

        def record(
            rule_code: str,
            status: OnlyMarketRuleEvaluationStatus,
            reason_code: str | None = None,
            inputs: tuple[tuple[str, str], ...] = (),
        ) -> None:
            nonlocal failed
            if failed:
                evaluations.append(
                    OnlyMarketRuleEvaluation(
                        rule_code,
                        OnlyMarketRuleEvaluationStatus.NOT_EVALUATED,
                        None,
                    )
                )
                return
            evaluations.append(OnlyMarketRuleEvaluation(rule_code, status, reason_code, inputs))
            failed = status is OnlyMarketRuleEvaluationStatus.FAILED

        passed = OnlyMarketRuleEvaluationStatus.PASSED
        failed_status = OnlyMarketRuleEvaluationStatus.FAILED
        not_applicable = OnlyMarketRuleEvaluationStatus.NOT_APPLICABLE
        record("REFERENCE_COVERAGE", passed, inputs=(("reference_fingerprint", reference.content_fingerprint),))
        effective = reference.effective_from.date() <= context.trading_day.value and (
            reference.effective_to is None or context.trading_day.value < reference.effective_to.date()
        )
        record(
            "REFERENCE_EFFECTIVE_RANGE",
            passed if effective else failed_status,
            None if effective else "REFERENCE_NOT_EFFECTIVE",
        )
        record("EFFECTIVE_PROFILE_RESOLUTION", passed, inputs=(("profile_version", rules.identity.profile_version),))
        phase_reason = {
            OnlyTradingPhase.OPENING_AUCTION: "TRADING_PHASE_NOT_SUPPORTED",
            OnlyTradingPhase.CLOSING_AUCTION: "TRADING_PHASE_NOT_SUPPORTED",
            OnlyTradingPhase.MIDDAY_BREAK: "MIDDAY_BREAK",
            OnlyTradingPhase.CLOSED: "MARKET_CLOSED",
            OnlyTradingPhase.PRE_OPEN: "MARKET_CLOSED",
            OnlyTradingPhase.POST_MARKET: "MARKET_CLOSED",
        }.get(session.phase)
        record(
            "TRADING_PHASE",
            passed if session.phase is OnlyTradingPhase.CONTINUOUS else failed_status,
            phase_reason,
            (("phase", session.phase.value),),
        )
        record(
            "SUSPENSION",
            failed_status if reference.suspended else passed,
            "INSTRUMENT_SUSPENDED" if reference.suspended else None,
        )
        active = reference.status == "ACTIVE"
        record("INSTRUMENT_LIFECYCLE", passed if active else failed_status, None if active else "INSTRUMENT_INACTIVE")
        order_type_supported = context.order_type is OnlyOrderType.LIMIT
        record(
            "SUPPORTED_ORDER_TYPE",
            passed if order_type_supported else failed_status,
            None if order_type_supported else "ORDER_TYPE_NOT_SUPPORTED",
        )
        position_supported = not (
            rules.position_policy.mode is OnlyMarketPositionMode.LONG_ONLY
            and (
                (context.side is OnlyOrderSide.SELL and effect is OnlyPositionEffect.OPEN)
                or (context.side is OnlyOrderSide.BUY and effect is not OnlyPositionEffect.OPEN)
            )
        )
        record(
            "SIDE_POSITION_EFFECT",
            passed if position_supported else failed_status,
            None if position_supported else "SIDE_POSITION_EFFECT_NOT_SUPPORTED",
        )
        quantity_positive = context.quantity > 0
        record(
            "QUANTITY_POSITIVE",
            passed if quantity_positive else failed_status,
            None if quantity_positive else "QUANTITY_NON_POSITIVE",
        )
        minimum = (
            rules.quantity_policy.minimum_buy_quantity
            if context.side is OnlyOrderSide.BUY
            else rules.quantity_policy.minimum_sell_quantity
        )
        meets_minimum = context.quantity >= minimum
        minimum_reason = (
            "BUY_QUANTITY_BELOW_MINIMUM" if context.side is OnlyOrderSide.BUY else "SELL_QUANTITY_BELOW_MINIMUM"
        )
        record(
            "BUY_SELL_MINIMUM", passed if meets_minimum else failed_status, None if meets_minimum else minimum_reason
        )
        increment = (
            rules.quantity_policy.buy_quantity_increment
            if context.side is OnlyOrderSide.BUY
            else rules.quantity_policy.sell_quantity_increment
        )
        aligned = (
            (context.quantity - minimum) % increment == 0
            if context.side is OnlyOrderSide.BUY
            else context.quantity % increment == 0
        )
        odd_candidate = context.side is OnlyOrderSide.SELL and rules.quantity_policy.odd_lot_liquidation_allowed
        record(
            "QUANTITY_INCREMENT",
            passed if aligned else not_applicable if odd_candidate else failed_status,
            None
            if aligned or odd_candidate
            else (
                "BUY_QUANTITY_INCREMENT_INVALID"
                if context.side is OnlyOrderSide.BUY
                else "SELL_QUANTITY_INCREMENT_INVALID"
            ),
        )
        odd_lot_valid = aligned or (odd_candidate and context.quantity == context.unreserved_sellable_quantity)
        record(
            "ODD_LOT_LIQUIDATION",
            not_applicable
            if context.side is OnlyOrderSide.BUY or aligned
            else passed
            if odd_lot_valid
            else failed_status,
            None if odd_lot_valid else "ODD_LOT_SELL_REQUIRES_FULL_LIQUIDATION",
        )
        price_positive = context.price > 0
        record(
            "PRICE_POSITIVE",
            passed if price_positive else failed_status,
            None if price_positive else "PRICE_NON_POSITIVE",
        )
        tick_aligned = context.price % rules.price_policy.tick_size == 0
        record(
            "PRICE_TICK_ALIGNMENT",
            passed if tick_aligned else failed_status,
            None if tick_aligned else "PRICE_NOT_ALIGNED_TO_TICK",
        )
        has_band = rules.price_policy.daily_limit_rate is not None
        previous_close_valid = rules.price_policy.previous_close is not None and rules.price_policy.previous_close > 0
        record(
            "PREVIOUS_CLOSE_SEMANTICS",
            not_applicable if not has_band else passed if previous_close_valid else failed_status,
            None if not has_band or previous_close_valid else "REFERENCE_PREVIOUS_CLOSE_INVALID",
        )
        upper = rules.price_policy.upper_limit
        below_upper = upper is None or context.price <= upper
        record(
            "DAILY_UPPER_LIMIT",
            not_applicable if upper is None else passed if below_upper else failed_status,
            None if below_upper else "PRICE_ABOVE_DAILY_LIMIT",
        )
        lower = rules.price_policy.lower_limit
        above_lower = lower is None or context.price >= lower
        record(
            "DAILY_LOWER_LIMIT",
            not_applicable if lower is None else passed if above_lower else failed_status,
            None if above_lower else "PRICE_BELOW_DAILY_LIMIT",
        )
        position_available = required_position <= context.unreserved_sellable_quantity
        record(
            "SELLABLE_POSITION",
            passed if position_available else failed_status,
            None if position_available else "SELL_QUANTITY_EXCEEDS_AVAILABLE",
        )
        capital_available = (
            required_cash <= context.trade_available_cash and required_margin <= context.available_margin
        )
        capital_reason = "INSUFFICIENT_MARGIN" if required_margin > context.available_margin else "INSUFFICIENT_CASH"
        record(
            "AVAILABLE_CASH",
            passed if capital_available else failed_status,
            None if capital_available else capital_reason,
        )
        record(
            "DYNAMIC_PRICE_CAGE",
            OnlyMarketRuleEvaluationStatus.NOT_EVALUATED,
            "REALTIME_QUOTE_AUTHORITY_UNAVAILABLE",
        )
        reason = next(
            (item.reason_code for item in evaluations if item.status is OnlyMarketRuleEvaluationStatus.FAILED),
            None,
        )
        decision = OnlyMarketOrderDecision(
            accepted=reason is None,
            reason_code=reason,
            evaluations=tuple(evaluations),
            trading_day=context.trading_day,
            trading_phase=session.phase,
            timestamp=context.timestamp,
            side=context.side,
            normalized_price=context.price,
            normalized_quantity=context.quantity,
            position_effect=effect,
            required_cash=required_cash,
            required_position=required_position,
            required_margin=required_margin,
            previous_close=rules.price_policy.previous_close,
            tick_size=rules.price_policy.tick_size,
            daily_limit_rate=rules.price_policy.daily_limit_rate,
            lower_limit=rules.price_policy.lower_limit,
            upper_limit=rules.price_policy.upper_limit,
            minimum_buy_quantity=rules.quantity_policy.minimum_buy_quantity,
            buy_quantity_increment=rules.quantity_policy.buy_quantity_increment,
            sell_quantity_increment=rules.quantity_policy.sell_quantity_increment,
            dynamic_price_cage_status=OnlyMarketRuleEvaluationStatus.NOT_EVALUATED,
            compiled_identity=rules.identity,
        )
        self._decisions.append(decision)
        return decision

    def _reference_failure_decision(
        self,
        context: OnlyPreTradeMarketContext,
        error: KeyError | OnlyAshareReferenceError,
    ) -> OnlyMarketOrderDecision:
        raw_code = error.code if isinstance(error, OnlyAshareReferenceError) else "REFERENCE_NOT_FOUND"
        reason = "REFERENCE_CONFLICT" if raw_code in {"REFERENCE_AMBIGUOUS", "REFERENCE_RUNTIME_CONFLICT"} else raw_code
        resolved = self._registry.resolve(self._request, effective_on=context.trading_day.value)
        failure_payload = {
            "instrument_id": context.instrument_id,
            "profile_fingerprint": resolved.resolved_rules_fingerprint,
            "reason": reason,
            "runtime_mode": self._runtime_mode.value,
            "trading_day": context.trading_day.value.isoformat(),
        }
        failure_fingerprint = hashlib.sha256(
            json.dumps(failure_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identity = OnlyCompiledMarketRuleIdentity(
            resolved.resolved_profile_id.value,
            resolved.resolved_version,
            context.trading_day.value,
            self._runtime_mode,
            context.instrument_id,
            "",
            "",
            resolved.resolved_rules_fingerprint,
            failure_fingerprint,
        )
        evaluations = (
            OnlyMarketRuleEvaluation("REFERENCE_COVERAGE", OnlyMarketRuleEvaluationStatus.FAILED, reason),
            *(
                OnlyMarketRuleEvaluation(code, OnlyMarketRuleEvaluationStatus.NOT_EVALUATED, None)
                for code in _PRE_TRADE_RULE_ORDER[1:]
            ),
        )
        phase = resolved.profile.session_model.state_at(
            context.timestamp.astimezone(ZoneInfo(resolved.profile.session_model.timezone))
        ).phase
        effect = OnlyPositionEffect.OPEN if context.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
        decision = OnlyMarketOrderDecision(
            False,
            reason,
            evaluations,
            context.trading_day,
            phase,
            context.timestamp,
            context.side,
            context.price,
            context.quantity,
            effect,
            Decimal(0),
            Decimal(0),
            Decimal(0),
            None,
            Decimal(0),
            None,
            None,
            None,
            Decimal(0),
            Decimal(0),
            Decimal(0),
            OnlyMarketRuleEvaluationStatus.NOT_EVALUATED,
            identity,
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
        settlement = rules.settlement_policy.schedule(
            OnlySettlementScheduleRequest(request.side, request.trading_day),
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
                OnlyTimestamp.from_datetime(request.timestamp),
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
            "AVAILABLE" if settlement.asset_trade_available_on == request.trading_day else "PENDING",
            request.order_id,
            request.trade_id,
        )
        settles_notional = rules.margin_policy is None
        cash_sign = Decimal(-1) if request.side is OnlyOrderSide.BUY else Decimal(1)
        return OnlyTradeApplicationInstruction(
            position,
            settlement,
            margin,
            OnlyCashInstruction(
                reference.currency,
                cash_sign * notional if settles_notional else Decimal(0),
                settlement.cash_trade_available_on,
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
            OnlyTimestamp.from_datetime(request.timestamp),
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


def only_ashare_instrument_reference(
    instrument: OnlyInstrument,
    record: OnlyAshareInstrumentReference,
    *,
    profile_id: object,
) -> OnlyInstrumentReferenceSnapshot:
    """Project one resolved authority record into the existing compiled-rule contract."""

    if record.instrument_id != instrument.instrument_id:
        raise ValueError("REFERENCE_RUNTIME_CONFLICT: Instrument and Reference identities differ")
    expected_venue = {"SSE": "XSHG", "SZSE": "XSHE"}[record.exchange.value]
    if str(instrument.venue) != expected_venue:
        raise ValueError("REFERENCE_RUNTIME_CONFLICT: exchange and Instrument venue differ")
    projection = only_instrument_reference(
        instrument,
        profile_id=profile_id,
        source=record.source.value,
        board=record.board.value,
        st_status=record.st_status,
    )
    return OnlyInstrumentReferenceSnapshot(
        **{
            **asdict(projection),
            "effective_from": datetime.combine(record.effective_from.value, time(), tzinfo=UTC),
            "effective_to": (
                None if record.effective_to is None else datetime.combine(record.effective_to.value, time(), tzinfo=UTC)
            ),
            "source_version": record.source_version,
            "content_fingerprint": record.record_fingerprint,
            "tick_size": record.price_tick.value,
            "lot_size": record.lot_size.value,
            "st_status": record.st_status,
            "suspended": record.suspended,
            "previous_close": record.previous_close.value,
        }
    )


def _compile_generic_price_policy(
    profile_version: str,
    raw: OnlyPriceRule,
    reference: OnlyInstrumentReferenceSnapshot,
) -> OnlyCompiledPriceBandPolicy:
    tick_size = reference.tick_size
    previous_close = reference.previous_close
    lower: Decimal | None = None
    upper: Decimal | None = None
    if raw.daily_limit_rate is not None:
        if previous_close is None or previous_close <= 0:
            raise ValueError("REFERENCE_PREVIOUS_CLOSE_INVALID")
        with localcontext() as context:
            context.prec = 34
            lower = (previous_close * (Decimal(1) - raw.daily_limit_rate) / tick_size).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            ) * tick_size
            upper = (previous_close * (Decimal(1) + raw.daily_limit_rate) / tick_size).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            ) * tick_size
    return OnlyCompiledPriceBandPolicy(
        f"GENERIC@{profile_version}",
        tick_size,
        previous_close,
        raw.daily_limit_rate,
        lower,
        upper,
        OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
    )


def _compile_generic_quantity_policy(
    raw: OnlyQuantityRule,
    reference: OnlyInstrumentReferenceSnapshot,
) -> OnlyCompiledQuantityPolicy:
    increment = reference.quantity_step
    minimum = reference.minimum_quantity or increment
    return OnlyCompiledQuantityPolicy(
        minimum,
        increment,
        minimum,
        increment,
        raw.allow_odd_lot_liquidation,
        reference.maximum_quantity,
        raw.allow_fractional,
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
