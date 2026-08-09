# P4.2 Broker-Driven Order Lifecycle Pre-Implementation Audit

Date: 2026-08-09

## Baseline

- Prompt baseline: `8ec5359470de3b7853a78e63c1a6fb88d9e227dd`
- Actual implementation baseline: `8ec5359470de3b7853a78e63c1a6fb88d9e227dd`
- `origin/master` was fetched before the audit and is identical to `HEAD`.
- Baseline differences: none.

## Authority ownership

Runtime owns every mutable authority. Manager command methods are local command-side orchestration APIs; they are not valid
projection installation APIs. The Runtime Transaction Store is the durable Broker-driven fact authority. Applied Projection
Ledger is the idempotent installation index.

## Existing Broker lifecycle matrix

The matrix below is derived from `OnlyExecutionProcessor`, `OnlyOrderUpdateProcessor`, the Reservation adapters, and Manager
implementations at the actual baseline. “Direct” means mutation occurs before any durable Store commit.

| Broker fact | BUY OPEN | SELL CLOSE |
|---|---|---|
| ACCEPTED | Direct `ORDER`. The current execution wrapper suppresses cash coordination, so Account cash does not change and Strategy cash ACK is accidentally skipped. | Direct `ORDER`; then Position Reservation `acknowledged`, which advances its stage and releases the account-level Position duplicate freeze. Allocation hold remains. |
| TRADE | Durable `ORDER, POSITION, ALLOCATION, SETTLEMENT, ORDER_FEE_ACCRUAL, FEE_LEDGER, ACCOUNT, STRATEGY_LEDGER, ACCOUNT_CASH_RESERVATION, STRATEGY_CASH_RESERVATION, RISK_RESERVATION, RISK, VALUATION` as applicable. | Same durable protocol, with Position Reservation instead of cash Reservations and exact close-cost authority. |
| CANCELLED | Direct `ORDER, ACCOUNT, STRATEGY_LEDGER, ACCOUNT_CASH_RESERVATION, STRATEGY_CASH_RESERVATION, RISK_RESERVATION, RISK`. | Durable only for the exact supported close shape; declared projections are `ORDER, POSITION_RESERVATION, RISK_RESERVATION, RISK`, but Position/Allocation are hidden mutations inside the Position Reservation target. |
| REJECTED | Same direct BUY authority set. Reject-before-ACK is accepted by the Order state machine. | Same durable/hidden-mutation shape as Cancel. |
| EXPIRED | Same direct BUY authority set. | Same durable/hidden-mutation shape as Cancel. |

## Stage-dependent SELL CLOSE authority

| Boundary | Position | Allocation | Position Reservation |
|---|---|---|---|
| Before Broker ACK (`LOCAL_ONLY` or `SENT_TO_BROKER`) | Contains the local account-level hold for the remaining quantity. | Contains the Cluster allocation hold for the remaining quantity. | Active, remaining quantity retained. |
| After Broker ACK (`BROKER_ACKNOWLEDGED`) | The local duplicate hold has been released. | Hold remains to prevent cross-Cluster oversell. | Stage records Broker acknowledgement. |
| After partial Fill | Position quantity/cost reflect committed fills; an unacknowledged local hold is consumed only by its exact fill delta. | Quantity/cost and hold reflect committed fill deltas. | `consumed + released + remaining == original`; only remaining may later be terminally released. |

Therefore a terminal before ACK must explicitly project `POSITION` and `ALLOCATION`; a terminal after ACK must project
`ALLOCATION` but must not release Position again. In both cases Position Reservation records the exact remaining release.

## Hidden mutation audit

- `OnlyPositionReservationManager.advance_stage(...BROKER_ACKNOWLEDGED...)` also calls `OnlyPositionManager.release()`.
- `OnlyPositionReservationManager.consume()` can call both `OnlyPositionManager.release()` and
  `OnlyPositionAllocationManager.release()`.
- `OnlyPositionReservationManager.release()` can call both `OnlyPositionManager.release()` and
  `OnlyPositionAllocationManager.release()`.
- `OnlyPositionReservationExecutionProjectionTarget` calls `release()` before restoring its declared Reservation state. This
  makes the declared projection set incomplete and makes replay depend on relative mutation.
- `OnlyAccountManager.release_cash()` changes both Account aggregate cash authority and Account cash Reservation.
- `OnlyStrategyLedgerManager.release_cash_reservation()` changes both Strategy Ledger aggregate authority and Strategy cash
  Reservation.
- `OnlyRiskService.release_order()` changes Risk Reservation and Risk snapshot.
- `OnlyOrderUpdateProcessor(coordinate_reservations=True)` coordinates Order, Position/Cash Reservation, and Risk authorities.

The command-side create/submit cleanup paths remain outside P4.2. Projection targets must use absolute restore/install APIs only.

## Persistence and recovery audit

- `TRADE_FILL` and SELL CLOSE `ORDER_TERMINAL` use the shared Prepared/Committed Runtime Transaction, Store, ordered Projection,
  durable Outbox, Applied Projection Ledger, and forward recovery.
- ACCEPTED is currently classified as non-transactional and can pass through `replay_non_transaction()`.
- Terminal lookup duplicates `get_by_transaction_id()` because terminal identity is the transaction ID; it has no independent
  business index requirement.
- Stored committed facts are replayed directly and are not re-authorized by the current support resolver. This behavior is
  correct and must remain.

## Version audit

`ONLY_EXECUTION_SUPPORT_POLICY_VERSION` is a policy version, but `OnlyExecutionSupportDecision.schema_version` and committed
facts' `execution_support_policy_version` misname it as a data schema. P4.2 must rename these to `policy_version` and
`execution_support_policy_version`, remove the old names without aliases, and advance policy to `2` only when Accepted and both
Terminal shapes are durable.

## Required cutover

The supported lifecycle must become:

```text
Broker fact -> stable identity/fingerprint -> frozen before authority -> one support decision
            -> pure planner -> complete projections/preconditions -> durable commit
            -> ordered absolute installation -> forward recovery
```

No supported Accepted/Trade/Terminal update may enter `_dispatch` economic mutation. Unsupported economic shapes fail closed.
Connection, Account snapshot, and Position reconciliation updates remain non-transactional because they are not the P4.2 Order
lifecycle.

## Non-scope

Broker submit/cancel command durability, command retry/idempotency, Margin/Short/Hedging, new market rules, fee-kernel redesign,
Production A-share E2E, and exactly-once subscriber delivery are not part of P4.2.
