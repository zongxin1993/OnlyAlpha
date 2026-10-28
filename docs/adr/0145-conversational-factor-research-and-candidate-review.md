# ADR 0145: Conversational Factor Research and candidate review

- Status: Accepted
- Date: 2026-10-28
- Decision maker: repository owner, approving the chat/two-confirmation flow, candidate review and condition-grouped evidence ordering, then requesting documentation only.
- Related: ADRs 0110, 0118, 0120, 0122, 0135, 0138, 0139, 0141, 0142, 0143, 0144.
- Owning architecture: [Conversational Factor Research](../conversational-factor-research.md).
- Construction order: [Repository work program](../repository-migration-work-program.md#conversational-factor-research-follow-up), [Agent work program](../agent_factor_mining_work_program.md#14-deliberate-sequencing).

> **Partial supersession:** [ADR 0146](0146-independent-agent-product-and-python-langgraph.md) selects the independent
> Python LangGraph Agent product, four main release lines and split frontend APIs. Earlier Agent-in-backend/Python-only-algorithms
> placement statements below are historical decisions superseded only in that scope; canonical Rust business, semantic identity,
> permission and Research/Evidence requirements remain. The new decision is documentation, not implementation evidence.

## Decision

Deliver human-led conversational Factor Research before background automatic mining. The workstation keeps persistent chat beside
an inspectable Factor/proposal/run/report. First show name, purpose, predictive hypothesis, calculation logic and formula, with
code/contracts in advanced details. Confirm the exact Factor and implementation binding first; then the Agent suggests data,
bar period, forecast horizon/Target and sample/evaluation conditions. A separate explicit chat confirmation authorizes one Research
through the formal API. Mere conversation, source publication or chart context is not execution permission.

Content changes invalidate both approvals; research-condition changes require a new Research confirmation. Display-only edits
retain computational identity and historical name snapshots. Running tasks and completed evidence stay pinned. UNKNOWN recovers
the original Command rather than blindly launching another task. After a weak result the Agent may propose one explained improvement
draft; it must again obtain Factor and Research confirmations before execution.

Retain unknown and rejected candidates and all attempts in research history. Use a small pending-review entry for daily work and
explicit human collect/observe/archive dispositions over the same Factor assets. Collection is management preference, independent
of exact scientific Qualification, publication, Generation, Promotion or runtime permission. No parallel candidate registry or
LLM-owned scientific truth is introduced.

For automatic screening, group compatible research conditions, then evidence tiers, then explicit reproducible ordering reasons.
Policies and their evidence references are versioned; unknown/inapplicable evidence is not zero. Preserve failed attempts,
multiple-testing exposure and holdout governance. Stage one has no universal composite-score leaderboard or full-pool automatic
screening. Stage two permits automatic generation/Research/refinement only inside a separately approved bounded mandate; exceeding
it requires approval. Formal Brief/Search/Research/Qualification authorities remain in force.

## Alternatives and consequences

A transcript-only UI hides the current pending approval; the chosen split keeps chat and exact structured state visible together.
Putting every draft into the common library floods daily work; retaining only winners destroys lineage. A global score hides
incomparable samples and missing evidence. Automatically rerunning after an improvement blurs first-stage human consent.

This refines the long-term Agent architecture and changes the work program's first product delivery order, not its scientific,
source-admission, immutable-input, recovery or permission gates. The existing autonomous symbolic-search MVP becomes a stage-two
milestone rather than a prerequisite for introducing human-led chat. Rust authorities implement the minimum complete real Research
slice; eligible Python retirement accompanies consumer migration. Backtest/SIM execution is outside these two stages' delivery;
the long-term goal remains. LIVE authority permanently stays human under the Constitution.

The architecture owns detailed fields, reconfirmation rules, report/candidate behavior and acceptance. This decision does not claim
implementation, define new wire schemas or authorize code changes, arbitrary code execution, historical compatibility work,
automatic publication/deployment or remote commits. Implementation requires a separately authorized bounded task.
