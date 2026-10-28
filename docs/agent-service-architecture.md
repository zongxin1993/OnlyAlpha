# Independent Agent service architecture

Target architecture under the Project Constitution and [ADR 0146](adr/0146-independent-agent-product-and-python-langgraph.md).
This defines ownership and required behavior, not implementation status. Current source still includes backend-hosted C2;
the [migration sequence](repository-migration-work-program.md#independent-agent-product-migration) governs its replacement.
The conversational product rules remain in [Conversational Factor Research](conversational-factor-research.md).

## Intent and approaches

Make high-change research automation independently deployable/versioned without moving data, trading or scientific authority
out of the Rust backend. One Shipping Web interface remains the normal Human entry. Agent is an API client of backend even
when both processes share a host. Host/database proximity grants no permission.

The owner chose independent Python LangGraph over backend-bundled orchestration and an independent TypeScript Agent.
Python fits literature/research tooling; LangGraph supplies graph execution, checkpoints and Human waits. Use it as a
library within the owned service, not as another mandatory UI, cloud platform or quantitative execution engine. Do not also
install Pydantic Graph, Temporal, RD-Agent/Qlib or multiple search stacks to satisfy this first slice. Particular LangGraph
versions, parsers, HTTP libraries, endpoint names and low-level auth encoding must be selected/locked in the relevant task
from actual dependencies; they are not frozen by illustrative names in this document.

## Product layout and deployment

```text
crates/                         existing reusable Rust libraries and dependency boundaries
packages/backend/               Rust Product API, canonical business, execution and algorithm children
packages/frontend/              unified Shipping Web; two explicit service API clients
packages/agent/
  pyproject.toml                Agent distribution/version authority
  src/onlyalpha_agent/           API, orchestration, external adapters, owning persistence, backend API client
  tests/                        affected Agent contracts, recovery and service tests
contracts/                      versioned public and cross-service contracts
```

This is a responsibility sketch, not a request to create empty directories. Choose internal modules only for real consumers.
Use a single coherent dependency lock authority per Agent installation closure. Keep Agent dependencies isolated from the
backend's minimum algorithm interpreter/SDK. A shared Python interpreter version does not make their environments shared.
Resolve/install exact dependencies at build time, never on service startup. Backend does not depend on Agent source or import
Agent code. Agent does not import private backend/Kernel/Store implementation objects.

Agent may run on the same host or a configured remote server, supervised by its deployment lifecycle. Backend supervises its
own execution children, not a competing Agent supervisor. A same-origin reverse proxy can route the two API namespaces without
owning business logic; remote placement must preserve authenticated identities, allowed origins and protected transport.
Local development still uses the single authorized `onlyalpha-dev` topology; any future Agent service joins that topology,
not a second Compose project or parallel business stack. No topology or runner changes occur in this documentation task.

## Terms and authority map

| Fact / capability | Sole owner and rule |
|---|---|
| Conversation, unconfirmed idea and proposed formula | Agent; distinguish chat/proposal IDs from canonical Factor/Candidate identities |
| Model profile/configuration Revision and credentials | Agent; exact profile binding, separate secret scope; no values in chat/checkpoints/artifacts/browser responses |
| Brief, Agent session, model/tool plans/results, Agent decisions and launch provenance | Agent's existing ADR 0123 contract; retain exact inputs/results, limits and downstream references |
| Workflow checkpoint | Agent's LangGraph persistence; execution cursor/scratch state, not authority for consent, metrics or backend effect |
| Agent call/tool budget | Agent under ADR 0123; derive consumption from committed plans, not mutable process counters; no restart reset |
| Immutable staged confirmation input | Backend owns its validated snapshot/receipt; Agent-origin reference remains provenance, not a second Factor registry |
| Formal Factor Draft/Revision/display and confirmation | Backend owning Authoring/Application boundary; unchanged fingerprint/numeric/source rules |
| Human approval / automatic-research mandate | Backend; authenticated exact scope, expiry/revocation and applicable usage enforcement |
| Search Experiment, iteration, formal search budget and stop/feedback facts | Backend's existing ADRs 0120–0122 authorities; Agent proposes strategies, never copies these transitions into another truth |
| Research inputs, execution, cancellation, results and scientific statistics | Backend Dataset/Research/Statistics authorities; immutable exact input bindings |
| Qualification and Promotion | Existing backend authorities; collection, optimizer best-trial and Agent interpretation cannot declare PASS |
| Agent research notes / literature retrieval | Agent-owned summaries, citations and working memory; no scientific rejection or suppression authority |
| Formal Experiment Memory / similarity query | Backend Product query/index under ADR 0127, accessed by Agent through API; Novelty Policy/Decision and admission enforcement remain backend-owned |
| Data, Strategy, Generation, trading, risk and LIVE | Backend and existing owning contracts; Agent never receives LIVE authority |

All Agent-specific features belong in Agent unless they enforce a backend-owned rule. A name containing `agent` is not a
reason to move authorization, Research facts, scientific novelty decisions or execution into Python. Search recommendations
and optimizer state must not bypass admitted backend Search contracts. This decision does not broaden ADR 0123's existing
session child limits or ADR 0122's finite deterministic parameter-search algorithm.

## Storage and evidence

Default deployment may share one PostgreSQL service but uses separate databases, roles, migration ownership and connection
configuration. Agent credentials cannot read backend business/secret tables; backend credentials do not read Agent tables.
No cross-database foreign key, join, shared model or filesystem Store import is an integration API. Each service owns its
document/blob namespace and encryption material. Remote Agent storage can be local to its deployment without sharing mounts.
Tests use isolated test namespaces, never dev business data.

Agent retains append-only model/tool occurrence and decision facts; LangGraph's normal checkpoint updates do not rewrite
these records. Persist full decision-affecting model requests/responses or classified failure/UNKNOWN with exact profile,
workflow, prompt/schema and source references. Do not request or depend on hidden model reasoning. Papers/reports are untrusted
content, not instructions: retain source/version/content identity and citation locations for claims used in proposals.
Actual parser dependencies/artifacts must be pinned when used. No general vector database, crawler fleet or document platform
is required before one real source consumer needs it.

Chat history is authoritative only for interaction/proposal provenance. Formal result values, task states and Qualification
shown there are references/projections of backend facts; unavailable queries remain unavailable, not cached new truth.
Source/model memory and failed attempts remain traceable. Agent-owned notes/literature indexes are distinct from ADR 0127
Experiment Memory. The latter retains its backend Product query/index placement and completeness/read-to-act rules; Agent
uses that API and may cache permitted results only as labelled projections with exact source references. Neither summaries
nor indexes can replace missing decision evidence or publish Novelty Decisions. Disposable indexes can be rebuilt; authoritative
source facts cannot be reconstructed by guessing from a checkpoint.

## Two service APIs and direct Human confirmation

Both versioned APIs are parts of OnlyAlpha's formal control boundary with explicit owners. Frontend calls Agent for chat,
model settings and orchestration control. It calls backend directly for Factor acceptance, Research authorization/submission,
formal cancellation, management and authoritative result queries. An Agent cancel stops its own future work; cancellation of
an already accepted Research requires its owning backend command/confirmed outcome. A disconnected Agent cannot imply a
Research cancellation or hide completed evidence.

Before offering a formal confirmation, Agent stages the exact proposed content through a scoped backend API. Backend checks
schema, identity, ownership, permitted content/size and expected Authoring base, and retains a complete immutable confirmation
snapshot plus its exact Agent origin. Its reference is a proposal occurrence, not a canonical Factor/Candidate identity.
For a Factor it binds displayed formula/hypothesis, source/API/contracts/dependencies and separate display metadata. For
Research it also binds the confirmed Factor/implementation and proposed source/data/bar/Target/sample/evaluation conditions.
It confers no publication, execution admission, Qualification or runtime permission.

Frontend renders the backend-registered snapshot for the pending confirmation and submits that exact reference with a Human
Command directly to backend. Backend independently derives/verifies its canonical content identities, rejects stale bases,
and durably records acceptance and owning business effect/receipt. An Agent hash or a formula explanation alone is not proof
of admitted code. Exact executable graph/source admission and immutable data preparation remain required before Research.
Content/condition edits create new snapshots and invalidate approvals as specified by ADR 0145; delayed old responses cannot
replace the current pending snapshot. Existing display-only and historical-name rules remain.

Agent observes the backend receipt via API before progressing. If backend accepts while Agent/checkpoint recording fails,
resume queries the original Command/effect. Stable identities and bounded queries reconcile cross-service partial success;
do not add distributed transactions, a second receipt store, blind retries or new IDs for UNKNOWN operations. Agent-local
chat request identities and backend Product Command IDs are distinct, explicitly linked and scoped to their owners.
Once staged, backend can show/confirm that snapshot without a live Agent lookup. Accepted Research can execute, be observed
and cancelled without Agent. Backend downtime permits readable Agent history but prevents formal work/progression.

## Identity, permissions and credentials

One user-facing sign-in experience may establish separate service-audience sessions. Each service verifies trusted issuer,
subject/ownership, intended audience, expiry/revocation and applicable request-origin protection. A shared proxy or localhost
is not authentication. Frontend never receives backend Agent credentials or model keys. Agent never receives the Human owner
Cookie/token for backend and cannot self-assert Human confirmation. Do not make either service a confused-deputy proxy.

Agent-to-backend calls use a separately identified service principal and explicit backend grant constrained by owner, purpose,
objects/sources, allowed operations, budget, expiry/revocation and existing capability rules. Backend enforces its grant at
each operation; a shared Human subject reference alone grants nothing. Stage one allows context/proposal/result operations,
not autonomous Research submission. A separate stage-two mandate may allow bounded Research/Search with durable usage, stop
and cancellation semantics; it does not transfer qualification, promotion or LIVE authority. Backend Source/data grants stay
effective when facts are exposed through Agent APIs, including cached chat/context disclosure.

Current native local-developer admission is not remote multi-service authentication. Before remote use, implement the minimum
versioned identity/grant/session boundary using existing security and revocation contracts; deny unsupported deployments.
Choose the concrete credential/transport mechanism in that bounded task, not by silently widening current Human-only routes.
Model secrets move to Agent through its normal configuration UI and owning secret commands. Existing backend-held market/broker
credentials and infrastructure bootstrap credentials remain separate. Do not retain a second active model configuration authority.

## Workflow continuation and upgrades

New sessions select an exact supported workflow artifact, dependency environment, configuration/model and policy bindings.
Resuming an existing session loads its bound implementation and supported checkpoint schema, not the currently installed
default graph. Retain required trusted artifacts/readers and records for active sessions. The implementation task must define
the ownership/fencing of a session so multiple service instances cannot execute the same model/tool occurrence concurrently.

If the bound workflow/environment/reader is missing or incompatible, show a blocked/unavailable continuation and preserve
the session, evidence, budget and pending outcomes. Never reinterpret a checkpoint using another graph, fall back to old
backend C2, reset consumption or rerun an unknown external call. Restoring the exact authorized artifact may resume it; choosing
a changed workflow requires an explicit linked new session and its applicable renewed confirmations/mandate. This is not a
promise to support every retired development schema or to build old-data compatibility loaders.

Model/tool steps can re-execute around checkpoint failures; use durable occurrence identities, stored results and owning API
reconciliation, not LangGraph alone as an exactly-once guarantee. A call accepted before a crash with no provable result stays
UNKNOWN. No automatic model retries, provider switching, time-travel replay of effects, parallelism or timeout expansion is
authorized merely by installing a framework. Changing model/profile policy follows its owning exact-binding rules.

## Releases and compatibility

See [release versioning](release-versioning.md) for the four metadata authorities, immutable tags and exact build inputs.
Agent owns its interpreter/dependency closure, provider/parser adapters and workflow implementation artifacts under its release;
it does not bundle a second maintained backend/Kernel. API compatibility is explicit for frontend/backend, frontend/agent and
agent/backend. A default tested combination binds actual artifacts and protocol/capability versions, not equal version numbers.
Backend remains independently operable without Agent. Do not run a full cross-product historical matrix for every change.

Agent release version, workflow identity, model configuration identity, proposal occurrence, Factor fingerprint and Research
Run are distinct. An Agent upgrade changes the default for new sessions only. Backend Generation is still the sole backend
execution/activation binding ledger; Agent session artifact selection is not a competing Generation or Product activation path.

## Migration, retirement and acceptance

The owning [work program](repository-migration-work-program.md#independent-agent-product-migration) specifies A1–A6 order.
Preserve C2's readable preview, independent advanced contract forms, identity rules, exact first confirmation and recovery while
changing physical ownership. Do not mechanically move legacy Python Agent modules: move only real orchestration/model/literature
responsibilities; backend-owned Search/Research/authority behavior must be implemented at its correct Rust boundary.

Retire replaced Rust C2 chat/model hosting and eligible old Python code only after actual consumers, builds/installations,
guards, independent semantic/fault assertions and Shipping UI acceptance pass. Keep still-needed callers explicit; legitimate
Python Agent code and Factor/Indicator SDKs are not deprecated merely for being Python. No permanent dual writer/fallback.
Old disposable development chat rows/model settings are not a migration compatibility target. Any necessary reset must be
explicit/coordinated under AGENTS.md, never implicit startup or test fixture behavior; this task performs none.

Required scenarios include normal chat → staged preview → direct backend confirmation, stale/tampered/foreign proposal denial,
two-service auth isolation, lost acknowledgement/repeated Command, backend effect ahead of checkpoint, independent restarts,
Agent outage during accepted Research, exact old-workflow continuation and missing-workflow pause without new effects/budget
reset. C3 additionally proves separate direct Human authorization and one real immutable-input Research/report, not a chart
study, model-generated metric or fake backend. C4/stage two retain ADR 0145's scope/holdout/attempt/collection requirements.

Only modified modules and direct consumers are verified, through the existing formal dev entry and real Shipping UI where
business behavior changes. Preserve existing guards, deterministic fault tests, bounded independent review and scoped Python
retirement. No whole-repository flow, extra generic tooling, code migration, installation, publication or deployment is
authorized by this design document.
