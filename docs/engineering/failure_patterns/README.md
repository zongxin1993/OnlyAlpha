# OnlyAlpha Failure Pattern Library

## Purpose

This directory stores generalized engineering failure patterns learned from OnlyAlpha defects, mature external projects, provider specifications, incident reports and closed issue histories.

The library exists to prevent known classes of failure from being rediscovered through production incidents.

A failure pattern is **not** an external patch and is **not** a new product Authority. It is engineering evidence used to derive OnlyAlpha invariants, regression tests and certification cases.

## Pattern identity

Use stable domain-prefixed identifiers:

```text
FP-DATA-xxx      Market Data / Tick / Replay
FP-BROKER-xxx    Order / Fill / Reconciliation
FP-CALC-xxx      Calculation / Streaming / Checkpoint
FP-RESEARCH-xxx  Leakage / PIT / Multiple Testing / Evidence validity
FP-SEARCH-xxx    Candidate search / duplication / budget / convergence
FP-STORAGE-xxx   WAL / Revision / corruption / crash recovery
FP-RUNTIME-xxx   lifecycle / lease / concurrency / recovery
FP-API-xxx       idempotency / compatibility / schema drift
FP-AGENT-xxx     capability hallucination / stale context / authority violation
```

The numbering only identifies the knowledge record. It does not imply severity or completion status.

## Required record structure

Each failure-pattern document should use this structure:

```markdown
# FP-<DOMAIN>-<NNN> — <short name>

## Failure family

<general class of failure>

## External / internal evidence

- source project / provider / OnlyAlpha issue
- issue / PR / documentation reference
- status of evidence: observed / reproduced / specification-defined

## Observed symptom

<what a user/system sees>

## Generalized root cause

<the reusable technical cause; do not copy an upstream patch as the lesson>

## Risk to OnlyAlpha

<which Authority, invariant, state or scientific property could be violated>

## OnlyAlpha invariant

<the property that must remain true>

## Required protection

<OnlyAlpha-native architectural protection>

## Required tests

- regression test
- fault-injection test
- differential test
- certification case

## Non-solutions / rejected shortcuts

<retry/sleep/best-effort approaches that would not prove correctness, when relevant>

## Scope notes

<where the pattern applies and where it does not>
```

## What belongs here

Good candidates include demonstrated failures such as:

- reconnect replaying duplicate market events;
- sequence gaps leaving an invalid order book marked READY;
- snapshot/delta races;
- timeout after venue acceptance causing duplicate submit;
- partial-fill recovery divergence;
- retry causing a second external side effect;
- checkpoint/restart calculation drift;
- batch/streaming semantic divergence;
- DST/timezone boundary errors;
- point-in-time / look-ahead leakage;
- warmup / NaN handling producing invalid scientific evidence;
- WAL or manifest crash-boundary ambiguity;
- mutable schema/version drift;
- Agent selecting a capability that does not exist in the exact Catalog Generation.

## What does not belong here

Do not store:

- general opinions about framework style;
- popularity comparisons;
- benchmark marketing claims;
- speculative risks with no plausible failure mechanism;
- task completion status;
- CI snapshots;
- copied GitHub issue discussions;
- third-party source code or patches;
- an upstream workaround presented as an OnlyAlpha requirement.

## Evidence quality

Prefer evidence in this order when possible:

```text
reproduced correctness defect
→ closed issue / merged bug-fix with root-cause evidence
→ provider / venue specification defining dangerous semantics
→ production incident / postmortem
→ open issue with strong reproduction
→ design discussion
```

Lower-strength evidence may still be useful, but the record must distinguish observation from inference.

## Conversion rule

The target transformation is:

```text
Failure evidence
→ generalized failure pattern
→ OnlyAlpha invariant
→ executable test
```

For high-risk patterns, documentation alone is insufficient when a deterministic reproduction or controlled fault test can be built.

## Example skeleton

```markdown
# FP-BROKER-001 — Unknown submit outcome

## Failure family

A venue may accept an order while the client loses or times out waiting for the response.

## Observed symptom

The local caller sees a timeout and cannot prove whether an external order exists.

## Generalized root cause

Transport acknowledgement is not execution truth.

## Risk to OnlyAlpha

Blind retry can create a second external order and violate order identity / exposure invariants.

## OnlyAlpha invariant

UNKNOWN submit outcome must reconcile through exact client/venue identity before another submit with economic equivalence is permitted.

## Required protection

Deterministic client order identity + UNKNOWN state + reconciliation.

## Required tests

- venue accepts, response is lost;
- process crashes before local acknowledgement persistence;
- restart/reconcile converges to exactly one venue order.
```

The example is a documentation illustration, not a declaration that a particular implementation task is already certified.
