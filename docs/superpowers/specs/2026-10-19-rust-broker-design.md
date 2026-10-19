# Rust Broker common protocol and reconciliation

This design describes the next isolated library under ADR 0139. It is not a completion or certification authority. PROJECT_CONSTITUTION.md, the Broker contracts, ADR 0066 and the Runtime persistence contract retain authority.

## Boundary

Broker normalizes immutable external observations and gates external dispatch against the owning Runtime's exact Ready intent. It never writes Order, Account, Position or Ledger projections. Provider SDKs, credentials, signing, network I/O, file drivers and venue rules belong to adapters. Existing Python Virtual Broker remains the deterministic comparison implementation. Rust Runtime activation, official Store drivers, LIVE and Web product acceptance are out of scope.

## Protocol

All commands bind engine, Runtime, Gateway, Account, exact generation and Runtime kind. Requests have explicit intent and stable request/order/client identity, independent of connection sessions. The Runtime reader verifies the complete canonical request, current owning Order/submission lifecycle and current pending cancel relation before returning its committed Ready transaction reference. Historical ADMIT/CANCEL existence alone never proves current dispatch eligibility. Broker persists that binding, then DISPATCHED, before invoking the adapter. A persisted DISPATCHED without a known result is UNKNOWN even when the adapter was never entered. Recovery never calls an adapter. Retrying the same command returns the existing state; changing its payload conflicts. No new submit or uncertain cancel identity may bypass unresolved evidence for that Order.

An opaque append capability prevents decoded history from authoring new records. The serialized owning journal atomically appends exact contiguous records and makes them queryable; an error may mean persisted UNKNOWN. Broker re-reads the immutable prefix before subsequent work. Driver failures never grant dispatch or readiness. Restart reconstructs state from the journal, resets transport readiness and rebuilds undelivered reconciliation facts.

## Facts and reconciliation

Normalized updates preserve observation provenance separately from the existing Execution v2 accepted, terminal and fill identities. Stream/query/recovery duplicates have one semantic identity; changed payloads conflict. Ingress batches are bounded and atomic. Account/position snapshots and queries are observations, not local trading authority.

Discovery binds the exact command and scope. PRESENT carries the authoritative Order view and complete missing fact set. Facts are persisted before publication. Resolution requires the owning Runtime's exact Ready application receipt for every missing fact and an independently re-read local Order view equal to a newly verified venue view. A boolean success flag, matching hash alone, partial receipt set or stale discovery cannot resolve anything. Strong ABSENT_PROVEN may resolve SUBMIT without fabricating a terminal Order event; CANCEL absence remains inconclusive. Neither authorizes resend. Identity conflict latches fail-closed readiness; cancellation and observation remain available. Starting discovery clears its aggregate completeness assertion, including on query failure; resolving one Order does not automatically certify all Gateway discovery.

## Proof obligations

Exercise fresh, durable-intent, dispatched, known, unknown, reconciling and resolved states; failures before/after append and before/after dispatch; process restart; missing/foreign/changed predecessor, scope, command and receipt; incomplete/unavailable discovery; duplicate stream/query observations; changed semantic payload; overflow without a partial batch. Compare canonical v2 identities against the current Python implementation and consume a real Virtual Broker trace. Compose with real Rust Execution through its owning Ready reader, without inferring intent from raw payload digests.

Python audit: factory/entry points and append/fsync implementations remain outside the library. Legacy schema fallback and offset-derived missing intent are not copied. The Python protocol's loose boolean verification, volatile pending set and incremental queue publication are not sufficient proof for this new isolated boundary. Current Python runtime activation is unchanged; new semantics do not certify or replace that path.
