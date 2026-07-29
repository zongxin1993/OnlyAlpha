from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.applied_projection import OnlyInMemoryAppliedProjectionLedger
from onlyalpha.fee.manager import OnlyFeeRecord
from onlyalpha.runtime.checkpoint.codec import only_seal_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
    OnlyBacktestReplayCursor,
    OnlyRuntimeCheckpointHeader,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.recovery.authority_views import OnlyRuntimeBoundaryAuthorityView
from onlyalpha.runtime.recovery.orchestrator import OnlyRuntimeRecoveryDiagnostic, OnlyRuntimeRecoveryStatus
from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome
from onlyalpha.runtime.recovery.validation import OnlyPostRecoveryValidationContext
from onlyalpha.settlement.manager import OnlySettlementRecord
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction


@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryAuthorityFixture:
    runtime_id: OnlyRuntimeId
    cursor: OnlyBacktestReplayCursor
    outcome: OnlyRuntimeRecoveryOutcome
    store: OnlyInMemoryRuntimePersistenceStore
    _context: OnlyPostRecoveryValidationContext

    @classmethod
    def create(cls, *, with_transaction: bool = False) -> OnlyPostRecoveryAuthorityFixture:
        runtime_id = OnlyRuntimeId("runtime")
        timestamp = OnlyTimestamp.from_unix_nanos(1)
        cursor = OnlyBacktestReplayCursor(
            OnlyMarketDataSourceId("source"), OnlyDataVersion("version"), None, 0, None, 0
        )
        store = OnlyInMemoryRuntimePersistenceStore()
        fee_records: tuple[OnlyFeeRecord, ...] = ()
        settlement_records: tuple[OnlySettlementRecord, ...] = ()
        covered_sequence = 0
        if with_transaction:
            prepared = only_test_generic_t0_cash_buy_open_transaction(runtime_id=runtime_id)
            committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction
            store.mark_projection_ready(runtime_id, 1, projected_at=prepared.prepared_at)
            fact = committed.fact
            fee_records = tuple(
                OnlyFeeRecord(
                    f"fee-{sequence}",
                    fact.fee_instruction_id,
                    fact.fee_instruction_id,
                    str(fact.account_id),
                    str(fact.instrument_id),
                    str(fact.order_id),
                    str(fact.trade_id),
                    component.fee_type.value,
                    component.authority.value,
                    component.status.value,
                    component.amount.amount,
                    component.amount.amount,
                    component.amount.currency.code,
                    component.schedule_id,
                    component.schedule_version,
                    sequence,
                )
                for sequence, component in enumerate(fact.fee_breakdown.components, start=1)
            )
            if not fee_records:
                fee_records = (
                    OnlyFeeRecord(
                        "fee-1",
                        fact.fee_instruction_id,
                        fact.fee_instruction_id,
                        str(fact.account_id),
                        str(fact.instrument_id),
                        str(fact.order_id),
                        str(fact.trade_id),
                        "NONE",
                        fact.fee_authority,
                        fact.fee_status,
                        Decimal(0),
                        Decimal(0),
                        fact.currency.code,
                        None,
                        None,
                        1,
                    ),
                )
            settlement_records = (
                OnlySettlementRecord(
                    fact.settlement_instruction_id,
                    str(fact.instrument_id),
                    str(fact.trade_id),
                    fact.fill_quantity.value,
                    fact.settled_notional.amount,
                    fact.fill_quantity.value,
                    Decimal(0),
                    Decimal(0),
                    Decimal(0),
                    False,
                    fact.trading_day,
                    1,
                    str(fact.account_id),
                    str(fact.order_id),
                    fact.legal_settlement_date,
                    "BOOKED",
                ),
            )
            covered_sequence = 1
        checkpoint = only_seal_runtime_checkpoint(
            OnlyRuntimeCheckpointHeader(
                runtime_id,
                1,
                covered_sequence,
                ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
                timestamp,
                cursor,
                "config",
                "registry",
                "pending",
            ),
            (),
        )
        diagnostic = OnlyRuntimeRecoveryDiagnostic(
            OnlyRuntimeRecoveryStatus.RESTORED,
            1,
            covered_sequence,
            0,
            0,
            0,
            0,
            0,
            covered_sequence,
            store.pending_count(runtime_id),
            0,
            0,
            None,
        )
        outcome = OnlyRuntimeRecoveryOutcome(checkpoint, diagnostic, None, None, None, None, None, False)
        context = OnlyPostRecoveryValidationContext(
            runtime_id,
            outcome,
            store,
            store,
            store,
            OnlyInMemoryAppliedProjectionLedger(),
            OnlyRuntimeBoundaryAuthorityView(runtime_id, 0, 0, 0, cursor, 0, 0, 0, timestamp),
            fee_records=fee_records,
            settlement_records=settlement_records,
        )
        return cls(runtime_id, cursor, outcome, store, context)

    def context(self, **overrides: object) -> OnlyPostRecoveryValidationContext:
        return replace(self._context, **dict[str, Any](overrides))
