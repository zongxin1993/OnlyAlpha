"""Compiled market rules and the sole Runtime market-rule entry point."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderSide, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay, only_require_utc
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionMode,
    OnlyPositionSide,
)
from onlyalpha.market.economics import OnlyEconomicModel, OnlyMarginIsolationScope
from onlyalpha.market.models import (
    OnlyMarketPositionMode,
    OnlyMarketRuleEvaluation,
    OnlyMarketRuleEvaluationStatus,
    OnlyPositionEffect,
    OnlyTradingDayAdvancer,
    OnlyTradingPhase,
)
from onlyalpha.market.product import (
    OnlyCompiledMarketPolicy,
    OnlyCompiledMarketPolicyIdentity,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductIdentity,
    OnlyResolvedMarketProductBinding,
)
from onlyalpha.settlement.models import OnlySettlementSchedule, OnlySettlementScheduleRequest

_PRE_TRADE_RULE_ORDER = (
    "REFERENCE_COVERAGE",
    "REFERENCE_EFFECTIVE_RANGE",
    "EFFECTIVE_MARKET_POLICY_RESOLUTION",
    "TRADING_PHASE",
    "SUSPENSION",
    "INSTRUMENT_LIFECYCLE",
    "SUPPORTED_ORDER_TYPE",
    "ORDER_CAPABILITY",
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
    "NOTIONAL_MINIMUM",
    "NOTIONAL_MAXIMUM",
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
    time_in_force: OnlyTimeInForce = OnlyTimeInForce.GTC
    position_side: OnlyPositionSide | None = None
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING
    close_scope: OnlyCloseScope = OnlyCloseScope.ANY
    exposure_constraint: OnlyExposureConstraint = OnlyExposureConstraint.NONE

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
    compiled_identity: OnlyCompiledMarketPolicyIdentity


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
    margin_mode: str = "CROSS"
    isolation_key: str | None = None
    position_side: str = "LONG"


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
    compiled_identity: OnlyCompiledMarketPolicyIdentity
    market_product_identity: OnlyMarketProductIdentity


class OnlyPreTradeMarketRulePort(Protocol):
    @property
    def market_product_identity(self) -> OnlyMarketProductIdentity: ...

    @property
    def market_product_provider(self) -> str: ...

    def position_mode(self, instrument_id: str, trading_day: OnlyTradingDay) -> OnlyMarketPositionMode: ...

    def evaluate_pre_trade(self, context: OnlyPreTradeMarketContext) -> OnlyMarketOrderDecision: ...


class OnlyTradeInstructionPort(Protocol):
    @property
    def market_product_identity(self) -> OnlyMarketProductIdentity: ...

    def build_trade_instruction(self, request: OnlyTradeApplicationRequest) -> OnlyTradeApplicationInstruction: ...

    def compiled_rules(
        self,
        instrument_id: str,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyCompiledMarketPolicy: ...


class OnlyMarketRuleEngine(OnlyPreTradeMarketRulePort, OnlyTradeInstructionPort):
    """Runtime operational service over one already-resolved Market Product binding."""

    def __init__(
        self,
        *,
        binding: OnlyResolvedMarketProductBinding,
        advance_trading_day: OnlyTradingDayAdvancer,
    ) -> None:
        self._binding = binding
        self._advance_trading_day = advance_trading_day
        self._cache: dict[tuple[str, object, str], OnlyCompiledMarketPolicy] = {}
        self._decisions: list[OnlyMarketOrderDecision] = []

    @property
    def decisions(self) -> tuple[OnlyMarketOrderDecision, ...]:
        return tuple(self._decisions)

    @property
    def market_product_identity(self) -> OnlyMarketProductIdentity:
        return self._binding.product_identity

    @property
    def market_product_provider(self) -> str:
        return str(self._binding.provider_plugin_id)

    @property
    def market_composition_fingerprint(self) -> str:
        return self._binding.composition_identity.fingerprint

    @property
    def compiled_identities(self) -> tuple[OnlyCompiledMarketPolicyIdentity, ...]:
        """Stable public query projection for collectors and artifacts."""
        return tuple(item.identity for _, item in sorted(self._cache.items(), key=lambda pair: pair[0]))

    def compiled_rules(
        self,
        instrument_id: str,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyCompiledMarketPolicy:
        compiled = self._binding.policy_compiler.compile(
            OnlyMarketPolicyCompilationRequest(
                OnlyInstrumentId.parse(instrument_id),
                trading_day,
                self._binding.reference_authority,
                as_of,
            )
        )
        key = (instrument_id, trading_day.value, compiled.identity.reference_fingerprint)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._cache[key] = compiled
        return compiled

    def capture_checkpoint(self) -> object:
        def identity_payload(identity: OnlyCompiledMarketPolicyIdentity) -> dict[str, str]:
            return {
                "instrument_id": str(identity.instrument_id),
                "reference_fingerprint": identity.reference_fingerprint,
                "policy_fingerprint": identity.policy_fingerprint,
                "trading_day": identity.trading_day.value.isoformat(),
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
        return {
            "schema_version": 7,
            "market_composition_fingerprint": self._binding.composition_identity.fingerprint,
            "decisions": decisions,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
            raise ValueError("Market Rule checkpoint must contain decisions")
        if payload.get("schema_version") != 7:
            raise ValueError("CHECKPOINT_SCHEMA_UNSUPPORTED: Market Rule checkpoint requires version 7")
        if payload.get("market_composition_fingerprint") != self._binding.composition_identity.fingerprint:
            raise ValueError("MARKET_COMPOSITION_FINGERPRINT_MISMATCH")

        def identity(raw: object, *, as_of: datetime) -> OnlyCompiledMarketPolicyIdentity:
            if not isinstance(raw, dict):
                raise ValueError("Market Rule decision identity must be an object")
            expected = self.compiled_rules(
                str(raw["instrument_id"]),
                OnlyTradingDay(date.fromisoformat(str(raw["trading_day"]))),
                as_of=as_of,
            ).identity
            if expected.reference_fingerprint != str(raw["reference_fingerprint"]):
                raise ValueError("REFERENCE_FINGERPRINT_MISMATCH: compiled Reference differs")
            if expected.policy_fingerprint != str(raw["policy_fingerprint"]):
                raise ValueError("COMPILED_POLICY_FINGERPRINT_MISMATCH")
            return expected

        restored: list[OnlyMarketOrderDecision] = []
        for raw in payload["decisions"]:
            if not isinstance(raw, dict):
                raise ValueError("Market Rule decision must be an object")
            if raw["kind"] == "ORDER":
                decision_timestamp = datetime.fromisoformat(str(raw["timestamp"]))
                compiled_identity = identity(raw["compiled_identity"], as_of=decision_timestamp)
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
                        decision_timestamp,
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
            else:
                raise ValueError("unsupported Market Rule decision kind")
        self._decisions = restored

    @property
    def checkpoint_schema_version(self) -> int:
        return 7

    def evaluate_pre_trade(self, context: OnlyPreTradeMarketContext) -> OnlyMarketOrderDecision:
        try:
            rules = self.compiled_rules(context.instrument_id, context.trading_day, as_of=context.timestamp)
        except (KeyError, ValueError) as exc:
            return self._reference_failure_decision(context, exc)
        session = rules.session_policy.state_at(context.timestamp.astimezone(ZoneInfo(rules.session_policy.timezone)))
        effect = self._position_effect(rules, context)
        required_position = context.quantity if effect is OnlyPositionEffect.CLOSE else Decimal(0)
        notional = context.price * context.quantity * rules.instrument_terms.contract_multiplier
        required_cash = (
            notional
            if rules.economic_model is OnlyEconomicModel.CASH_EXCHANGE
            and context.side is OnlyOrderSide.BUY
            and effect is OnlyPositionEffect.OPEN
            else Decimal(0)
        )
        required_margin = Decimal(0)
        if effect is OnlyPositionEffect.OPEN:
            requirement = self._margin_requirement(rules, notional, context.price, context.quantity)
            if requirement is not None:
                required_margin = requirement[0]
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
        record("REFERENCE_COVERAGE", passed, inputs=(("reference_fingerprint", rules.identity.reference_fingerprint),))
        record("REFERENCE_EFFECTIVE_RANGE", passed)
        record(
            "EFFECTIVE_MARKET_POLICY_RESOLUTION",
            passed,
            inputs=(("policy_fingerprint", rules.identity.policy_fingerprint),),
        )
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
            failed_status if rules.instrument_terms.trading_status is OnlyInstrumentTradingStatus.SUSPENDED else passed,
            "INSTRUMENT_SUSPENDED"
            if rules.instrument_terms.trading_status is OnlyInstrumentTradingStatus.SUSPENDED
            else None,
        )
        active = rules.instrument_terms.trading_status is not OnlyInstrumentTradingStatus.INACTIVE
        record("INSTRUMENT_LIFECYCLE", passed if active else failed_status, None if active else "INSTRUMENT_INACTIVE")
        order_type_supported = context.order_type is OnlyOrderType.LIMIT
        record(
            "SUPPORTED_ORDER_TYPE",
            passed if order_type_supported else failed_status,
            None if order_type_supported else "ORDER_TYPE_NOT_SUPPORTED",
        )
        canonical_side = context.position_side or (
            OnlyPositionSide.LONG
            if (context.side is OnlyOrderSide.BUY and effect is OnlyPositionEffect.OPEN)
            or (context.side is OnlyOrderSide.SELL and effect is OnlyPositionEffect.CLOSE)
            else OnlyPositionSide.SHORT
        )
        capability = rules.order_capability_policy
        capability_supported = capability is None or (
            context.order_type in capability.supported_order_types
            and context.time_in_force in capability.supported_time_in_force
            and effect in capability.supported_position_effects
            and context.close_scope in capability.supported_close_scopes
            and context.exposure_constraint in capability.supported_exposure_constraints
            and context.position_mode in capability.supported_position_modes
        )
        record(
            "ORDER_CAPABILITY",
            passed if capability_supported else failed_status,
            None if capability_supported else "ORDER_CAPABILITY_NOT_SUPPORTED",
            (("position_side", canonical_side.value),),
        )
        position_supported = not (
            rules.position_policy.mode is OnlyMarketPositionMode.LONG_ONLY
            and (
                (context.side is OnlyOrderSide.SELL and effect is OnlyPositionEffect.OPEN)
                or (context.side is OnlyOrderSide.BUY and effect is not OnlyPositionEffect.OPEN)
            )
        )
        expected_position_mode = (
            OnlyPositionMode.HEDGING
            if rules.position_policy.mode is OnlyMarketPositionMode.HEDGING
            else OnlyPositionMode.NETTING
        )
        position_supported = position_supported and context.position_mode is expected_position_mode
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
        notional_policy = rules.notional_policy
        minimum_notional = None if notional_policy is None else notional_policy.minimum_notional
        minimum_notional_valid = minimum_notional is None or notional >= minimum_notional
        record(
            "NOTIONAL_MINIMUM",
            not_applicable if minimum_notional is None else passed if minimum_notional_valid else failed_status,
            None if minimum_notional_valid else "NOTIONAL_BELOW_MINIMUM",
            () if minimum_notional is None else (("notional", str(notional)), ("minimum", str(minimum_notional))),
        )
        maximum_notional = None if notional_policy is None else notional_policy.maximum_notional
        maximum_notional_valid = maximum_notional is None or notional <= maximum_notional
        record(
            "NOTIONAL_MAXIMUM",
            not_applicable if maximum_notional is None else passed if maximum_notional_valid else failed_status,
            None if maximum_notional_valid else "NOTIONAL_ABOVE_MAXIMUM",
            () if maximum_notional is None else (("notional", str(notional)), ("maximum", str(maximum_notional))),
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
        dynamic_status = (
            OnlyMarketRuleEvaluationStatus.NOT_EVALUATED
            if rules.dynamic_price_requirements
            else OnlyMarketRuleEvaluationStatus.NOT_APPLICABLE
        )
        record(
            "DYNAMIC_PRICE_CAGE",
            dynamic_status,
            "REALTIME_QUOTE_AUTHORITY_UNAVAILABLE" if rules.dynamic_price_requirements else None,
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
            dynamic_price_cage_status=dynamic_status,
            compiled_identity=rules.identity,
        )
        self._decisions.append(decision)
        return decision

    def _reference_failure_decision(
        self,
        context: OnlyPreTradeMarketContext,
        error: KeyError | ValueError,
    ) -> OnlyMarketOrderDecision:
        raw_code = getattr(error, "code", "REFERENCE_NOT_FOUND")
        reason = "REFERENCE_CONFLICT" if raw_code in {"REFERENCE_AMBIGUOUS", "REFERENCE_RUNTIME_CONFLICT"} else raw_code
        identity = OnlyCompiledMarketPolicyIdentity(
            OnlyInstrumentId.parse(context.instrument_id),
            context.trading_day,
            "0" * 64,
            self._binding.policy_compiler.identity,
            only_canonical_fingerprint((context.instrument_id, context.trading_day, reason)),
        )
        evaluations = (
            OnlyMarketRuleEvaluation("REFERENCE_COVERAGE", OnlyMarketRuleEvaluationStatus.FAILED, reason),
            *(
                OnlyMarketRuleEvaluation(code, OnlyMarketRuleEvaluationStatus.NOT_EVALUATED, None)
                for code in _PRE_TRADE_RULE_ORDER[1:]
            ),
        )
        phase = OnlyTradingPhase.CLOSED
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

    def build_trade_instruction(self, request: OnlyTradeApplicationRequest) -> OnlyTradeApplicationInstruction:
        rules = self.compiled_rules(request.instrument_id, request.trading_day, as_of=request.timestamp)
        effect = request.position_effect
        if effect is OnlyPositionEffect.AUTO:
            effect = OnlyPositionEffect.OPEN if request.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
        notional = request.price * request.quantity * rules.instrument_terms.contract_multiplier
        settlement = rules.settlement_policy.schedule(
            OnlySettlementScheduleRequest(request.side, request.trading_day),
            self._advance_trading_day,
        )
        position_side = (
            "SHORT"
            if (request.side is OnlyOrderSide.SELL and effect is OnlyPositionEffect.OPEN)
            or (request.side is OnlyOrderSide.BUY and effect is not OnlyPositionEffect.OPEN)
            else "LONG"
        )
        margin = None
        requirement = self._margin_requirement(rules, notional, request.price, request.quantity)
        if requirement is not None:
            margin_mode, isolation_key = self._margin_scope(rules, request.instrument_id, position_side)
            margin = OnlyMarginInstruction(
                "OCCUPY" if effect is OnlyPositionEffect.OPEN else "RELEASE",
                request.account_id,
                request.instrument_id,
                rules.instrument_terms.settlement_currency,
                requirement[0],
                requirement[1],
                request.order_id,
                request.trade_id,
                OnlyTimestamp.from_datetime(request.timestamp),
                margin_mode.value,
                isolation_key,
                position_side,
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
        settles_notional = rules.economic_model is OnlyEconomicModel.CASH_EXCHANGE
        cash_sign = Decimal(-1) if request.side is OnlyOrderSide.BUY else Decimal(1)
        return OnlyTradeApplicationInstruction(
            position,
            settlement,
            margin,
            OnlyCashInstruction(
                rules.instrument_terms.settlement_currency,
                cash_sign * notional if settles_notional else Decimal(0),
                settlement.cash_trade_available_on,
                settles_notional,
            ),
            rules.identity,
            self._binding.product_identity,
        )

    @staticmethod
    def _position_effect(rules: OnlyCompiledMarketPolicy, context: OnlyPreTradeMarketContext) -> OnlyPositionEffect:
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

        rules = self.compiled_rules(request.instrument_id, request.trading_day, as_of=request.timestamp)
        if request.position_effect is not OnlyPositionEffect.OPEN:
            return None
        notional = request.price * request.quantity * rules.instrument_terms.contract_multiplier
        requirement = self._margin_requirement(rules, notional, request.price, request.quantity)
        if requirement is None:
            return None
        position_side = "LONG" if request.side is OnlyOrderSide.BUY else "SHORT"
        margin_mode, isolation_key = self._margin_scope(rules, request.instrument_id, position_side)
        return OnlyMarginInstruction(
            "RESERVE",
            request.account_id,
            request.instrument_id,
            rules.instrument_terms.settlement_currency,
            requirement[0],
            requirement[1],
            request.order_id,
            request.trade_id,
            OnlyTimestamp.from_datetime(request.timestamp),
            margin_mode.value,
            isolation_key,
            position_side,
        )

    @staticmethod
    def _margin_requirement(
        rules: OnlyCompiledMarketPolicy,
        notional: Decimal,
        price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal] | None:
        if rules.compiled_margin_policy is not None:
            return rules.compiled_margin_policy.requirement(notional)
        if rules.margin_policy is not None:
            requirement = rules.margin_policy.requirement(price, quantity, rules.instrument_terms.contract_multiplier)
            return requirement.initial_margin, requirement.maintenance_margin
        return None

    @staticmethod
    def _margin_scope(
        rules: OnlyCompiledMarketPolicy,
        instrument_id: str,
        position_side: str,
    ) -> tuple[OnlyMarginMode, str | None]:
        policy = rules.compiled_margin_policy
        if policy is None:
            return OnlyMarginMode.CROSS, None
        if policy.margin_mode is OnlyMarginMode.CROSS:
            return policy.margin_mode, None
        isolation_key = (
            instrument_id
            if policy.isolation_scope is OnlyMarginIsolationScope.INSTRUMENT
            else f"{instrument_id}:{position_side}"
        )
        return policy.margin_mode, isolation_key
