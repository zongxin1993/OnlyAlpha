# ADR 0146: Independent Agent product and Python LangGraph

- Status: Accepted
- Date: 2026-10-28
- Decision maker: repository owner, approving the independent Agent package, split API interaction, and exact workflow-version continuation, then requesting documentation only.
- Constitution Impact: NO
- Related: ADRs 0104, 0117–0124, 0127, 0130, 0135, 0139, 0141, 0142, 0145.
- Owning architecture: [Independent Agent service](../agent-service-architecture.md).
- Construction order: [Agent extraction sequence](../repository-migration-work-program.md#independent-agent-product-migration).

## Decision

Keep one repository and the existing root Cargo workspace. Add `packages/agent` as a third independently versioned product
alongside backend and frontend. Its implementation is Python with Python LangGraph as the single selected orchestration
framework. Agent can run as its own process on the backend host or another explicitly configured, authenticated server.
No per-role/per-worker product packages, second orchestrator, full RD-Agent/Qlib execution stack or generic agent platform
are selected. The library set, backend, frontend and agent form four main release lines; plugin distribution rules remain.

Agent owns chat, model/provider access and secrets, literature processing, proposed content, orchestration, model/tool
occurrence provenance and Agent research notes/literature memory. Backend retains canonical data/assets, formal Factor acceptance, Human
authorization, Search Experiment/provenance and Research budgets, admission, execution, immutable Evidence, Qualification,
Generation and trading. Existing ADR 0123 Agent budget is distinct from ADR 0120 Search budget. Separate processes never
create competing authorities for the same fact. LangGraph checkpoints are not scientific Evidence, Human consent or a
replacement for durable Agent model/tool/decision records.

Frontend uses Agent API for chat and orchestration, and backend API directly for formal Factor confirmation and Research
authorization. Versioned service APIs are owner-specific parts of the OnlyAlpha API boundary, not alternate control paths
into backend internals. Agent may stage an immutable proposal through the backend API. Backend validates and retains the
exact confirmation input and origin reference before Human acceptance; registration does not publish/admit/execute a Factor.
Neither model prose nor Agent credentials can manufacture Human authorization. Stage two additionally requires a backend-
enforced bounded mandate; stage-one confirmation never becomes blanket autonomous permission.

Agent and backend have separate storage ownership, database credentials/migrations and secret scopes. The default may share
one PostgreSQL service with separate databases; remote Agent deployment may use its own storage. No cross-database joins,
shared business-table access, secret-table reads or distributed transaction coordinator are introduced. Calls use stable
operation identities and owning receipts/queries to reconcile partial success and UNKNOWN.

Each new Agent session pins an exact workflow implementation and dependency artifact, model configuration and relevant
policies. Existing sessions continue using their bound workflow; if it or its supported checkpoint reader is unavailable,
pause visibly without selecting the latest implementation, resetting budget or repeating unknown calls. An explicit linked
new session may be proposed, with applicable confirmations/mandate, but is not continuation under a substituted workflow.

## Alternatives and consequences

1. Keep Agent bundled with backend: fewer release units, but ties high-change model/literature dependencies and independent
   remote deployment to the stable backend lifecycle. Rejected for the owner's chosen independent Agent product.
2. Independent TypeScript LangGraph.js Agent: viable orchestration and UI integration, but Python literature/research tools
   would more often require an additional integration boundary. Python LangGraph was selected for this workload and the
   existing Python runtime experience, not because JavaScript lacks persistence or Human interruption.
3. Independent Python LangGraph Agent: selected. Reuse orchestration and suitable libraries; retain OnlyAlpha-specific
   authority/admission/recovery contracts. Its locked environment is separate from backend's bounded algorithm environment.

Four-line release composition requires evidence for frontend/backend, frontend/agent and agent/backend API combinations.
Only changed selected units advance; package version, workflow identity and Factor semantic identity remain distinct.
Exact Agent artifact retention and checkpoint support are operational obligations for continuing sessions, not a promise
of arbitrary historical compatibility or permission to execute untrusted old code.

## Supersession and limits

Supersedes ADR 0142 only where it limits products to backend/frontend, assigns Agent coordination/deployment to backend,
and omits the Agent release line. Refines ADR 0141's Python scope: backend canonical business remains Rust; the independent
Python Agent owns proposal/orchestration, never a Python backend fallback. Supersedes ADR 0145/C2's backend-hosted chat/model
placement and confirmation routing, preserving its product flow, exact two confirmations and all semantic safeguards.
ADRs 0120/0123/0124/0127 retain their distinct fact identities and authorities; physical ownership is specified in the new
architecture. In particular, ADR 0127 formal Experiment Memory query/index stays with backend Product; Agent research notes
and literature retrieval are not a replacement or parallel novelty index. No existing one-child limit, search algorithm, authorization scope or historical identity is broadened here.

This decision authorizes documentation only. It does not enable routes, create a package/database/environment, migrate C2,
install LangGraph, change current API schemas, delete Python or development data, publish, deploy or grant LIVE permission.
Each implementation phase requires its own bounded task and affected-consumer/real-Web acceptance under AGENTS.md.
