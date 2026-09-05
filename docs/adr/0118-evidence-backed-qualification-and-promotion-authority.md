# ADR 0118: Evidence-Backed Qualification and Promotion Authority

- Status: Accepted
- Date: 2026-09-05
- Decision maker: repository owner through the B2.5 implementation authorization
- Related: ADR 0097, 0100, 0101, 0115, 0116, 0117

## Context

ADR 0097 established immutable Strategy Revision identity and an append-only Promotion ledger, but the first Product Promotion
command still accepted a Freeze relation and created an approved Promotion fact without a separately reproducible standard or
qualification decision. Research and Backtest already produce immutable exact evidence. The missing authority is the deterministic
relation that decides whether one exact Strategy Revision satisfies one exact policy using one exact evidence set.

## Decision

OnlyAlpha adds an immutable `QualificationPolicyRevision` and immutable `QualificationDecision`. The first subject is the existing
`StrategyRevision`; Qualification does not create a qualified-strategy identity or mutable status. The first gates are
`RESEARCH_TO_BACKTEST` and `BACKTEST_TO_SIM`. There is no `SIM_TO_LIVE` qualification gate in this decision.

A Policy Revision binds an exact `policy_id + policy_version`, gate, canonical criteria, fail-closed missing-evidence behavior and
aggregation semantics. The same ID/version may never identify different canonical content. Formal evaluation resolves an exact
revision and never selects latest, newest or highest. V1 supports deterministic `ALL` aggregation and scalar numeric comparisons.
Unknown aggregation, comparison or metric semantics fail closed.

Evidence binding is typed. Research qualification binds an exact verified Research Result to the subject through an exact verified
Freeze relation. Backtest qualification binds an exact verified Backtest Evidence manifest whose Strategy fingerprint equals the
subject. Qualification reads only facts already owned by those immutable authorities. V1 exposes only manifest-owned result,
artifact and implementation counts; it does not read raw bars or recompute IC, PnL, return, drawdown or other Research/Backtest
truth. Additional metrics require their owning Evidence contract to expose them first.

The deterministic evaluator consumes exactly:

```text
StrategyRevision + QualificationPolicyRevision + typed exact Evidence
→ QualificationDecision
```

Criterion results preserve the exact evidence reference, observed scalar, comparison, threshold and PASS/FAIL outcome. Decision
identity excludes clock, actor, host, process, UI, Agent prompt and natural-language explanation. Immutable Policy and Decision
stores use put-once, exact verified load and content identity. The public Decision store is read-only; its internal publication
capability accepts only evaluator-sealed Decisions, so a caller cannot persist a self-declared outcome. Re-evaluation of the same
inputs must reproduce the same Decision.

Qualification does not grant progression. New Promotion facts require an exact approved Qualification Decision whose subject,
gate, policy and evidence bindings verify. `RESEARCH_TO_BACKTEST` additionally requires the existing Freeze relation;
`BACKTEST_TO_SIM` produces SIM eligibility only. Existing pre-B2.5 Promotion records remain historical append-only facts and are
not fabricated or rewritten as qualification-backed facts. The validating Product service is the sole production call site that
seals a qualified Promotion authorization; the legacy raw application/ledger append path fails closed. Runtime lifecycle and LIVE
permission remain separate authorities.

Product commands use the existing UUID4 command identity and receipt semantics. Policy administration remains an explicit
operator-owned composition action; the Agent-facing Product surface may query exact Policies, request evaluation, query immutable
Decisions and request Promotion, but cannot mutate Policy content, declare a Decision, bypass a rejected result or acquire LIVE
authority.

## Consequences

Research and Backtest remain fact producers, Qualification becomes the sole meets-policy relation authority, and Promotion remains
the sole progression authority. Historical decisions can be replayed without current-time or current-policy selection. Initial
criteria are intentionally narrow until richer scalar metrics are owned by authoritative Evidence contracts.

## Rejected alternatives

- A mutable `qualified` field on Strategy or Factor.
- Agent/LLM confidence, free text or operator reason as PASS/FAIL authority.
- Recomputing Research statistics or Backtest analytics inside Qualification.
- Untyped fingerprint bags, latest-policy lookup or semantic-near-match evidence substitution.
- Replacing Promotion with Qualification or treating SIM eligibility as a running Runtime.
- Automatic or Agent-authorized LIVE progression.
