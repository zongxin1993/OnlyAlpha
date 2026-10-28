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

## A3 proposal API and acceptance boundary

The scoped Product seam is `/api/v2/factor-proposals`. An Agent registers an unadmitted immutable snapshot; only a separately
verified backend Human session can confirm it. These interfaces are the prerequisites for the Shipping C2 interaction below; technical API proofs alone do not establish Web acceptance.

A Human-authorized grant is registered at `POST /api/v2/factor-proposal-grants` and revoked at
`POST /api/v2/factor-proposal-grants/revocations`. Both use global Command identities. Grant input includes a UUID, service
subject, SHA-256 of a separately provisioned credential, a finite proposal limit and UTC expiry; owner comes from authenticated
backend Human identity, never the request body. Credential provisioning is infrastructure work: a CSPRNG secret is delivered
only to the Agent deployment, not through browser/model output. The credential is `oa-proposal-v1.<grant UUID>.<32-byte hex
secret>`; its digest includes the entire audience-prefixed credential. Agent-audience JWTs, backend Human Cookies and model keys
are not interchangeable with it. No default grant/secret or automatic enrollment is installed.

This grant permits only registration and scoped context/snapshot/original-command queries. It owns no Source-data, Research,
confirmation, Generation or trading permission. Objects are confined to the backend-derived Factor namespace for the authenticated
owner, service subject and Agent chat session. The backend counts registered snapshots per grant independently of Agent model-call
usage; replay does not consume a second slot. Every request verifies the owning grant, expiry and revocation. Revocation cuts off
existing proposal responses through the retained ingress physical write fence; conservatively it invalidates all in-flight proposal
responses on this node. Human access to already registered owned input does not require a live Agent or active Agent grant.
The presented credential in ingress is untrusted routing/capacity context, not a Human/Source proof; only the owning database
transaction grants service access. Existing Human Cookie, Source and denied `/api/v2/agent`/LIVE boundaries remain.

`GET /api/v2/factor-proposal-context/{session_id}` returns the granted owner/service and exact current Authoring/display/proposal
bases. `POST /api/v2/factor-proposals` binds these bases and the exact Agent session, model occurrence/result, model revision and
workflow fingerprints. Backend derives the restricted V1 expression's formula, declared dependencies and Factor source together
using the existing authoring logic. Arbitrary model code, extra candidate fields or unsupported expressions are refused. The
snapshot retains this complete input with Agent origin; registration creates no Factor, Revision, execution admission or Evidence.
It is not an ADR 0123 Research Session/Decision or an alternate Factor registry.

`GET /api/v2/factor-proposals/{fingerprint}` returns the exact snapshot, whether it remains the current registered input and any
confirmed owning receipt. A newer registration must match the prior registered head and supersedes it. Only
`POST /api/v2/factor-proposals/{fingerprint}/confirmation` with a backend Human session can confirm; the body must name that exact
fingerprint. Confirmation rechecks the current head and exact draft/display bases, rejects intervening edits/publication, and
atomically records the existing Authoring save/display effects and global receipt. It does not publish a Factor Revision or execute
anything. Original command queries at `/api/v2/factor-proposals/commands/{command_id}` reconcile exact identities; receipt/effect
records are append-only and checked against the retained request, global Command and owning Authoring bindings.
A confirmation query proves the Human operation family, exact target and deterministic mandatory save child; an unrelated valid
receipt is not confirmation. The mutable head must match the unique terminal snapshot in its complete verified supersession chain.
A missing, foreign or rolled-back projection is unavailable/corrupt, not certified absence or a proved non-current snapshot.

In Agent API, `POST /api/v1/agent/sessions/{session_id}/proposals` stages the exact current model occurrence. Its independent local
idempotency key is durably linked to a distinct backend Command before submission. Backend context owner must equal the authenticated
Agent user. Connection/credential binding is frozen with the plan; credential rotation cannot silently resubmit an old operation.
Only a newly committed plan may send its one POST. Lost acknowledgement or process failure leaves UNKNOWN; replay queries the original
backend Command and reuses a verified receipt, never makes a new identity or automatically resends. The receipt is recorded before
the synchronous LangGraph checkpoint; repairing that checkpoint only loads the exact recorded occurrence and cannot submit effects.
Reading a cached receipt rechecks its Command relation as well as its digest. Observed refusal/uncertainty is
recorded separately from a successful owning receipt. `GET .../proposals/{local_command_id}` queries the registered snapshot from the
backend afresh for confirmation status; cached Agent chat/receipt data does not become current backend truth. Backend outage leaves
ordinary Agent history readable but blocks staging/authoritative status observation.

Agent settings use an explicit `ONLYALPHA_AGENT_BACKEND_URL` and protected
`ONLYALPHA_AGENT_BACKEND_CREDENTIAL_FILE`; neither is a model setting or a backend Human credential. Protected remote transport is
required; the existing backend physical deployment gate is not broadened by this client. No proxy trust or new server topology is
implicitly enabled. A4 must provide the coherent sign-in/configuration experience and invalidate pending UI input before editing;
private chat text alone does not mutate a backend-registered snapshot. Delayed UI responses must use the exact registered head.

Migration 0059 extends backend-owned Command kinds and adds grant/snapshot/operation facts plus a replaceable current-head projection.
It is transactional under the existing migration entry: any failure rolls back schema changes, and confirmation failure rolls back
all Authoring/Command effects. Existing facts and fingerprints are not rewritten. Agent adds only its own backend-call plans,
observations and receipt references to its separate store. Startup/tests never migrate backend data through Agent credentials.
Superseded Rust C2 chat/model writers are removed at the A4 cutover. Still-consumed Python Research orchestration/model-profile
implementations remain subject to their actual A5/A6 consumer closure; they are not a fallback for this page. Migration 0058 remains
schema provenance without a serving C2 reader/writer or development-history conversion path.


## Shipping C2 interaction and independent lifecycle

The ordinary Factor Research page configures models and persists discussion through Agent API v1. It reads the canonical preview
from backend `/api/v2/factor-proposals/{fingerprint}` and submits the first Human confirmation directly to backend. It never submits
confirmation through Agent. Model-generated content alone cannot create a Factor, publish a Revision, run Research or activate a
Generation. Existing advanced authoring forms continue to use the same Authoring Authority.

Backend `POST /api/v2/agent-browser-access` exchanges an already verified Human session for a short-lived, Agent-audience assertion.
It is an operational authentication step, not a business grant. Its fixed issuer is `onlyalpha-backend-browser-v1`; subject comes
from the verified Human and scopes are only `chat:read`, `chat:write`, `model:write`. A dedicated protected browser-assertion key is
separate from Human Cookies, model keys, Agent's own signing/encryption keys and the proposal service credential. Agent verifies the
issuer, signature, audience, expiry and its own durable revocation facts. This assertion grants no backend permission. Browser calls
Agent with `credentials: omit` and the intended bearer; Cookies and forwarded identity headers are refused. CORS permits only the
configured Web origin, without credentialed requests or wildcards. A cached Agent assertion permits an already loaded page to read
owned history during backend outage; it does not independently serve the frontend while backend's static host is stopped.

`GET /api/v2/agent-connection` exposes only public connection metadata and the exact Human-owned grant state. A discoverable Web
action explicitly enables a finite proposal-registration grant (100 snapshots, 24 hours). There is no startup grant, copied service
secret, model enrollment or execution consent. Configuration errors, expired/revoked grants and independent service outages remain
visible. The browser-assertion binding pins the Agent endpoint/issuer/subject for pending interactions; reconnecting cannot silently
move an unresolved command to another service installation.

An edited text draft disables local confirmation. Before submitting that changed idea, Web explicitly withdraws the registered
snapshot using backend Human `POST /api/v2/factor-proposals/{fingerprint}/withdrawal`. Withdrawal is an immutable, globally receipted
Command, serialized with confirmation and head changes. It blocks a stale tab even while a new model response is pending. It does
not undo accepted Authoring or erase historical confirmation. A newly registered snapshot still CAS-checks the exact prior head and
Authoring/display bases. Delayed responses are displayed only for the selected session and exact event head.

Agent `GET /api/v1/agent/commands/{id}` distinguishes UNKNOWN, accepted owning effect and an explicit local abandonment tombstone.
`POST .../commands/{id}/abandon` fences a not-yet-accepted interaction under the same lock; it never cancels an accepted call or any
backend operation. Model secrets are never retained in browser pending metadata. Proposal staging has one durable plan per model
occurrence. `POST .../sessions/{session}/proposals/{id}/resume` loads that plan and only reconciles the original backend Command or
repairs its recorded checkpoint. It cannot create a new plan or repeat the first POST. UNKNOWN is not certified absence; missing or
malformed mandatory owning relations are not accepted effects. Optional model/backend results are not prerequisites for occurrence
existence. A lost Human confirmation, withdrawal or grant response is reconciled against its original backend Command. Explicit same-identity
replay preserves the complete original target/body (including grant expiry); it cannot become a second business identity. A staging
refusal does not certify nonacceptance: Web may explicitly return to history while retaining the exact plan. Reopening that original
session remains read-only pending reconciliation; another session requires an explicit Human action and distinct namespace.

Infrastructure may package the exact independently installed Agent closure beside the selected local runtime composition. Its
manifest pins Agent version, workflow, project/contract bytes and every bundled file; this does not couple Agent's release version
to backend. The Agent interpreter has no backend/root distribution on its import path. Installation and operator provisioning are
explicit build/deployment actions: a dedicated unprivileged Agent database, separate protected keys and a digest-only backend
connection descriptor. Partial or conflicting provisioning is refused, not repaired or overwritten automatically.

In the sole dev topology the infrastructure supervisor owns two separate processes. Backend never imports or starts Agent.
A configured Agent has its own state volume and explicit loopback publication `127.0.0.1:5174`; backend/Web remain on 5173. The
contained transport exception requires the host-inspected container/network/publication record and exact client peer/Host checks;
remote listeners retain explicit TLS requirements. Normal source edits reuse the fixed tools; there is no extra Compose stack,
startup dependency installation, automatic service restart or model fallback. An unavailable process remains visibly unavailable
until an explicit lifecycle action. Fixed-image validation uses isolated test databases and the same selected Shipping artifacts.
