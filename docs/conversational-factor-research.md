# Conversational Factor Research

> Target Architecture under the Project Constitution; decisions recorded by
> [ADR 0145](adr/0145-conversational-factor-research-and-candidate-review.md) and
> [ADR 0146](adr/0146-independent-agent-product-and-python-langgraph.md).
> This is an approved product direction, not evidence that the Rust Research or Agent path is implemented.
> Construction order belongs to the [repository work program](repository-migration-work-program.md#conversational-factor-research-follow-up)
> and [Agent work program](agent_factor_mining_work_program.md#14-deliberate-sequencing).

## Purpose and chosen approach

A person describes a predictive idea in ordinary language, understands the generated Factor before accepting it, and separately
confirms one proposed Research. OnlyAlpha returns reproducible scientific evidence; the Agent explains it and can propose an
improvement. Users should not need to author input/output JSON, read code or copy internal identities to complete this flow.

The owner refined the workstation layout on 2026-10-30: a Codex-like workspace has research conversation history on the left,
the conversation on the right, and a composer with model selection fixed below that conversation. Factor previews are structured
cards embedded in the corresponding assistant reply, rather than a permanently separate preview column. Research proposals,
task observations and reports appear with their relevant replies. Clearly distinguish current actionable cards from historical
versions; keep the pending confirmation discoverable even in a long conversation. This changes presentation, not approval authority.
Model connection and credential configuration lives in global settings beside data-source configuration, not in the research transcript.
The existing Agent-owned durable conversation store is reused; browser storage may retain presentation selection but is not the
sole record of research context. Restoring a conversation must restore its owned messages and exact associated proposal/task references.
The daily entry is a small **待复核候选清单**; complete candidates and failed experiments remain discoverable in research history.
Putting every generated draft into the common Factor library obscures useful assets, while retaining only winners loses evidence.
Compare candidates within declared research conditions, using evidence tiers and explicit reasons; a universal composite-score
leaderboard hides incompatible samples and unknown evidence. Stage one does not build such a leaderboard.

This design preserves [the four-layer model](adr/0110-four-layer-quant-asset-model-and-local-example-boundary.md): Operators express
mathematics, Indicators express established financial calculations, Factors express predictive hypotheses, and Strategies express
trading decisions using Factors. A Factor may output a continuous score or a condition; a research signal is not an order or risk
permission. Portfolio, Risk and Execution retain their own authorities. Research predictive evidence is not Backtest profitability.

## Terms and authority

| Term | Meaning and owning boundary |
|---|---|
| Conversation | Recoverable human/Agent interaction around one hypothesis; references authoring, proposals and tasks, without becoming their authority |
| Factor draft | Editable content in the existing Private Asset authoring boundary; chat turns need not create separate assets |
| Research candidate | A retained Factor hypothesis/content version under evaluation; uses existing Factor/Candidate/Calculation identities, not a second asset registry |
| Factor confirmation | Human acceptance of the displayed exact content and its implementation binding; not Research submission or execution admission |
| Research proposal | Explicit conditions and one-run intent awaiting separate human confirmation |
| Research / Evidence | Formal computation over exact admitted content, immutable input and configuration; owned by existing Research/Result/Artifact authorities |
| Screening assessment | Reproducible application of a declared versioned policy to exact evidence; cannot invent metrics or scientific qualification |
| Pending review / common / observe / archived | Management views and human dispositions over the same assets and referenced evidence; not scientific or runtime status |
| Qualification / Promotion | Existing exact policy/decision/progression authorities; collection and Agent explanations cannot replace them |

[Private Factor authoring](private-factor-authoring.md) owns Draft/Revision concurrency and publication;
[display identity](product-display-identity.md) owns names, purposes, display versions and historical labels.
[Search provenance](adr/0120-search-experiment-and-search-provenance-authority-contract.md) owns experiment/iteration/decision
lineage, not numeric results. [Research Statistics](adr/0119-rich-research-statistics-authority-and-factor-quality-evidence-contract.md)
owns scientific metric definitions and values. [Qualification](adr/0118-evidence-backed-qualification-and-promotion-authority.md) alone owns its
formal meets-policy decisions. New screening projections must reference or extend the appropriate existing contract, never create
a competing `qualified` flag. Current qualification subjects/metrics are not silently broadened by this design.

Human operations use Shipping Web → versioned Product API → owning Authority; Agent actions use the formal API. Chat transcripts,
model confidence and browser calculations are not acceptance, numeric or authorization authorities. Canonical backend business
belongs in `packages/backend`; Python LangGraph chat/research orchestration belongs in independent `packages/agent`; UI belongs
in `packages/frontend`. Reusable Rust libraries retain audited canonical roles. [Agent service architecture](agent-service-architecture.md)
owns storage, authentication, workflow continuation and API separation. Frontend uses Agent for conversation and directly calls
backend for exact Factor confirmation/Research authorization; no Agent service identity can impersonate Human consent.

## Conversation and visible information

The workstation exposes a discoverable 因子研究 entry. Chart instrument/timeframe may prefill context and suggestions, never consent.
One conversation follows one hypothesis through draft revisions and independent Research runs. A parameter/formula refinement of the
same hypothesis stays in that conversation. A fundamental change such as momentum continuation to reversal is explicitly a new
hypothesis, with its origin linked rather than replacing the old one silently.

The conversation's structured reply cards present:

1. **因子预览**: meaningful editable name, purpose, predictive hypothesis, calculation steps, formula, parameters and readiness rules.
   Code and input/parameter/output contracts remain advanced details. Agent-generated contracts still undergo formal validation;
   the ordinary user is not asked to fill JSON. Existing manual forms remain available for deliberate advanced authoring.
2. **研究方案**: proposed inputs, forecast and evaluation conditions, reasons, expected preparation and explicit confirmation state.
3. **运行情况**: the exact accepted task, observed phase, cancellation/recovery feedback and any actionable gap.
4. **研究报告**: actual inputs, scientific results and a separately labelled Agent interpretation, with earlier runs selectable.

Messages and their cards always identify the corresponding exact draft/proposal; only the current eligible card can offer a new confirmation.
Prior confirmed versions and reports stay selectable without
silently making an old item the current draft. Refresh/restart restores conversation, pending confirmation and original task
references. User-facing names lead; precise identities, source bindings and model/tool versions remain inspectable in details.
No new fingerprint or identity algorithm is introduced for these presentation views. Default copy uses natural financial/quantitative
language and exposes only information needed for the current step. Exact implementation identities, code and diagnostic records
remain available on demand under AGENTS.md §3.3.2. Required consent, source/sample conditions and unconfirmed outcomes stay visible
where they affect a decision. Existing sessions retain their bound model; a model picker must not silently substitute that binding.

## Two confirmations and amendment rules

**First confirmation — the Factor.** Agent clarifies the idea, constructs a draft and explains its hypothesis, logic and formula.
The displayed formula and executable implementation must refer to the same exact reviewed candidate/content version; approving
an explanation cannot authorize later unseen code. First confirmation durably retains the research candidate and acceptance
reference. Mutable display metadata is referenced separately from immutable computational content. Draft/Revision publication,
static/security validation, Calculation admission and Generation binding remain distinct existing operations; confirmation alone
cannot certify or bypass them. Before execution, Research must bind an exact immutable admitted version.

**Second confirmation — one Research.** After Factor confirmation, Agent recommends:

- instrument/universe, authorized source and bar semantics, period, data availability and quality requirements;
- forecast Target, direction/hypothesis, forecast horizon, sample dates and effective-sample requirements;
- development, out-of-sample and protected holdout boundaries; applicable statistics, uncertainty and baseline comparison;
- method/configuration versions, preparation and resource scope, and reasons for each recommendation.

The user may negotiate through chat and explicitly confirm the current proposal for **one** run. A clear equivalent UI action is
allowed, but cannot be the only confirmation path. The backend records authenticated intent bound to the exact Factor and proposal,
rechecks permissions/capability/admission, and submits through the existing recoverable Command boundary. Ambiguous agreement,
“looks good”, draft generation or a generic chat message does not silently launch Research. Confirmation is not permission to
collect arbitrary data, change source, widen dates or choose latest available artifacts. If input preparation is necessary, it must
stay inside the approved scope; the owning authority proves and binds the immutable Dataset before computation. If it cannot do so,
the UI explains the missing data/capability and asks for a revised proposal, without fallback or fabricated evidence.

| Change | Required confirmation and effect |
|---|---|
| Name/purpose wording with unchanged hypothesis/content | Confirm the display edit; computational approval remains. Do not copy mutable text into fingerprinted description |
| Hypothesis, formula, parameters or executable implementation | Invalidate Factor and Research approvals; confirm both again, including code-only changes |
| Source, universe, bars, Target, horizon, samples, metrics or evaluation method | Retain unchanged Factor approval; confirm the revised Research proposal |
| Edit during an accepted/running task | New draft/proposal only; accepted task stays pinned. Editing does not cancel it |
| Policy change after completion | New assessment over referenced evidence; do not rewrite original decisions/results |

Historical reports show submission-time names first, with current names as assistance under ADR 0143. Mutable task titles do not
change inputs, task identity or numeric artifacts. Approval is checked against current exact references and authoring concurrency;
a stale tab or delayed Agent response cannot execute an obsolete or substituted proposal.

If results are weak, the Agent may proactively offer **one improvement draft**, explaining supporting evidence, limitations and the
changed hypothesis/parameters. It may not run it. The improved candidate must pass Factor confirmation and then a new Research
confirmation; if content is unchanged, the exact content must still be explicitly reaffirmed for this proposed improvement cycle.
Further autonomous iteration is outside stage one.

## Run states, recovery and report

### Explicit environment and input preparation

The owner additionally authorizes native Rust Runtime management for this slice. After the Agent presents the proposed
conditions, Shipping Web exposes a separate **准备并启用研究环境** operation. Its preview includes the exact Factor, installed
algorithm/runtime versions, current-to-target Generation change and bounded data/source/window to prepare. The user explicitly
requests that preparation; it does not start Research, grant trading permission or stand in for the second Research confirmation.
The subsequent confirmation authorizes one exact prepared Study. Changing its content or conditions invalidates the appropriate
preparation/approval relation; no unseen Generation activation is hidden in Research submission.

Use the existing Generation journal, lifecycle lock, immutable artifacts and global Product Command authority. Rust lifecycle
mutations share the reader's canonical replay rules. Original activation replay observes its recorded outcome even after a later
switch, without reactivating an old target; an existing work binding never retargets. Source access, validated executable closure,
prepared input eligibility and Human Research consent remain separate proofs. Preparation may verify synthetic algorithm ABI
vectors, but these are not Research observations, scientific Evidence, Qualification or permission to inspect protected samples.
An installed-environment observation has its own immutable proof identity: physical release locations and installation
observations can differ while the exact executable Generation stays identical. Retain each observation by that proof identity,
under its exact Generation; a preparation Command selects its exact proof reference. Do not make a release directory part of
Generation identity, overwrite an earlier observation, or select an unspecified latest proof on recovery.

Persist the preparation's exact request/outcome references so refresh, restart and acknowledgement loss recover the original
operation and prepared inputs. Missing or corrupt original history is unavailable/UNKNOWN, not a fresh initialization, latest
selection or automatic retry. Only explicitly fresh owned namespaces may be initialized. Current Python lifecycle consumers remain
until their real call sites migrate; do not introduce Python backend functionality or a second Runtime registry for this path.

Visible phases are clarification, generating/checking Factor, awaiting Factor confirmation, proposing Research, explicitly preparing
and enabling the environment/data, awaiting Research confirmation, queued, computing, preparing report and completed. Failed, unavailable and confirmed cancelled are
explicit outcomes. These are a projection of owning workflow/task facts, not a parallel Research state machine.

Study suggestions use a separate finite Human registration permission; the default invitation permits ten suggestions for the
already-confirmed Factor and authorizes no preparation or execution. The Agent reads only exact available Source choices
(integration/revision/type/source/environment). Its proposed instrument remains a suggestion until the backend proves it through
the owning Source path. Missing permission does not accept a model occurrence or consume a new model-call slot. Human context
queries can still show the original grant and its inactive/exhausted state without silently issuing a replacement.

Preparation records the exact Study, first Factor confirmation, selected release and future Research Command before background
work. It explicitly publishes or reuses the confirmed immutable Factor Revision through Authoring, prepares the installed
mathematical closure, enables or reuses its exact Generation and materializes the authorized input window. The initial supported
window is bounded to seven days including warmup; recommendations must respect this and the Statistics sample/block/resource
requirements. A useful initial suggestion is 15-minute bars, 256 development and 256 sample-out observations, expected block
length 12 and 4,096 resamples; these are visible recommendations, not hidden execution defaults or a claim of statistical power.
The preparation context reuses the owning input validator to expose unsupported proposed windows before submission. Each sample
must reserve at least ten expected block lengths of potential pairs after forecast-boundary exclusion. A shorter proposal stays
visible with a specific explanation and a disabled preparation action; the user can ask for expanded conditions. It does not
create a preparation or Research, and does not hide earlier reports. The actual command repeats the same owning guard.

The preparation operation is not a Run and its READY state is not Research permission. Refresh uses verified original operations
and an explicit selection from this Factor's retained preparations, including prior conditions with accepted Runs. Restart does
not recreate a Human session or silently continue an incomplete preparation. Explicit resume retains the original Command and
release; an unavailable original release pauses it. Repeated cancellation cannot stand in for draining the original child owner.
Current Source or execution-environment availability must not hide previously accepted preparation/Run identities. The context
separately reports whether new work is available, and retained preparation queries separately report whether their physical
readiness proof can still be verified. Its history contains only discovery summaries from the owning verified operations:
Command identity, exact revision string, recorded workflow state, Study proposal fingerprint and acceptance time. A summary
contains no physical readiness, submission outcome or accepted Run claim. Selecting it reads that original operation through
the normal owning query before displaying or acting on its proof; a recorded READY in the list cannot enable confirmation.
Discovery does not reopen every historical Dataset/Runtime/Group proof, and it retains cancelled operations. Missing original
operation/Command/Factor ownership relations still fail closed rather than becoming an empty history. Neither status substitutes
for submission-time authorization. A known accepted Research
Command is recovered before checking current execution prerequisites; its original Run remains independently observable and
cancellable. Missing Runtime files with retained owning database facts are unavailable history, not a fresh Runtime.
Public preparation observation uses the retained read-only Product connection rather than queuing behind the preparation
producer's writer. It retains the original Command coordination and complete physical readiness checks, and fails explicitly
if that reader is unavailable. Internal checkpoints, resume/cancellation, materialization and Human authorization continue
through the original write Authority; observation never falls back to a writable connection.
Reading the retained Factor/Study grant relation verifies its original canonical record, Command and Receipt without taking
an update lock. It does not authenticate a new action or spend budget. Fresh authorization, revocation and budget checks retain
their parent-grant lock; Study withdrawal/current-admission checks retain parent-grant-before-Factor-lineage lock ordering.
Within one preparation call, the producer consumes the owning sealer's typed outcome, including its verified Group disposition,
rather than immediately reopening the same proofs. This outcome is not serialized into the prepared record, changes no
fingerprint and cannot be reconstructed from a restored record. Historical readiness and Human submission continue to verify
their exact retained Group and physical inputs independently; the outcome is neither a cached proof nor execution permission.
Changing a Study cannot invalidate an already accepted Run, and cancelling preparation does not rewrite immutable effects or
cancel a separately authorized Run. The latter has its own direct Human cancellation command.
An explicitly rejected stale confirmation can release its browser-local pending locator only after an owning read matches the
original preparation/Research Command/prepared-Study tuple, records BLOCKED/STOPPED with the exact stale reason and proves
NOT_SUBMITTED with no Run. Keep the original preparation and show how to stop it and load the new proposal; never automatically
prepare or confirm that replacement. An HTTP error, READY, UNKNOWN or an unobserved outcome alone cannot release the locator.

The chat phrase **确认本次研究** and its visible confirmation button submit the same exact prepared proposal directly to backend.
They are not a new model call or a Study edit. Unknown acknowledgement preserves that original Research Command; a Run state
observed from another operation cannot be substituted for its receipt. API counters that need exact CAS use canonical decimal
strings, and canonical input/report documents remain text rather than JavaScript floating-point timestamp objects.

Show only observed progress. No invented percentage or completion estimate. A requested cancellation is distinct from confirmed
cancellation; a completion/cancellation race follows canonical task truth and preserves completed evidence. Unknown submission
outcome is shown as 核对任务结果: reconnect/refresh queries the original Command/task and never blindly creates another run.
A known failure permits a deliberate new confirmed run; it does not turn an unknown outcome into a safe retry.

Reports separate three layers:

1. **Actual inputs and limits**: exact Factor/implementation, data/source/snapshot, bars, Target/horizon, sample split, exclusions,
   missingness, observations/effective sample, configuration and recorded decisions.
2. **Authoritative scientific evidence**: applicable predictive effect/direction, uncertainty, sample-out performance, stability
   across declared periods/regimes/universe, and declared baseline/robustness comparisons. Missing/unsupported evidence is explicit,
   not zero. Time-series and cross-sectional methods have distinct applicability; BTCUSDT alone does not justify cross-sectional IC.
3. **Agent interpretation**: what the cited evidence supports, what contradicts it, remaining uncertainty and a suggested next step.
   Interpretive text cannot change an artifact, declare formal Qualification or claim executable profitability.

Applicable report measures may include IC/RankIC and their distribution/uncertainty, directional hit rate with a declared baseline,
conditional or quantile forward returns, forecast-horizon decay, sample/coverage diagnostics and period/regime stability. Correlation
significance must account for serial dependence, overlapping forecast windows and multiple trials rather than presenting naive
independent-observation confidence. Quantile/long-short analytical forward returns are labelled research diagnostics, not a traded
portfolio or transaction-cost-adjusted Backtest. Exact metric definitions, applicability and the minimum supported first-slice set
must use existing frozen Statistics/Evidence contracts where applicable, and any missing time-series/uncertainty semantics must
be explicitly frozen at that owning boundary before implementation; absent metrics remain visibly unsupported.

For the first single-instrument Research, dependence-aware uncertainty is mandatory under
[ADR 0147](adr/0147-time-series-association-and-dependent-uncertainty.md) and the
[time-series Statistics contract](research-time-series-statistics.md). Use its paired stationary
bootstrap method with frozen comparison family, block length, confidence and deterministic seed.
An unavailable interval is an explicit outcome for insufficient/degenerate evidence; it is not
permission to omit uncertainty from the implementation or silently fall back to IID inference.

Forecast evaluation compares factor values to **future** returns/declared Target, not merely contemporaneous price movement.
Negative predictive direction can be informative but cannot silently reverse the agreed hypothesis after seeing results.
Insufficient data, invalid implementation and completed evidence against a hypothesis are different outcomes.

## Candidate retention, review and collection

Candidates with unknown or poor effectiveness remain traceable in research history, including failed runs and parent/child changes.
Retaining them does not put them in the daily common library. Stage one puts completed, human-confirmed Research candidates with
no current human disposition into the review entry; this is a manual-review inbox, not a claim that they passed automatic selection.
Present one hypothesis/family entry with relevant current evidence and expandable prior revisions/runs, rather than flooding the
inbox with slight parameter variants. Do not suppress a materially different hypothesis merely because its name is similar.

The user can **收录到常用因子**, **继续观察** or **归档** with a reason. Record the actor, exact asset/evidence scope and disposition,
with concurrency/recoverability appropriate to existing management Commands. Archiving removes a daily distraction, not immutable
artifacts or experiment history. Collection is an explicit human management choice and may include a promising but uncertain factor;
show the limitations rather than implicitly marking it qualified. No collection action publishes code, activates a Generation,
promotes a Strategy, starts Backtest/SIM or grants LIVE permission.

New material evidence can request review again, with a visible reason. Without new evidence or explicit user action, the same
candidate must not repeatedly resurface. Contradictory evidence does not rewrite the old report or silently undo an earlier human
collection. A favourable result is conditional on the tested data, forecast and policy, never a timeless global “good factor”.

## Automatic screening and explainable ordering

Stage two automates triage using exact authoritative evidence and a policy fixed/versioned before the search; stage one displays
applicable checks and report limitations and leaves disposition to the human. Neither stage uses LLM confidence as a metric.
Threshold values and eligible metric contracts require a separately frozen implementation contract; this architecture does not
invent a universal IC cutoff, minimal sample count or numerical score.

Screening proceeds through:

1. **Validity and sufficiency**: admitted implementation, alignment/no leakage, coverage/missingness, reproducible inputs and adequate
   effective samples. Invalid and insufficient evidence are separate classifications, never weak-but-valid results.
2. **Predictive support and robustness**: out-of-sample effect and uncertainty, consistency across declared periods/regimes/assets,
   direction and parameter stability. In-sample strength alone cannot count as robust support.
3. **Distinct contribution**: redundancy with known candidates and incremental information under an explicit comparable baseline.
   Absent comparison evidence stays unknown and cannot receive an invented novelty bonus.

Group before comparing: compatible universe/market/source and bar semantics, period, Target/horizon, sample/split and evaluation
methods. Materially different conditions appear separately, with their limits visible. Within a group, distinguish insufficient,
exploratory, sample-out supported and additionally robust/independently supported evidence **only when the required actual evidence
exists**. These are evidence presentation tiers, not new Qualification decisions or fixed numeric gate claims.

Within a tier, use a small declared lexicographic order such as sample-out support, stability, then evidenced distinct contribution;
show the keys, supporting references, missing evidence, rejection/review reasons and limitations. Parameter families group together
with a representative and alternatives. Exact keys, applicability and stable tie handling are frozen/versioned with the selected
screening policy before automatic use; no hidden weights, cross-group ranking or stage-one composite total-score board.

All attempts, failures, search budgets and lineage are retained, not only winners. Multiple testing and repeated parameter trials
must be visible when interpreting evidence. Once sample-out/holdout results guide an improvement they are no longer untouched
validation. Protected holdout access follows the existing governance; repeated optimization against it cannot be labelled independent
confirmation. New untouched data or expanded search scope requires the appropriate new proposal/mandate authority.

## Two-stage boundary

| | Stage one: human-led single Research | Stage two: bounded automatic mining |
|---|---|---|
| Input | Human chats about one hypothesis | Human explicitly authorizes a bounded mining mandate |
| Authorization | Factor confirmation, then separate one-run Research confirmation | Within the exact mandate, generate/research/refine without per-candidate stage-one confirmation; out-of-scope work returns for approval |
| Generation | Explainable candidate using admitted components; generated source only after real execution admission | Authorized literature/reports/market observations and bounded search methods |
| Evaluation | Actual Research/report, manual review; one unsolicited improvement draft without execution | Deterministic screening, deduplication, evidence tiers and reasoned shortlist |
| Retention | Conversation, exact candidates/runs/evidence and human dispositions | Same facts plus complete search lineage, attempt/budget accounting and stop/recovery facts |
| Excluded | Background batch mining, autonomous re-runs, full-pool automatic ranking | Unbounded search, hidden holdout probing, bypassed admission or new execution authority |

The stage-two mandate fixes goals/hypothesis scope, assets/markets, reading/data sources, admitted capabilities and model/tools,
samples/forecast/evaluation/holdout policies, search/compute/model budgets, concurrency, expiry, cancellation and stopping conditions.
It maps to existing Brief/Search/authorization contracts rather than creating a parallel grant. Content from papers, reports and
market sources is untrusted input with references and versions, not instructions or permission. Restart must preserve consumed
budget, lineage and pending outcomes; it cannot reset the search or repeat unknown effects.

Both stages leave Backtest, SIM and LIVE execution outside this delivery scope. The longer-term Research → Strategy → Backtest →
SIM direction remains; Agent Backtest/SIM needs its own formally granted scope. LIVE activation, LIVE strategy change and material
LIVE risk authorization always require explicit human operation. Missing shared Operators/Indicators require their own audited
library/plugin admission; generating a Factor does not silently change stable primitives or smuggle them into another layer.

## Acceptance and implementation decisions

| Proof | Stage-one acceptance |
|---|---|
| Normal user path | Shipping workstation chat → clarification → readable preview → explicit Factor confirmation → proposed conditions → separate chat confirmation → exactly one real Research → report → human disposition; advanced code/JSON never mandatory |
| Confirmation precision | Ambiguous/stale replies do not run; formula and code bind together; content change invalidates both approvals; condition change invalidates only Research; name edit preserves computational identity |
| Inputs/admission | Unavailable source/data/capability gives an actionable UI gap; immutable inputs and admitted content are proved before compute, with no scope widening/latest substitution |
| Evidence | Authoritative actual statistics with applicable uncertainty/quality and exact input references; unsupported metrics remain unavailable; interpretation cannot fabricate values or Qualification |
| Amendment/history | Running work stays pinned; earlier names, reports and versions survive edits; improvement needs both confirmations and cannot secretly run |
| Recovery | Refresh, backend restart, lost acknowledgement and cancel/completion race retain one task/Command identity and truthful states; UNKNOWN never launches a second task |
| Management | Candidate/history/common views share identities; collect/observe/archive have visible recoverable outcomes; no runtime or scientific promotion side effect |
| Usability | Pending step, loading/empty/invalid/denied/unavailable/success and error recovery discoverable through normal UI; relevant keyboard/focus/responsive behavior verified |

Stage-two acceptance additionally proves mandate boundaries and expiry/cancel, bounded attempts/resources/concurrency, durable budget
and lineage across restart, all failed attempts retained, no leakage/holdout reuse claims, same evidence/policy producing the same
screening/order, comparable-condition grouping, explicit missingness and shortlist reasons, family deduplication, no resurfacing
without new evidence, and human-only collection. Formal Qualification and Promotion remain separate. No Agent acquires LIVE authority.

Use “放量动量” on BTCUSDT as a worked interaction scenario: explain momentum × relative-volume, clarify lookbacks and closed-bar/
missing/zero-denominator rules, confirm the exact formula, then propose/confirm a forecast and sample split. Chat changes to horizon
must update the proposal before running; a weak-result parameter improvement needs both confirmations again. Example periods,
lookbacks, budgets and any illustrative results are not accepted numerical defaults or proof of actual available data/effectiveness.

Before each implementation slice, inspect current Rust/Python consumers and freeze the minimum complete module/API gap, capability,
DTO/Command bindings and deterministic acceptance under the owning contracts. In particular, pin preview-to-code validation,
execution sandbox/admission and Dataset preparation boundaries before code execution is added. ADR 0146 selects Python LangGraph
for Agent orchestration, without selecting new endpoint names, wire schemas, scoring thresholds or arbitrary execution capability. A safe graph-only implementation cannot falsely claim to
support arbitrary formulas; unsupported ideas must return an explicit capability gap.

The first product slice must include the minimum Rust Research and evidence consumers needed for a **real** vertical flow, not a
mock report or the existing display-only chart study. It need not horizontally migrate every backend subsystem. Retire replaced
Python only after consumer/admission/recovery closure, migrating useful independent assertions under ADR 0139. Keep legitimate
Python algorithms/plugins. Verification follows AGENTS.md: modified modules and direct consumers only; real Shipping UI acceptance
is required for the business flow. No full-repository test run, extra tooling project, release or deployment is implied.

## C2 backend-hosted contract and selected extraction

The following describes the backend-hosted C2 contract retained until its consumer-complete cutover; it is not the target
placement after ADR 0146. [Independent Agent migration](repository-migration-work-program.md#independent-agent-product-migration)
moves chat/model/profile/secrets and orchestration provenance to Agent, retains canonical preview validation/Authoring and
Human acceptance in backend, and changes the Web clients together. A backend-registered immutable proposal binds what the
user sees to the direct backend confirmation; neither Agent prose nor a chat request itself grants authority. Existing readable
previews, advanced forms, fingerprint/display semantics and UNKNOWN protections below remain required. No historical dev-chat
conversion or permanent old-route fallback is selected.

### Canonical preview and the Shipping C2 boundary

Shipping C2 uses independent Agent API v1 for model settings, bounded chat and interaction provenance, and the backend proposal
API for immutable previews and direct Human confirmation (ADR 0146). The backend-hosted `/api/v2/factor-chats` and Integration-based
chat-model writer/adapter are retired. The independent service is the only active model/chat owner for this page. Existing
`/api/v2/agent` autonomous operations remain denied. No model credentials enter chat records or frontend persistence.

The first supported candidate grammar is a bounded arithmetic tree over OHLCV, integer literals, and declared closed-bar delay/
rolling-mean dependencies. Unsupported source/operations are rejected. The backend derives formula, input contracts and restricted
Private Factor API V1 source together; returned model code is never accepted or executed. Dependency declarations are preparation
requirements, not admitted executable graphs. C3 must resolve them through the existing canonical Calculation Graph and prove the
exact execution binding before Research. The current API V1 remains stateless pointwise with unchanged identity and numeric rules.

Agent conversation events are append-only provenance bound to Agent-local command identity, the exact preceding event and pinned
model/workflow. Backend global Command/Receipt identities own registration, withdrawal and Human confirmation. A model occurrence
is accepted before one external call; its bounded response or failure/UNKNOWN is recorded once. Reconciliation never calls the model
again. A deliberate new message is a new occurrence and cannot bypass an unresolved predecessor. Model-profile successors do not
replace existing session bindings; missing exact workflow/artifact pauses continuation without a latest-version fallback.

Explicit chat text “确认因子” / “确认当前因子”, or the equivalent preview action, submits a Human confirmation bound to the exact
preview. Confirmation and the existing Authoring save participate in one owning transaction, with separately bound child Command
identities. It creates/updates the same Private Factor Draft and display metadata, not a parallel source store, published Revision,
Calculation admission, Runtime Generation or Research Run. Concurrent manual authoring changes cause an explicit conflict. Names
and purposes remain separate display metadata; computational confirmation survives a display-only edit. Model output is never
interpreted as Human confirmation. C2's visible completion is a confirmed saved draft, not scientific validation or a runnable factor.

Agent-local Command intent binds the original Human request, independently of model context derived by the service. The accepted event also
freezes the complete model request, including exactly the messages known at acceptance; late model responses cannot change that
request. Display metadata uses its own last-confirmed base fingerprint, so manual renaming cannot be silently overwritten by a
later chat confirmation. An explicit UI abandonment action settles a not-yet-accepted original Command under its Agent command lock with
an immutable Agent-local abandonment fact. This fences late arrivals; it does not revoke an accepted event or retry an unknown model call.
