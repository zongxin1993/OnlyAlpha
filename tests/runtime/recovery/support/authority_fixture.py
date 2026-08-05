from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
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
from onlyalpha.settlement.models import OnlySettlementInstructionSnapshot, OnlySettlementInstructionStatus
from onlyalpha.transaction.applied_projection import OnlyInMemoryAppliedRuntimeProjectionLedger
from onlyalpha.transaction.projection import OnlySettlementExecutionProjection
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_prepared_transaction


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
        settlement_records: tuple[OnlySettlementInstructionSnapshot, ...] = ()
        covered_sequence = 0
        if with_transaction:
            prepared = only_test_generic_t0_prepared_transaction()
            runtime_id = prepared.runtime_id
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
            settlement_projection = next(
                item for item in prepared.projections if isinstance(item, OnlySettlementExecutionProjection)
            )
            settlement_state = settlement_projection.after
            assert settlement_state.instruction is not None
            settlement_records = (
                OnlySettlementInstructionSnapshot(
                    settlement_state.instruction,
                    True,
                    settlement_state.asset_released,
                    True,
                    settlement_state.trade_cash_released,
                    settlement_state.withdrawable_cash_released,
                    settlement_state.legal_settled,
                    OnlySettlementInstructionStatus.COMPLETED,
                    settlement_state.version,
                    settlement_state.record_sequence_head,
                    None,
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
            OnlyInMemoryAppliedRuntimeProjectionLedger(),
            OnlyRuntimeBoundaryAuthorityView(runtime_id, 0, 0, 0, cursor, 0, 0, 0, timestamp),
            fee_records=fee_records,
            settlement_records=settlement_records,
        )
        return cls(runtime_id, cursor, outcome, store, context)

    def context(self, **overrides: object) -> OnlyPostRecoveryValidationContext:
        return replace(self._context, **dict[str, Any](overrides))
