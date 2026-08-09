# ADR 0061: Fee Reconciliation Semantic Closure

Status: Accepted

## Context

ADR 0060 closed local fee-authority integrity. External broker evidence remained
an aggregate comparison with caller-owned materiality, nullable scope fields, an
account-wide statement fallback, mutable single-blocker semantics, and a fee gate
that interpreted SELL+CLOSE itself. Those contracts could not prove what an
external report covered, which component differed, or why a later report was
allowed to correct or unblock earlier state.

## Decision

External evidence and local fee applications are independent immutable facts.
Neither overwrites the other. Reconciliation governance is a third, independent,
versioned authority with identity, currency, threshold and explicit handling for
unknown, incomplete and component-mismatch cases. Runtime callers submit evidence
only; policy parameters and system difference classifications are not caller input.

Evidence uses one tagged typed scope. Trade and order scopes contain exactly one
typed ID. Statement scope freezes broker, account, currency, statement identity,
fingerprint and a UTC `[period_start, period_end)` interval. The fee ledger stores
the economic effective time and maintains trade, order and account/currency/time
indexes. Its query service is the sole local scope authority.

DETAILED evidence is normalized by broker adapters into stable component
identities. Reconciliation uses the union of local, external and prior-adjustment
component identities. Missing and zero are distinct. An external total supplied
with detailed components must equal their signed sum. Local-fact and prior-
adjustment fingerprints prove the exact inputs to every decision.

Adjustments are immutable component facts. A revision carries an integer sequence
and explicit predecessor in the same evidence family. Same family/sequence/content
is duplicate input; different content is conflict; a next revision must supersede
the current evidence ID. Corrections are new forward adjustments computed against
local facts plus component-aware prior adjustments.

Risk gating stores a deterministic active blocker set. A blocker is attributable
to account, evidence family, evidence, reconciliation, scope and policy. Only an
accepted revision in that lineage can resolve it. Independent matching evidence
cannot clear it, and resolving one of several blockers leaves the others active.

The fee gate accepts a risk-change classification produced by Risk. It does not
import order side or offset. While blocked, only RISK_REDUCING is allowed;
RISK_INCREASING, RISK_NEUTRAL and UNKNOWN fail closed.

Broker adapters expose normalized `OnlyExternalFeeEvidence` through the broker fee
evidence port. Provider DTO and SDK field names do not enter Core.

## Persistence and recovery

Evidence, decision, adjustment, committed fee-reconciliation fact, fee-application
record, reconciliation authority checkpoint and risk-gate checkpoint schemas are
upgraded without an implicit migration. The generic Runtime transaction envelope
is unchanged. Existing ordered projections remain the durable chain: evidence,
decision, component adjustment facts, account/strategy or unallocated economics,
then one atomic active-blocker state.

Forward recovery uses the existing Transaction Store and Applied Projection Ledger.
No committed evidence or adjustment is edited or removed. Replaying a committed
tail is economically idempotent.

## Consequences

This is a breaking evidence and checkpoint change. Configuration must select the
reconciliation policy explicitly. P2 establishes domain/durable semantics only;
it does not connect a real MiniQMT statement endpoint, install production A-share
fees or commission contracts, enable Live, or add FX/advanced allocation.

## Rejected alternatives

- Overwriting local fee records destroys the historical authority used at trade time.
- Total-only matching can hide offsetting component errors.
- String statement scopes cannot enforce account, broker, currency or time boundaries.
- Clearing an account boolean after any match lets unrelated evidence remove risk controls.
- Fee-owned BUY/SELL rules duplicate market and position semantics.
- Revision by string comparison gives values such as `"10"` and `"2"` accidental ordering semantics.
