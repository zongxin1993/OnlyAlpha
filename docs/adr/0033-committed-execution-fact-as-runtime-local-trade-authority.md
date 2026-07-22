# ADR 0033: Committed Execution Fact as Runtime Local Trade Authority

- Status: Accepted
- Date: 2026-07-22

## Context

A Broker Trade Update is an external report. It can be duplicated, stale, out of order, scoped to an unknown order, omit
fees, or arrive while the local transaction fails. The former Applied Trade Fact retained mainly Fill input and therefore
could not prove the fee, position scope, multiplier/notional, settlement, margin, rule identity, attribution, or actual
state deltas accepted by Runtime. Result code consequently had to query mutable state or invent missing zero values.

## Decision

`OnlyCommittedExecutionFact` is the immutable, self-contained authority for one successfully committed local execution.
It contains stable identities and sequences; event/commit timestamps; explicit order and position scope; exact economic
values; authoritative and reported fee evidence; fee schedule identities; compiled market-rule identity; settlement and
margin instruction outcomes; and the transaction's Position, Allocation, Account and Strategy Ledger deltas. It does not
contain Managers, mutable entities, complete Account/Position/Ledger snapshots, Resolver instances, or Profile objects.

Each Runtime exclusively owns one `OnlyCommittedExecutionJournal`. `OnlyExecutionProcessor` is its only writer. Broker
plugins can emit normalized updates and expose external query projections, but cannot construct or append local facts.
Result, Analytics, Artifact, Report, Scenario and Conformance consume the Journal or its standard Result projection.
They never use Broker `query_trades()` to reconstruct Runtime history and never rerun Fee or Market Rule logic.

## Commit and failure semantics

The successful order is:

```text
apply all local state
→ invariant check
→ Event commit
→ build Committed Execution Fact from transaction-local results
→ append Journal
→ report APPLIED
```

The idempotency boundary uses the local execution identity plus Runtime/Gateway-scoped Broker update and trade identities.
The Journal assigns an explicit contiguous execution sequence and rejects update or trade replay without advancing it.

Event commit failure creates no Fact. Fact construction or Journal append failure cannot return APPLIED; the Processor
records a dependency failure, marks the affected scope for reconciliation, and emits failure/reconciliation facts. The
current in-memory architecture cannot atomically roll back Manager changes after a late commit-stage failure, so this is
an explicit reconciliation boundary rather than silent success.

## Consequences

Backtest executions now preserve multiplier-aware notional, exact fees, explicit LONG/SHORT and OPEN/CLOSE semantics,
slippage provenance, settlement/margin evidence, and stable attribution. The same authority is intended for future Paper
and Live local histories; late external fee reports remain a separate reconciliation/adjustment concern.

The old Applied Trade Fact and Journal, their exports, tests, and compatibility paths are deleted. No aliases, wrappers,
dual writes, schema compatibility branches, or deprecated re-exports are retained. Execution Result and Artifact schemas
advance to version 2 because retaining the old incomplete shape would preserve incorrect semantics.
