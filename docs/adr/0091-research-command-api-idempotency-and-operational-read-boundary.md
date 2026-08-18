# ADR 0091: Research Command API Idempotency and Operational Read Boundary

- Status: Accepted
- Date: 2026-08-18
- Related: ADR 0085, 0088, 0089, 0090

## Context

P8.2 established PostgreSQL `ResearchRun + ResearchRunAttempt` as the durable operational authority and fenced every Worker outcome.
External clients still cannot reliably submit, inspect or cancel a Run. A response can be lost after commit, concurrent retries can race,
and a cancellation can race with Worker claim or completion. A transport wrapper around the existing admission service would acknowledge
before a replay identity existed and would re-run environment-dependent admission after a successful but unobserved commit.

## Decision

Core exposes a transport-neutral Research Command/Application boundary. `OnlyResearchSpecification` and its resolver remain the only
request semantic authority; `ResearchRun` remains the only lifecycle transition authority; the PostgreSQL Execution Store remains the
only Attempt/lease/fence and Worker-finalization authority. Command code never reads Artifact content or starts Scheduler, Worker,
Runtime or Engine. Artifact Query remains a portable, PostgreSQL-free read plane.

Submission requires a canonical UUID4 `Idempotency-Key`. The command fingerprint is the SHA-256 fingerprint of canonical JSON containing
the strict canonical Specification document. The key is a retry identity, not a Specification identity: the same key and command returns
the original Run, the same key and a different command conflicts, and different keys create different Runs even for the same
Specification.

Migration `0004_research_run_submission_and_read_projection` adds `research_run_submission` and a descending Run read index. The first
submission inserts the revision-zero QUEUED Run and its submission mapping in one transaction. HTTP returns `202 Accepted` only after
commit. A unique-key race rolls the whole transaction back, reloads the winner and compares the command fingerprint; no orphan Run can
remain. Replay computes only strict canonical command identity and does not repeat resolver or Dataset verification.

The operational read boundary returns exact Run facts and structured failure, never Result/Artifact content or Attempt history. Recent
Runs use `(queued_at DESC, run_id DESC)` keyset order. A versioned canonical JSON/base64url cursor contains only the exact UTC timestamp and
canonical UUID4 needed for that order. Unknown fields, non-canonical encoding, timestamp or UUID fail closed; offset pagination is absent.

Cancellation loads the Run, asks the Domain state machine for `QUEUED -> CANCELLED` or `RUNNING -> CANCEL_REQUESTED`, and commits through
revision/state CAS. A conflict reloads and reinterprets the command with a fresh UTC time, for at most three attempts. Existing
`CANCEL_REQUESTED` and `CANCELLED` are idempotent without a revision increment; `COMPLETED` and `FAILED` conflict. The API never creates or
updates an Attempt and never forces a running Run directly to CANCELLED.

HTTP extends `/api/v2`: POST/GET/list/cancellation routes use strict transport DTOs and stable phase/code/detail errors. The full Research
app combines independent Artifact and Run routers; the portable Artifact app retains only GET Artifact routes and requires no PostgreSQL.
The full server reads its DSN from `ONLYALPHA_POSTGRES_DSN`, checks schema compatibility without migrating, derives Dataset/Artifact roots
from `OnlyUserDataLayout`, discovers Calculation plugins, and binds loopback by default. There is no permissive CORS or authentication
claim; non-loopback/public deployment is outside this stage.

## Consequences

- API/process/browser restart preserves Run lookup and submission replay because no process-local state is authoritative.
- Network ambiguity after commit is resolved by replaying the same key and canonical command.
- Cancellation races converge through the existing Run CAS and fenced Worker protocol.
- PostgreSQL stores command identity and operational references only; immutable semantic content remains outside it.
- P8.4 can consume stable Run DTOs and client methods but this increment adds no page, form, progress, streaming or interactive builder.

## Rejected alternatives and non-goals

Rejected: Specification-fingerprint global deduplication, in-memory locks/maps, Redis, serializable transactions, generic CRUD repository,
offset pagination, API-owned Run state transitions, direct Attempt updates, execution in an HTTP request, Artifact content in command
responses, automatic migration, permissive CORS, SSE/WebSocket, pause/resume/delete/manual retry, multi-user/RBAC and P8.4 UI work.
