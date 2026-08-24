# ADR 0099: P9.0 Execution Evidence, Certification and Publication Authority

- Status: Accepted
- Date: 2026-08-24
- Related: ADR 0073, 0074, 0097, 0098

## Context

P9.0 Closure established Strategy Revision identity and Candidate Freeze, but three authority gaps remained. Research Calculation
execution resolved providers while processing and did not preserve the exact implementation manifest that produced a Result. Calculation
equivalence V1 accepted caller-provided runners and corpora and bound only a type reference, so it did not prove execution of the exact
node or the actual registered backends. The Strategy Revision Store also exposed `commit(raw_revision)`, allowing executable publication
without verified Freeze.

Those gaps allowed current Registry state, caller claims, or raw content publication to become a second interpretation of historical
Research provenance, cross-backend equivalence, or executable Strategy authority.

## Decision

Calculation semantic identity remains independent of implementation identity. A Calculation Result continues to answer what was
calculated. A separate immutable Research Calculation Execution Evidence V1 answers which exact RESEARCH implementation binding produced
that exact Result. Research resolves every Graph node exactly once before reading Dataset rows, freezes an execution plan, and carries a
canonical binding set through execution. Evidence publication derives linkage from that execution and the verified committed Result;
callers cannot submit claimed provenance.

Completed Research Runs store exact immutable Execution Evidence fingerprints. PostgreSQL owns only those operational references; the
content-addressed semantic Store owns evidence truth. Freeze verified-loads only the Run-referenced evidence and requires exactly one
fully linked producer evidence for the Candidate Calculation. A legacy completed Run without provenance remains a historical fact but is
not Freeze-eligible and fails with `RESEARCH_EXECUTION_PROVENANCE_UNAVAILABLE`. Historical implementation identity is never inferred from
the current Registry.

Calculation Equivalence Evidence V2 binds the exact Calculation node fingerprint, type reference, historical RESEARCH implementation,
current TRADING implementation, system-owned certification profile, system-materialized canonical corpus, exact output identities and
comparison identity. Only the official Calculation Equivalence Certification Application Service may mint the sealed publication value
accepted by the V2 Store. The service accepts an exact node only: it accepts no runner, output, profile, or corpus from callers. It resolves
and executes the actual registered RESEARCH provider and the same exact TRADING invocation primitive used by Strategy execution. V1
evidence remains legacy historical content and is never upgraded or accepted by Trading Admission.

Trading Admission reads historical RESEARCH implementation bindings exclusively from verified Run-linked Execution Evidence. It resolves
only the current exact TRADING implementation, derives the required system profile from node semantics, and requires one exact Evidence
V2 match for every node. Current RESEARCH Registry availability is not an Admission requirement. Research implementation drift therefore
changes the Strategy implementation binding and `strategy_fingerprint`, even when semantic Result identity is unchanged.

Strategy Revision construction remains a valid Domain operation, but executable publication is Freeze-only. A new
`strategy/frozen-revisions` namespace is the sole Runtime-readable authority. Runtime, Cluster, Backtest, SIM and Promotion receive only
the `OnlyStrategyRevisionReader` capability. An internal publisher accepts only a Freeze-sealed publication value and is composed only
inside the Freeze application boundary. The legacy `strategy/revisions` namespace is not Runtime-readable and is not automatically
trusted or copied.

Freeze Record V3 records exact Research Execution Evidence and Equivalence Evidence V2 fingerprints without adding evidence, actor, or
audit time to Strategy semantic identity. Forward migration 0010 adds nullable legacy-compatible Run references and V3 Freeze provenance;
old Run and Freeze rows remain legacy facts but cannot satisfy new publication rules.

## Rejected alternatives

- Adding implementation fingerprints to Calculation semantic identity.
- Reconstructing historical provenance from the current Registry.
- Scanning semantic storage during Freeze to find some matching producer evidence.
- Letting callers provide synthetic runners, outputs, weak corpora, or custom production profiles.
- Treating type/version equality or Equivalence V1 as admission-grade proof.
- Keeping raw Strategy Store commit for tests or compatibility.
- Auto-copying legacy raw-published Strategy revisions into the frozen executable namespace.
- Giving Runtime a publisher, writer, repair, update, or migration capability.

## Consequences

The proof chain is unique: verified Dataset and exact Research Graph produce immutable Result plus immutable implementation provenance;
actual-backend Evidence V2 certifies the exact Research/Trading pair for each exact node; verified Freeze alone publishes the immutable
Revision into the frozen namespace; Runtime can only verified-load that exact fingerprint and resolve its bound TRADING implementation.
Unknown, missing, ambiguous, corrupt, legacy, or incompatible authority fails closed.

P9.0 remains `Closure-2 / IN PROGRESS` until the complete quality matrix and exact immutable Final-SHA Certification workflow produce an
`ACCEPTED` artifact.
