"""Deterministic read-only post-recovery authority validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from onlyalpha.account.models import OnlyAccountReservation, OnlyAccountSnapshot
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution.applied_projection import OnlyAppliedProjectionLedger
from onlyalpha.execution.persistence_ports import (
    OnlyExecutionTransactionOutboxPort,
    OnlyExecutionTransactionQueryPort,
    OnlyProjectionReadyExecutionQueryPort,
)
from onlyalpha.fee.manager import OnlyFeeRecord
from onlyalpha.margin.manager import OnlyMarginRecord
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.position.reservations import OnlyPositionReservation
from onlyalpha.risk.reservations import OnlyRiskReservation
from onlyalpha.settlement.manager import OnlySettlementRecord
from onlyalpha.strategy_ledger.models import OnlyStrategyCashReservation, OnlyStrategyLedgerSnapshot

from .authority_views import OnlyBrokerRecoveryAuthorityView, OnlyRuntimeBoundaryAuthorityView
from .outcome import OnlyRuntimeRecoveryOutcome


class OnlyPostRecoveryCheckStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationCheck:
    code: str
    status: OnlyPostRecoveryCheckStatus
    scope: str
    expected: str | None
    actual: str | None
    detail: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.scope.strip():
            raise ValueError("post-recovery check code and scope are required")

    @property
    def identity(self) -> tuple[str, str]:
        return self.code, self.scope


@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationReport:
    runtime_id: OnlyRuntimeId
    checks: tuple[OnlyPostRecoveryValidationCheck, ...]
    authority_fingerprint: str = ""

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.checks, key=lambda item: item.identity))
        identities = tuple(item.identity for item in ordered)
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate post-recovery validation check identity")
        object.__setattr__(self, "checks", ordered)
        payload = [
            {
                "actual": item.actual,
                "code": item.code,
                "detail": item.detail,
                "expected": item.expected,
                "scope": item.scope,
                "status": item.status.value,
            }
            for item in ordered
        ]
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if self.authority_fingerprint and self.authority_fingerprint != fingerprint:
            raise ValueError("post-recovery authority fingerprint mismatch")
        object.__setattr__(self, "authority_fingerprint", fingerprint)

    @property
    def passed(self) -> bool:
        return all(item.status is not OnlyPostRecoveryCheckStatus.FAILED for item in self.checks)


@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationContext:
    runtime_id: OnlyRuntimeId
    outcome: OnlyRuntimeRecoveryOutcome
    transaction_query: OnlyExecutionTransactionQueryPort
    ready_transaction_query: OnlyProjectionReadyExecutionQueryPort
    outbox_query: OnlyExecutionTransactionOutboxPort
    applied_projection_view: OnlyAppliedProjectionLedger
    runtime_boundary_view: OnlyRuntimeBoundaryAuthorityView
    orders: tuple[OnlyOrderSnapshot, ...] = ()
    positions: tuple[OnlyPositionSnapshot, ...] = ()
    allocations: tuple[OnlyPositionAllocationSnapshot, ...] = ()
    accounts: tuple[OnlyAccountSnapshot, ...] = ()
    strategy_ledgers: tuple[OnlyStrategyLedgerSnapshot, ...] = ()
    account_reservations: tuple[OnlyAccountReservation, ...] = ()
    position_reservations: tuple[OnlyPositionReservation, ...] = ()
    strategy_reservations: tuple[OnlyStrategyCashReservation, ...] = ()
    risk_reservations: tuple[OnlyRiskReservation, ...] = ()
    margin_reservations: tuple[OnlyMarginReservation, ...] = ()
    fee_records: tuple[OnlyFeeRecord, ...] = ()
    settlement_records: tuple[OnlySettlementRecord, ...] = ()
    margin_records: tuple[OnlyMarginRecord, ...] = ()
    broker_view: OnlyBrokerRecoveryAuthorityView | None = None
    ledger_reconciliation_violations: tuple[str, ...] = ()


class OnlyPostRecoveryAuthorityCheck(Protocol):
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]: ...


def _check(
    code: str, scope: str, passed: bool, expected: object, actual: object, detail: str
) -> OnlyPostRecoveryValidationCheck:
    return OnlyPostRecoveryValidationCheck(
        code,
        OnlyPostRecoveryCheckStatus.PASSED if passed else OnlyPostRecoveryCheckStatus.FAILED,
        scope,
        str(expected),
        str(actual),
        detail,
    )


class OnlyTransactionAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        records = context.transaction_query.records(context.runtime_id)
        ready = context.ready_transaction_query.ready_records(context.runtime_id)
        sequences = tuple(item.execution_sequence for item in records)
        expected = tuple(range(1, len(records) + 1))
        ids = tuple(item.transaction_id for item in records)
        updates = tuple(str(item.fact.broker_update_id) for item in records)
        trades = tuple(str(item.fact.trade_id) for item in records)
        ready_expected = tuple(item for item in records if item.projection_ready)
        return (
            _check(
                "POST_RECOVERY_TRANSACTION_SEQUENCE_GAP",
                "transactions",
                sequences == expected,
                expected,
                sequences,
                "transaction sequence must be contiguous",
            ),
            _check(
                "POST_RECOVERY_UNPROJECTED_TRANSACTION",
                "transactions",
                all(item.projection_ready for item in records),
                True,
                all(item.projection_ready for item in records),
                "every durable transaction must be projection ready",
            ),
            _check(
                "POST_RECOVERY_READY_SEQUENCE_MISMATCH",
                "transactions",
                (sequences[-1] if sequences else 0) == context.outcome.diagnostic.final_ready_sequence,
                context.outcome.diagnostic.final_ready_sequence,
                sequences[-1] if sequences else 0,
                "durable head must equal recovery outcome",
            ),
            _check(
                "POST_RECOVERY_DUPLICATE_TRANSACTION_ID",
                "transactions",
                len(ids) == len(set(ids)),
                "unique",
                ids,
                "transaction ids must be unique",
            ),
            _check(
                "POST_RECOVERY_DUPLICATE_BROKER_UPDATE_ID",
                "transactions",
                len(updates) == len(set(updates)),
                "unique",
                updates,
                "broker update ids must be unique",
            ),
            _check(
                "POST_RECOVERY_DUPLICATE_TRADE_ID",
                "transactions",
                len(trades) == len(set(trades)),
                "unique",
                trades,
                "trade ids must be unique",
            ),
            _check(
                "POST_RECOVERY_READY_QUERY_MISMATCH",
                "transactions",
                ready == ready_expected
                and context.ready_transaction_query.ready_count(context.runtime_id) == len(ready_expected),
                tuple(item.execution_sequence for item in ready_expected),
                tuple(item.execution_sequence for item in ready),
                "ready query must equal the ready subset of durable transactions",
            ),
        )


class OnlyOutboxAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        records = context.transaction_query.records(context.runtime_id)
        by_sequence = {item.execution_sequence: item for item in records}
        outbox = context.outbox_query.outbox_records(context.runtime_id)
        event_ids = tuple(str(item.event.event_id) for item in outbox)
        keys = tuple(
            (str(item.key.runtime_id), item.key.execution_sequence, item.key.event_sequence) for item in outbox
        )
        wrong_runtime = tuple(item.key for item in outbox if item.key.runtime_id != context.runtime_id)
        orphan = tuple(item.key for item in outbox if item.key.execution_sequence not in by_sequence)
        unready = tuple(
            item.key
            for item in outbox
            if item.key.execution_sequence in by_sequence
            and not by_sequence[item.key.execution_sequence].projection_ready
        )
        continuation = set()
        if (
            context.outcome.continuation_start_sequence is not None
            and context.outcome.continuation_end_sequence is not None
        ):
            continuation = set(
                range(context.outcome.continuation_start_sequence, context.outcome.continuation_end_sequence + 1)
            )
        continuation_rows = tuple(item for item in outbox if item.key.execution_sequence in continuation)
        present = {item.key.execution_sequence for item in continuation_rows}
        return (
            _check(
                "POST_RECOVERY_OUTBOX_ORPHAN",
                "outbox",
                not orphan,
                (),
                orphan,
                "outbox rows must reference durable transactions",
            ),
            _check(
                "POST_RECOVERY_OUTBOX_REFERENCES_UNREADY_TRANSACTION",
                "outbox",
                not unready,
                (),
                unready,
                "outbox rows must reference projection-ready transactions",
            ),
            _check(
                "POST_RECOVERY_DUPLICATE_OUTBOX_EVENT",
                "event-id",
                len(event_ids) == len(set(event_ids)),
                "unique",
                event_ids,
                "outbox event ids must be unique",
            ),
            _check(
                "POST_RECOVERY_DUPLICATE_OUTBOX_KEY",
                "outbox-key",
                len(keys) == len(set(keys)),
                "unique",
                keys,
                "durable outbox keys must be unique",
            ),
            _check(
                "POST_RECOVERY_OUTBOX_SCOPE_MISMATCH",
                "outbox-runtime",
                not wrong_runtime,
                context.runtime_id,
                wrong_runtime,
                "outbox key Runtime must equal validation Runtime",
            ),
            _check(
                "POST_RECOVERY_CONTINUATION_OUTBOX_MISSING",
                "continuation",
                present == continuation,
                tuple(sorted(continuation)),
                tuple(sorted(present)),
                "every continuation transaction needs durable outbox",
            ),
            _check(
                "POST_RECOVERY_CONTINUATION_OUTBOX_PREMATURELY_PUBLISHED",
                "continuation",
                all(not item.published for item in continuation_rows),
                False,
                any(item.published for item in continuation_rows),
                "continuation outbox cannot publish before finalization",
            ),
            _check(
                "POST_RECOVERY_OUTBOX_PENDING_COUNT_MISMATCH",
                "outbox",
                context.outbox_query.pending_count(context.runtime_id)
                == sum(not item.published and item.projection_ready for item in outbox),
                sum(not item.published and item.projection_ready for item in outbox),
                context.outbox_query.pending_count(context.runtime_id),
                "pending count must match rows",
            ),
        )


class OnlyRecoveredProjectionRangeCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        starts = tuple(
            item
            for item in (context.outcome.persisted_tail_start_sequence, context.outcome.continuation_start_sequence)
            if item is not None
        )
        ends = tuple(
            item
            for item in (context.outcome.persisted_tail_end_sequence, context.outcome.continuation_end_sequence)
            if item is not None
        )
        if not starts:
            return (
                OnlyPostRecoveryValidationCheck(
                    "POST_RECOVERY_APPLIED_PROJECTION_RANGE_MISMATCH",
                    OnlyPostRecoveryCheckStatus.NOT_APPLICABLE,
                    "recovery-range",
                    None,
                    None,
                    "recovery range is empty",
                ),
            )
        records = context.transaction_query.records(context.runtime_id, after_sequence=min(starts) - 1)
        records = tuple(item for item in records if item.execution_sequence <= max(ends))
        missing: list[str] = []
        hashes: list[str] = []
        for transaction in records:
            for projection in transaction.projections:
                actual = context.applied_projection_view.get(
                    transaction.execution_sequence, projection.identity.component
                )
                scope = f"{transaction.execution_sequence}:{projection.identity.component.value}"
                if actual is None or actual.transaction_id != transaction.transaction_id:
                    missing.append(scope)
                elif (
                    actual.payload_hash != projection.identity.payload_hash
                    or actual.result_state_hash != projection.identity.result_state_hash
                ):
                    hashes.append(scope)
        return (
            _check(
                "POST_RECOVERY_APPLIED_PROJECTION_RANGE_MISMATCH",
                "recovery-range",
                not missing,
                (),
                tuple(missing),
                "recovery projections need applied records",
            ),
            _check(
                "POST_RECOVERY_APPLIED_PROJECTION_HASH_MISMATCH",
                "recovery-range",
                not hashes,
                (),
                tuple(hashes),
                "applied hashes must equal durable projections",
            ),
        )


class OnlyPositionAllocationAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        def position_scope(item: OnlyPositionSnapshot) -> tuple[str, str, str]:
            return str(item.key.account_id), str(item.key.instrument_id), item.key.position_side.value

        positions = {position_scope(item): item for item in context.positions}
        allocation_totals: dict[tuple[str, str, str], Decimal] = {}
        orphan: list[str] = []
        for allocation in context.allocations:
            scope = (
                str(allocation.key.account_id),
                str(allocation.key.instrument_id),
                allocation.key.position_side.value,
            )
            if scope not in positions:
                orphan.append(str(allocation.key))
            allocation_totals[scope] = allocation_totals.get(scope, Decimal(0)) + allocation.total_quantity.value
        mismatches = tuple(
            scope for scope, item in positions.items() if allocation_totals.get(scope, 0) != item.total_quantity.value
        )
        invalid = tuple(
            str(item.key)
            for item in context.positions
            if item.total_quantity.value < 0
            or item.available_quantity.value < 0
            or item.order_frozen_quantity.value + item.risk_reserved_quantity.value + item.restricted_quantity.value
            > item.total_quantity.value
        )
        return (
            _check(
                "POST_RECOVERY_POSITION_ALLOCATION_QUANTITY_MISMATCH",
                "positions",
                not mismatches,
                (),
                mismatches,
                "position total must equal allocations",
            ),
            _check(
                "POST_RECOVERY_POSITION_QUANTITY_INVARIANT_FAILED",
                "positions",
                not invalid,
                (),
                invalid,
                "position quantities must remain non-negative and bounded",
            ),
            _check(
                "POST_RECOVERY_ORPHAN_ALLOCATION",
                "allocations",
                not orphan,
                (),
                tuple(orphan),
                "allocation requires account position",
            ),
        )


class OnlyOrderReservationAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        terminal = {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.EXPIRED,
            OnlyOrderStatus.FILLED,
            OnlyOrderStatus.REJECTED,
            OnlyOrderStatus.FAILED,
        }
        all_orders = {item.order_id: item for item in context.orders}
        open_orders = {order_id: order for order_id, order in all_orders.items() if order.status not in terminal}
        terminal_order_ids = set(all_orders) - set(open_orders)
        account = {
            item.order_id: item
            for item in context.account_reservations
            if item.state.value in {"ACTIVE", "PARTIALLY_CONSUMED"}
        }
        position = {
            item.order_id: item
            for item in context.position_reservations
            if item.state.value in {"ACTIVE", "PARTIALLY_CONSUMED"}
        }
        margin = {item.source_order_id: item for item in context.margin_reservations if item.reserved or item.occupied}
        strategy = {
            item.order_id: item
            for item in context.strategy_reservations
            if item.state.value in {"ACTIVE", "PARTIALLY_CONSUMED"}
        }
        risk = {item.order_id: item for item in context.risk_reservations if item.state.value == "ACTIVE"}
        missing = tuple(
            str(order_id)
            for order_id, order in open_orders.items()
            if order.side.value == "BUY"
            and (order_id not in account or order_id not in strategy or order_id not in risk)
        )
        maps = (
            ("account", account),
            ("strategy", strategy),
            ("position", position),
            ("risk", risk),
            ("margin", margin),
        )
        orphan = tuple(
            sorted(f"{kind}:{order_id}" for kind, items in maps for order_id in set(items) - set(all_orders))
        )
        terminal_active = tuple(
            sorted(f"{kind}:{order_id}" for kind, items in maps for order_id in set(items) & terminal_order_ids)
        )
        account_snapshots = {item.account_id: item for item in context.accounts}
        scoped: list[str] = []
        currency: list[str] = []
        for order_id, order in all_orders.items():
            if order_id in account:
                account_item = account[order_id]
                if (
                    account_item.runtime_id != order.runtime_id
                    or account_item.account_id != order.account_id
                    or account_item.order_id != order.order_id
                ):
                    scoped.append(f"account:{order_id}")
                snapshot = account_snapshots.get(order.account_id)
                if snapshot is not None and account_item.reserved_amount.currency != snapshot.base_currency:
                    currency.append(f"account:{order_id}")
            if order_id in strategy:
                strategy_item = strategy[order_id]
                if (
                    strategy_item.key.runtime_id != order.runtime_id
                    or strategy_item.key.account_id != order.account_id
                    or strategy_item.key.cluster_id != order.cluster_id
                    or strategy_item.order_id != order.order_id
                ):
                    scoped.append(f"strategy:{order_id}")
                snapshot = account_snapshots.get(order.account_id)
                if snapshot is not None and strategy_item.key.base_currency != snapshot.base_currency:
                    currency.append(f"strategy:{order_id}")
            if order_id in risk:
                risk_item = risk[order_id]
                if (
                    risk_item.runtime_id != order.runtime_id
                    or risk_item.account_id != order.account_id
                    or risk_item.cluster_id != order.cluster_id
                    or risk_item.instrument_id != order.instrument_id
                    or risk_item.order_id != order.order_id
                ):
                    scoped.append(f"risk:{order_id}")
            if order_id in position:
                position_item = position[order_id]
                if (
                    position_item.runtime_id != order.runtime_id
                    or position_item.account_id != order.account_id
                    or position_item.cluster_id != order.cluster_id
                    or position_item.instrument_id != order.instrument_id
                    or position_item.order_id != order.order_id
                    or position_item.quantity.precision != order.quantity.precision
                    or position_item.quantity.value > order.quantity.value
                ):
                    scoped.append(f"position:{order_id}")
            if order_id in margin:
                margin_item = margin[order_id]
                if (
                    margin_item.runtime_id != order.runtime_id
                    or margin_item.account_id != order.account_id
                    or margin_item.instrument_id != order.instrument_id
                    or margin_item.source_order_id != order.order_id
                ):
                    scoped.append(f"margin:{order_id}")
                snapshot = account_snapshots.get(order.account_id)
                if snapshot is not None and margin_item.currency != snapshot.base_currency:
                    currency.append(f"margin:{order_id}")
        return (
            _check(
                "POST_RECOVERY_OPEN_ORDER_RESERVATION_MISSING",
                "orders",
                not missing,
                (),
                missing,
                "open BUY orders require cash reservation",
            ),
            _check(
                "POST_RECOVERY_ORPHAN_RESERVATION",
                "reservations",
                not orphan,
                (),
                orphan,
                "active reservation requires non-terminal order",
            ),
            _check(
                "POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION",
                "reservations-terminal",
                not terminal_active,
                (),
                terminal_active,
                "terminal orders cannot retain active reservations",
            ),
            _check(
                "POST_RECOVERY_RESERVATION_SCOPE_MISMATCH",
                "reservations",
                not scoped,
                (),
                tuple(scoped),
                "reservation scope must equal its order",
            ),
            _check(
                "POST_RECOVERY_RESERVATION_CURRENCY_MISMATCH",
                "reservation-currency",
                not currency,
                (),
                tuple(currency),
                "cash and margin reservation currency must equal Account base currency",
            ),
        )


class OnlyAccountLedgerAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        active_by_account: dict[str, Decimal] = {}
        for reservation in context.account_reservations:
            if reservation.state.value not in {"ACTIVE", "PARTIALLY_CONSUMED"}:
                continue
            account_id = str(reservation.account_id)
            active_by_account[account_id] = (
                active_by_account.get(account_id, Decimal(0)) + reservation.remaining_amount.amount
            )
        reservation_mismatch = tuple(
            str(account.account_id)
            for account in context.accounts
            if active_by_account.get(str(account.account_id), Decimal(0)) != account.cash.frozen_cash.amount
        )
        return (
            _check(
                "POST_RECOVERY_ACCOUNT_LEDGER_MISMATCH",
                "runtime-ledgers",
                not context.ledger_reconciliation_violations,
                (),
                context.ledger_reconciliation_violations,
                "runtime ledger reconciliation must pass",
            ),
            _check(
                "POST_RECOVERY_ACCOUNT_RESERVATION_MISMATCH",
                "accounts",
                not reservation_mismatch,
                (),
                reservation_mismatch,
                "account frozen cash must equal active cash reservations",
            ),
        )


class OnlyFeeSettlementMarginAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        records = context.transaction_query.records(context.runtime_id)
        fee_keys = {item.instruction_id for item in context.fee_records}
        settlement_keys = {item.instruction_id for item in context.settlement_records}
        fact_by_fee = {item.fact.fee_instruction_id: item.fact for item in records}
        fact_by_settlement = {item.fact.settlement_instruction_id: item.fact for item in records}
        missing_fee = tuple(item.execution_sequence for item in records if item.fact.fee_instruction_id not in fee_keys)
        missing_settlement = tuple(
            item.execution_sequence for item in records if item.fact.settlement_instruction_id not in settlement_keys
        )
        invalid_margin = tuple(
            item.sequence
            for item in context.margin_records
            if min(item.amount, item.reserved_after, item.occupied_after, item.maintenance_required_after) < 0
        )
        fee_totals = {
            instruction_id: sum(
                (item.charged for item in context.fee_records if item.instruction_id == instruction_id), Decimal(0)
            )
            for instruction_id in fee_keys
        }
        fee_mismatch = tuple(
            item.execution_sequence
            for item in records
            if fee_totals.get(item.fact.fee_instruction_id, Decimal(0)) != item.fact.authoritative_fee_total.amount
        )
        fee_scope = tuple(
            item.fee_record_id
            for item in context.fee_records
            if (fact := fact_by_fee.get(item.instruction_id)) is not None
            and (
                item.account_id != str(fact.account_id)
                or item.instrument_id != str(fact.instrument_id)
                or item.order_id != str(fact.order_id)
                or item.trade_id != str(fact.trade_id)
                or item.currency != fact.currency.code
            )
        )
        orphan_fee = tuple(item.fee_record_id for item in context.fee_records if item.instruction_id not in fact_by_fee)
        settlement_scope = tuple(
            item.instruction_id
            for item in context.settlement_records
            if (fact := fact_by_settlement.get(item.instruction_id)) is not None
            and (
                item.account_id != str(fact.account_id)
                or item.instrument_id != str(fact.instrument_id)
                or item.source_order_id != str(fact.order_id)
                or item.source_trade_id != str(fact.trade_id)
                or item.legal_settlement_date != fact.legal_settlement_date
            )
        )
        orphan_settlement = tuple(
            item.instruction_id for item in context.settlement_records if item.instruction_id not in fact_by_settlement
        )
        settlement_state = tuple(
            item.instruction_id
            for item in context.settlement_records
            if (item.legal_settled and item.status != "SETTLED")
            or (not item.legal_settled and item.status not in {"BOOKED", "PENDING"})
            or (item.status == "SETTLED" and not item.legal_settled)
        )
        margin_applicable = any(item.fact.margin_instruction_id is not None for item in records)
        active_margin = tuple(item for item in context.margin_reservations if item.reserved or item.occupied)
        margin_applicable = (
            margin_applicable
            or bool(context.margin_records or context.margin_reservations)
            or any(item.reserved_margin is not None for item in context.accounts)
        )
        margin_check = (
            _check(
                "POST_RECOVERY_MARGIN_STATE_MISMATCH",
                "margin",
                not invalid_margin,
                (),
                invalid_margin,
                "margin authority cannot be negative",
            )
            if margin_applicable or context.margin_records or context.margin_reservations
            else OnlyPostRecoveryValidationCheck(
                "POST_RECOVERY_MARGIN_STATE_MISMATCH",
                OnlyPostRecoveryCheckStatus.NOT_APPLICABLE,
                "margin",
                None,
                None,
                "margin is not enabled for generic T0 cash recovery",
            )
        )
        margin_totals: dict[tuple[str, str], tuple[Decimal, Decimal, Decimal]] = {}
        for item in active_margin:
            key = str(item.account_id), item.currency.code
            before = margin_totals.get(key, (Decimal(0), Decimal(0), Decimal(0)))
            margin_totals[key] = (
                before[0] + item.reserved,
                before[1] + item.occupied,
                before[2] + item.released,
            )
        margin_account_mismatch: list[str] = []
        for account in context.accounts:
            if account.reserved_margin is None:
                continue
            assert account.occupied_margin is not None and account.released_margin is not None
            key = str(account.account_id), account.base_currency.code
            totals = margin_totals.get(key, (Decimal(0), Decimal(0), Decimal(0)))
            wrong_currency = any(
                str(item.account_id) == str(account.account_id) and item.currency != account.base_currency
                for item in active_margin
            )
            if wrong_currency or totals != (
                account.reserved_margin.amount,
                account.occupied_margin.amount,
                account.released_margin.amount,
            ):
                margin_account_mismatch.append(str(account.account_id))
        margin_account_check = (
            _check(
                "POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH",
                "margin-account",
                not margin_account_mismatch,
                (),
                tuple(margin_account_mismatch),
                "active margin reservations must equal Account margin authority",
            )
            if margin_applicable
            else OnlyPostRecoveryValidationCheck(
                "POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH",
                OnlyPostRecoveryCheckStatus.NOT_APPLICABLE,
                "margin-account",
                None,
                None,
                "margin is not enabled for generic T0 cash recovery",
            )
        )
        return (
            _check(
                "POST_RECOVERY_FEE_RECORD_MISSING",
                "fees",
                not missing_fee,
                (),
                missing_fee,
                "ready transactions require fee authority",
            ),
            _check(
                "POST_RECOVERY_FEE_TOTAL_MISMATCH",
                "fees",
                not fee_mismatch,
                (),
                fee_mismatch,
                "fee records must reduce to the committed fee total",
            ),
            _check(
                "POST_RECOVERY_FEE_SCOPE_MISMATCH",
                "fee-scope",
                not fee_scope,
                (),
                fee_scope,
                "fee record scope must equal its committed transaction",
            ),
            _check(
                "POST_RECOVERY_ORPHAN_FEE_RECORD",
                "fee-orphan",
                not orphan_fee,
                (),
                orphan_fee,
                "fee records require a durable transaction",
            ),
            _check(
                "POST_RECOVERY_SETTLEMENT_RECORD_MISSING",
                "settlement",
                not missing_settlement,
                (),
                missing_settlement,
                "ready transactions require settlement authority",
            ),
            _check(
                "POST_RECOVERY_SETTLEMENT_SCOPE_MISMATCH",
                "settlement-scope",
                not settlement_scope,
                (),
                settlement_scope,
                "settlement record scope must equal its committed transaction",
            ),
            _check(
                "POST_RECOVERY_ORPHAN_SETTLEMENT_RECORD",
                "settlement-orphan",
                not orphan_settlement,
                (),
                orphan_settlement,
                "settlement records require a durable transaction",
            ),
            _check(
                "POST_RECOVERY_SETTLEMENT_STATE_MISMATCH",
                "settlement-state",
                not settlement_state,
                (),
                settlement_state,
                "settlement status and legal-settled flag must agree",
            ),
            margin_check,
            margin_account_check,
        )


class OnlyBrokerLocalParityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        if context.broker_view is None:
            return (
                OnlyPostRecoveryValidationCheck(
                    "POST_RECOVERY_BROKER_ORDER_MISMATCH",
                    OnlyPostRecoveryCheckStatus.NOT_APPLICABLE,
                    "broker",
                    None,
                    None,
                    "broker recovery query is not applicable",
                ),
            )
        local_orders = {str(item.order_id): item for item in context.orders}
        broker_orders = {str(item.order_id): item for item in context.broker_view.orders()}
        local = set(local_orders)
        broker = set(broker_orders)

        def broker_order_matches(order_id: str) -> bool:
            broker_order = broker_orders[order_id]
            local_order = local_orders[order_id]
            scope_matches = (
                broker_order.account_id == local_order.account_id
                and broker_order.instrument_id == str(local_order.instrument_id)
                and broker_order.side == local_order.side.value
                and broker_order.quantity == local_order.quantity
                and broker_order.limit_price == local_order.price
            )
            exact = (
                broker_order.status == local_order.status.value
                and broker_order.filled_quantity == local_order.filled_quantity
                and broker_order.remaining_quantity == local_order.remaining_quantity
            )
            # A checkpointable deterministic Broker may have executed a Fill whose durable
            # PUBLISH_FILL action is still pending. Its own restore validator proves that
            # Trade/Plan/Scheduler authority; local Runtime authority is therefore allowed
            # to trail, but must never be ahead or disagree on immutable order scope.
            broker_ahead = (
                local_order.status in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}
                and broker_order.status in {OnlyOrderStatus.PARTIALLY_FILLED.value, OnlyOrderStatus.FILLED.value}
                and broker_order.filled_quantity.value >= local_order.filled_quantity.value
                and broker_order.remaining_quantity.value <= local_order.remaining_quantity.value
            )
            return scope_matches and (exact or broker_ahead)

        mismatched = tuple(order_id for order_id in sorted(local & broker) if not broker_order_matches(order_id))
        behind_items: list[str] = []
        for order_id in sorted(local & broker):
            broker_sequence = broker_orders[order_id].broker_sequence
            local_sequence = local_orders[order_id].last_external_sequence
            if broker_sequence is not None and local_sequence is not None and broker_sequence < local_sequence:
                behind_items.append(order_id)
        behind = tuple(behind_items)
        return (
            _check(
                "POST_RECOVERY_BROKER_ORDER_MISMATCH",
                "broker",
                local == broker and not mismatched,
                tuple(sorted(local)),
                (tuple(sorted(broker)), mismatched),
                "broker and local order authority must agree",
            ),
            _check(
                "POST_RECOVERY_BROKER_ORDER_SEQUENCE_BEHIND",
                "broker",
                not behind,
                (),
                behind,
                "broker order sequence cannot trail local authority",
            ),
        )


class OnlyRuntimeBoundaryAuthorityCheck:
    def evaluate(self, context: OnlyPostRecoveryValidationContext) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        view = context.runtime_boundary_view
        boundary = context.outcome.final_boundary
        cursor_matches = boundary is None or (
            view.replay_cursor.source_id == boundary.source_id
            and view.replay_cursor.data_version == boundary.data_version
            and view.replay_cursor.last_update_id == boundary.update_id
            and view.replay_cursor.last_source_sequence == boundary.source_sequence
            and view.replay_cursor.last_event_time == boundary.ts_event
        )
        clock_ok = boundary is None or view.clock_time >= boundary.ts_event
        return (
            _check(
                "POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY",
                "inbound",
                view.broker_inbound_count == 0 and view.market_data_inbound_count == 0,
                (0, 0),
                (view.broker_inbound_count, view.market_data_inbound_count),
                "inbound queues must be empty",
            ),
            _check(
                "POST_RECOVERY_EVENT_BUS_NOT_DRAINED",
                "event-bus",
                view.event_bus_pending_count == 0,
                0,
                view.event_bus_pending_count,
                "event bus must be drained",
            ),
            _check(
                "POST_RECOVERY_CURSOR_BOUNDARY_MISMATCH",
                "cursor",
                cursor_matches,
                boundary,
                view.replay_cursor,
                "cursor must equal exact final boundary",
            ),
            _check(
                "POST_RECOVERY_RESULT_COUNT_CURSOR_MISMATCH",
                "result-count",
                view.processed_bar_count == view.replay_cursor.processed_bar_count,
                view.replay_cursor.processed_bar_count,
                view.processed_bar_count,
                "bar counts must agree",
            ),
            _check(
                "POST_RECOVERY_PROCESSING_SEQUENCE_MISMATCH",
                "processing-sequence",
                view.last_market_processing_sequence == view.market_processing_sequence,
                view.market_processing_sequence,
                view.last_market_processing_sequence,
                "processing sequences must agree",
            ),
            _check(
                "POST_RECOVERY_CLOCK_BEHIND_BOUNDARY",
                "clock",
                clock_ok,
                None if boundary is None else boundary.ts_event,
                view.clock_time,
                "clock cannot precede recovery boundary",
            ),
        )


class OnlyPostRecoveryAuthorityValidator:
    def __init__(self, checks: tuple[OnlyPostRecoveryAuthorityCheck, ...]) -> None:
        if not checks:
            raise ValueError("post-recovery validator requires checks")
        self._checks = checks

    def validate(self, context: OnlyPostRecoveryValidationContext) -> OnlyPostRecoveryValidationReport:
        checks = tuple(item for authority_check in self._checks for item in authority_check.evaluate(context))
        return OnlyPostRecoveryValidationReport(context.runtime_id, checks)


def only_default_post_recovery_authority_validator() -> OnlyPostRecoveryAuthorityValidator:
    return OnlyPostRecoveryAuthorityValidator(
        (
            OnlyTransactionAuthorityCheck(),
            OnlyOutboxAuthorityCheck(),
            OnlyRecoveredProjectionRangeCheck(),
            OnlyPositionAllocationAuthorityCheck(),
            OnlyOrderReservationAuthorityCheck(),
            OnlyAccountLedgerAuthorityCheck(),
            OnlyFeeSettlementMarginAuthorityCheck(),
            OnlyBrokerLocalParityCheck(),
            OnlyRuntimeBoundaryAuthorityCheck(),
        )
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_default_")]
