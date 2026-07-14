"""Runtime-owned Risk orchestration, audit, Snapshot and Reservation service."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.event.model import OnlyEvent
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.risk.audit import OnlyOrderIntentAudit, OnlyRiskDecisionAudit
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext, OnlyRiskStateUpdateContext
from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskRejection
from onlyalpha.risk.enums import (
    OnlyRiskLevel,
    OnlyRiskOutcome,
    OnlyRiskRejectionCode,
    OnlyRiskReleaseReason,
    OnlyRiskRuleScope,
    OnlyRiskSeverity,
)
from onlyalpha.risk.events import (
    OnlyRiskAcceptedEvent,
    OnlyRiskRejectedEvent,
    OnlyRiskReservationCreatedEvent,
    OnlyRiskReservationReleasedEvent,
    OnlyRiskRuleFailedEvent,
    OnlyRiskStateUpdatedEvent,
)
from onlyalpha.risk.identifiers import (
    OnlyRiskAuditId,
    OnlyRiskProfileId,
    OnlyRiskReservationId,
    OnlyRiskRuleId,
)
from onlyalpha.risk.kill_switch import OnlyRiskKillSwitch
from onlyalpha.risk.pipeline import OnlyRiskPipeline
from onlyalpha.risk.ports import (
    OnlyAccountRiskView,
    OnlyPositionRiskView,
    OnlyUnavailableAccountRiskView,
    OnlyUnavailablePositionRiskView,
)
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.publisher import OnlyRiskEventPublisher
from onlyalpha.risk.reservations import (
    OnlyRiskReservation,
    OnlyRiskReservationManager,
    OnlyRiskReservationResult,
)
from onlyalpha.risk.rules.base import OnlyRiskRule
from onlyalpha.risk.rules.instrument import only_default_instrument_rules
from onlyalpha.risk.rules.mandatory import only_mandatory_rules
from onlyalpha.risk.rules.runtime import (
    OnlyClusterAccountPermissionRiskRule,
    OnlyClusterInstrumentPermissionRiskRule,
    OnlyMaxOrderNotionalRiskRule,
)
from onlyalpha.risk.snapshots import OnlyRiskSnapshot
from onlyalpha.risk.state_store import OnlyInMemoryRiskStateStore
from onlyalpha.risk.views import (
    OnlyClusterPermissionMappingView,
    OnlyInstrumentRiskMappingView,
    OnlyMarketRuleRiskMappingView,
    OnlyOrderRiskQueryView,
)


class OnlyRiskService:
    """Unique Risk Pipeline and mutable Risk State owner for one Runtime."""

    def __init__(
        self,
        engine_id: OnlyEngineId,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClockView,
        trading_calendar: OnlyTradingCalendar,
        instruments: OnlyInstrumentRiskMappingView,
        market_rules: OnlyMarketRuleRiskMappingView,
        order_query: OnlyOrderQueryService,
        publisher: OnlyRiskEventPublisher,
        *,
        runtime_rules: tuple[OnlyRiskRule, ...] = (),
        account_rules: tuple[OnlyRiskRule, ...] = (),
        account_risk: OnlyAccountRiskView | None = None,
        position_risk: OnlyPositionRiskView | None = None,
    ) -> None:
        self.engine_id = engine_id
        self.runtime_id = runtime_id
        self._clock = clock
        self._calendar = trading_calendar
        self._instruments = instruments
        self._market_rules = market_rules
        self._orders = OnlyOrderRiskQueryView(order_query)
        self._publisher = publisher
        self._runtime_rules = runtime_rules
        self._account_rules = account_rules
        self._instrument_rules = only_default_instrument_rules()
        self._cluster_base_rules: tuple[OnlyRiskRule, ...] = (
            OnlyClusterInstrumentPermissionRiskRule(),
            OnlyClusterAccountPermissionRiskRule(),
        )
        self._mandatory_rules = only_mandatory_rules(runtime_id)
        self._account_risk = account_risk or OnlyUnavailableAccountRiskView()
        self._position_risk = position_risk or OnlyUnavailablePositionRiskView()
        self._state = OnlyInMemoryRiskStateStore()
        self._reservations = OnlyRiskReservationManager(runtime_id)
        self._permissions = OnlyClusterPermissionMappingView()
        self._profiles: dict[OnlyClusterId, OnlyRiskProfile] = {}
        self._default_accounts: dict[OnlyClusterId, OnlyAccountId] = {}
        self._latest_market_data: dict[OnlyClusterId, OnlyMarketDataSnapshot] = {}
        self._requests: dict[tuple[OnlyClusterId, OnlyAccountId, object], OnlyOrderRequest] = {}
        self._audits: list[OnlyRiskDecisionAudit] = []
        self._audit_sequence = 0
        self._event_sequence = 0
        self._kill_switch = OnlyRiskKillSwitch()

    @property
    def mandatory_rule_ids(self) -> tuple[OnlyRiskRuleId, ...]:
        return tuple(rule.rule_id for rule in self._mandatory_rules)

    @property
    def reservations(self) -> OnlyRiskReservationManager:
        """Runtime-internal Reservation port; never placed in Cluster Context."""

        return self._reservations

    @property
    def kill_switch(self) -> OnlyRiskKillSwitch:
        """Management-only Kill Switch; Cluster receives a boolean Snapshot."""

        return self._kill_switch

    @property
    def audits(self) -> tuple[OnlyRiskDecisionAudit, ...]:
        return tuple(self._audits)

    def bind_cluster_profile(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        profile: OnlyRiskProfile,
        *,
        allowed_accounts: frozenset[OnlyAccountId] | None = None,
        allowed_instruments: frozenset[OnlyInstrumentId] | None = None,
    ) -> None:
        if cluster_id in self._profiles:
            raise ValueError(f"Cluster Risk Profile already bound: {cluster_id}")
        mandatory = set(self.mandatory_rule_ids)
        if any(rule.rule_id in mandatory or rule.metadata.mandatory for rule in profile.rules):
            raise ValueError("Cluster Profile cannot replace Mandatory Risk Rules")
        self._pipeline(profile)
        self._profiles[cluster_id] = profile
        self._default_accounts[cluster_id] = account_id
        self._permissions.bind(
            cluster_id,
            allowed_accounts if allowed_accounts is not None else frozenset({account_id}),
            allowed_instruments if allowed_instruments is not None else frozenset(),
        )
        now = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        self.update_pre_decision_state(OnlyRiskStateUpdateContext(self.runtime_id, cluster_id, account_id, now, now))

    def unbind_cluster_profile(self, cluster_id: OnlyClusterId) -> None:
        now = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        for result in self._reservations.release_cluster(cluster_id, now):
            if result.changed and result.reservation is not None:
                self._publisher.publish(self._reservation_event(result.reservation, False))
        self._profiles.pop(cluster_id, None)
        self._default_accounts.pop(cluster_id, None)
        self._latest_market_data.pop(cluster_id, None)
        self._permissions.unbind(cluster_id)
        self._state.remove_cluster(cluster_id)

    def make_evaluation_context(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        timestamp: OnlyTimestamp,
    ) -> OnlyRiskEvaluationContext:
        return OnlyRiskEvaluationContext(
            self.runtime_id,
            cluster_id,
            account_id,
            timestamp,
            timestamp,
            self._clock,
            self._instruments,
            self._market_rules,
            self._calendar,
            self._orders,
            self._reservations,
            self._permissions,
            self._account_risk,
            self._position_risk,
            frozenset({OnlyOrderType.MARKET, OnlyOrderType.LIMIT}),
            cluster_id in self._profiles,
            self._kill_switch.is_active(cluster_id, account_id),
            self._latest_market_data.get(cluster_id),
        )

    def evaluate_order(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> OnlyRiskDecision:
        if context.runtime_id != self.runtime_id:
            raise ValueError("Risk Evaluation Context belongs to another Runtime")
        key = (context.cluster_id, context.account_id, request.request_id)
        previous_request = self._requests.get(key)
        cached = self._state.get_decision(context.cluster_id, context.account_id, request.request_id)
        if cached is not None and previous_request == request:
            return cached
        if previous_request is not None and previous_request != request:
            decision = OnlyRiskDecision.rejected(
                OnlyRiskRejection(
                    OnlyRiskRuleId("system.request_idempotency"),
                    OnlyRiskRejectionCode.DUPLICATE_ORDER_REQUEST,
                    "RequestId was already used for different Order intent",
                    OnlyRiskRuleScope.SYSTEM,
                    OnlyRiskSeverity.ERROR,
                )
            )
        else:
            profile = self._profiles.get(
                context.cluster_id,
                OnlyRiskProfile(OnlyRiskProfileId("UNBOUND")),
            )
            decision = self._pipeline(profile).evaluate(request, context).decision
        self._requests.setdefault(key, request)
        self._state.save_decision(context.cluster_id, context.account_id, request.request_id, decision)
        if decision.outcome is OnlyRiskOutcome.REJECT:
            self._state.record_rejection(context.cluster_id)
        audit = self._audit(request, context, decision)
        self._audits.append(audit)
        self._publisher.publish(self._decision_event(decision, audit))
        return decision

    def update_pre_decision_state(self, context: OnlyRiskStateUpdateContext) -> OnlyRiskSnapshot:
        if context.runtime_id != self.runtime_id:
            raise ValueError("Risk state update belongs to another Runtime")
        if context.market_data is not None:
            self._latest_market_data[context.cluster_id] = context.market_data
        profile = self._profiles.get(context.cluster_id)
        maximum = self._profile_notional_limit(profile)
        reserved = None
        remaining = None
        if maximum is not None:
            reserved = self._reservations.active_notional(maximum.currency, cluster_id=context.cluster_id)
            remaining = OnlyMoney(max(Decimal("0"), maximum.amount - reserved.amount), maximum.currency)
        active_reservations = tuple(
            item for item in self._reservations.snapshot_active() if item.cluster_id == context.cluster_id
        )
        reserved_quantity = sum((item.reserved_quantity.value for item in active_reservations), Decimal("0"))
        quality_flags = tuple(
            name
            for name, available in (
                ("ACCOUNT_RISK_UNAVAILABLE", self._account_risk.available),
                ("POSITION_RISK_UNAVAILABLE", self._position_risk.available),
            )
            if not available
        )
        kill_switch = self._kill_switch.is_active(context.cluster_id, context.account_id)
        snapshot = OnlyRiskSnapshot(
            self.runtime_id,
            context.cluster_id,
            context.account_id,
            context.ts_event,
            context.ts_init,
            self._state.next_snapshot_version(context.cluster_id),
            OnlyRiskLevel.BLOCKED if kill_switch else OnlyRiskLevel.NORMAL,
            kill_switch,
            self._orders.active_count(),
            self._orders.active_count(cluster_id=context.cluster_id),
            reserved,
            reserved_quantity,
            remaining,
            self._state.rejection_count(context.cluster_id),
            quality_flags=quality_flags,
        )
        self._state.save_snapshot(snapshot)
        self._publisher.publish(self._state_event(snapshot))
        return snapshot

    def get_snapshot(self, cluster_id: OnlyClusterId) -> OnlyRiskSnapshot:
        snapshot = self._state.get_snapshot(cluster_id)
        if snapshot is None:
            raise KeyError(f"Risk Snapshot is unavailable for Cluster: {cluster_id}")
        return snapshot

    def reserve_order(
        self,
        order: OnlyOrderSnapshot,
        timestamp: OnlyTimestamp,
    ) -> OnlyRiskReservationResult:
        if order.runtime_id != self.runtime_id:
            raise ValueError("Order belongs to another Runtime")
        instrument = self._instruments.get(order.instrument_id)
        reserved_notional = None
        if instrument is not None and order.price is not None:
            raw = order.price.value * order.quantity.value * instrument.contract_multiplier.value
            quantum = Decimal(1).scaleb(-instrument.quote_currency.precision)
            reserved_notional = OnlyMoney(raw.quantize(quantum, rounding=ROUND_DOWN), instrument.quote_currency)
        result = self._reservations.create(
            order.cluster_id,
            order.account_id,
            order.order_id,
            order.instrument_id,
            reserved_notional,
            order.quantity,
            timestamp,
        )
        if result.changed and result.reservation is not None:
            self._publisher.publish(self._reservation_event(result.reservation, True))
            self._refresh_snapshot(order.cluster_id, order.account_id, timestamp)
        return result

    def release_order(
        self,
        order_id: OnlyOrderId,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        reason: OnlyRiskReleaseReason,
        timestamp: OnlyTimestamp,
    ) -> OnlyRiskReservationResult:
        result = self._reservations.release_for_order(
            order_id,
            reason,
            timestamp,
            runtime_id=self.runtime_id,
            cluster_id=cluster_id,
        )
        if result.changed and result.reservation is not None:
            self._publisher.publish(self._reservation_event(result.reservation, False))
            self._refresh_snapshot(cluster_id, account_id, timestamp)
        return result

    def release_reservation(
        self,
        reservation_id: OnlyRiskReservationId,
        cluster_id: OnlyClusterId,
        reason: OnlyRiskReleaseReason,
        timestamp: OnlyTimestamp,
    ) -> OnlyRiskReservationResult:
        result = self._reservations.release(
            reservation_id,
            reason,
            timestamp,
            runtime_id=self.runtime_id,
            cluster_id=cluster_id,
        )
        if result.changed and result.reservation is not None:
            self._publisher.publish(self._reservation_event(result.reservation, False))
            self._refresh_snapshot(cluster_id, result.reservation.account_id, timestamp)
        return result

    def _pipeline(self, profile: OnlyRiskProfile) -> OnlyRiskPipeline:
        return OnlyRiskPipeline(
            self._mandatory_rules
            + self._runtime_rules
            + self._account_rules
            + self._instrument_rules
            + self._cluster_base_rules
            + profile.rules
        )

    def _audit(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
        decision: OnlyRiskDecision,
    ) -> OnlyRiskDecisionAudit:
        self._audit_sequence += 1
        audit_id = OnlyRiskAuditId(f"{self.runtime_id}-AUDIT-{self._audit_sequence:06d}")
        intent = OnlyOrderIntentAudit(
            audit_id,
            self.runtime_id,
            context.cluster_id,
            context.account_id,
            request,
            context.ts_event,
            context.ts_init,
            str(request.request_id),
        )
        return OnlyRiskDecisionAudit(intent, decision)

    def _decision_event(self, decision: OnlyRiskDecision, audit: OnlyRiskDecisionAudit) -> OnlyEvent:
        event_type = {
            OnlyRiskOutcome.ACCEPT: (OnlyRiskAcceptedEvent, "RISK_ACCEPTED"),
            OnlyRiskOutcome.REJECT: (OnlyRiskRejectedEvent, "RISK_REJECTED"),
            OnlyRiskOutcome.ERROR: (OnlyRiskRuleFailedEvent, "RISK_RULE_FAILED"),
        }[decision.outcome]
        return self._event(
            event_type[0],
            event_type[1],
            audit.intent.cluster_id,
            audit.intent.ts_event,
            {"audit_id": str(audit.intent.audit_id), "decision": decision.to_dict()},
        )

    def _state_event(self, snapshot: OnlyRiskSnapshot) -> OnlyEvent:
        return self._event(
            OnlyRiskStateUpdatedEvent,
            "RISK_STATE_UPDATED",
            snapshot.cluster_id,
            snapshot.ts_event,
            {"snapshot": snapshot.to_dict()},
        )

    def _reservation_event(self, reservation: OnlyRiskReservation, created: bool) -> OnlyEvent:
        return self._event(
            OnlyRiskReservationCreatedEvent if created else OnlyRiskReservationReleasedEvent,
            "RISK_RESERVATION_CREATED" if created else "RISK_RESERVATION_RELEASED",
            reservation.cluster_id,
            reservation.updated_at,
            {"reservation": reservation.to_dict()},
        )

    def _event(
        self,
        event_class: type[OnlyEvent],
        event_type: str,
        cluster_id: OnlyClusterId,
        timestamp: OnlyTimestamp,
        payload: object,
    ) -> OnlyEvent:
        self._event_sequence += 1
        return event_class(
            event_type,
            timestamp.to_datetime(),
            self.engine_id,
            self.runtime_id,
            "risk_service",
            self._event_sequence,
            payload=payload,
            cluster_id=cluster_id,
            timestamp_ns=timestamp.unix_nanos,
            ts_init_ns=timestamp.unix_nanos,
        )

    def _profile_notional_limit(self, profile: OnlyRiskProfile | None) -> OnlyMoney | None:
        if profile is None:
            return None
        limits = [rule.maximum for rule in profile.rules if isinstance(rule, OnlyMaxOrderNotionalRiskRule)]
        return limits[0] if limits else None

    def _refresh_snapshot(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        timestamp: OnlyTimestamp,
    ) -> None:
        self.update_pre_decision_state(
            OnlyRiskStateUpdateContext(
                self.runtime_id,
                cluster_id,
                account_id,
                timestamp,
                timestamp,
                self._latest_market_data.get(cluster_id),
            )
        )
