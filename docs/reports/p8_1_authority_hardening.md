# P8.1 Authority Hardening Closure

- Date: 2026-08-17
- `TASK_BASE_SHA`: `c1cdcbb5771fda76200be9bdd5ee75885e26ac76`
- Implementation HEAD: `c1cdcbb5771fda76200be9bdd5ee75885e26ac76` with intentional dirty task worktree
- Authority: local implementation and real PostgreSQL 16.10 evidence; not P8 Final-SHA certification

## Task Gate and authority boundaries

This closure fixes two integrity gaps without changing P8.1 ownership or adding P8.2 behavior. Repository migration files in deterministic
filename order remain the canonical schema history; PostgreSQL's checksummed ledger remains the durable applied-history fact.
`OnlyResearchRun` remains the unique lifecycle consistency authority; PostgreSQL mirrors its core durable fact boundaries defensively, and
the Store continues to accept only exact Domain successors through revision/state CAS.

No Scheduler, Worker, Attempt, claim, lease, heartbeat, retry, HTTP, Web, semantic Store or new semantic fingerprint was added. Admission,
Specification resolution, Dataset verification and all Calculation/Statistics/Research Result/Artifact identities are unchanged.

## Problem 1: migration history exact-prefix integrity

The original status implementation converted ledger rows to a mapping and computed pending migrations as Repository membership minus
applied membership. That could classify known but non-prefix histories such as `[M2]`, `[M1, M3]`, or an old `[M1]` after Repository
prepended `M0` as `BEHIND`, then plan migrations around a historical hole.

The implemented invariant is:

```text
applied_ids == repository_ids[:len(applied_ids)]
```

for checksum-equal known migrations. Status evaluates a missing ledger first, then unknown IDs as `AHEAD`, known-ID checksum differences
as `CHECKSUM_MISMATCH`, and known but non-prefix order/history as the new stable `HISTORY_DIVERGED`. Only an exact strict prefix is
`BEHIND`; equality is `COMPATIBLE`. Diverged status exposes no pending migrations. `assert_compatible()`, `plan()`, `migrate()` and
application compatibility checks all fail closed for divergence.

`plan()` now returns the Repository tuple slice beginning at the applied prefix length. It no longer uses a set or set difference. Ledger
load remains explicitly `ORDER BY migration_id`; the fixed four-digit migration filename/ID convention makes this the same canonical
lexical order used by deterministic Repository discovery.

## Published migration and forward hardening

Published `0001_research_run_operational_authority.sql` remains byte-for-byte unchanged. Its frozen SHA-256 is
`3e7d6564dc83a062ea2954f7eb23255065c39b3f6398115cde3e2719954062b0`, verified against both Git HEAD and an architecture regression.

New `0002_research_run_authority_hardening.sql` only adds named constraints for:

- lifecycle timestamp monotonicity and cancellation requiring a start;
- RUNNING having no durable cancellation request;
- COMPLETED and FAILED requiring started execution;
- the two exact CANCELLED shapes;
- Artifact reference implying Research Result reference.

It contains no data update or repair. Schema changes and the M2 ledger append use the existing single advisory lock and one transaction.
A legal M1 Run is preserved exactly through M1 to M2 and reloads as the same Domain object. An M1 row that was previously database-valid
but has RUNNING plus a cancellation request makes M2 fail; the transaction leaves both the row and M1-only ledger unchanged.

Real PostgreSQL tests also prove fresh M1+M2 installation, exact M2-only upgrade planning, `[M2]`, `[M1, M3]` and Repository-prepend
divergence, no database change after diverged plan/migrate attempts, independent M1/M2 checksum mismatch, unknown-ID AHEAD, migration
transaction rollback and advisory-lock serialization.

## Problem 2: ResearchRun operational fact integrity

`OnlyResearchRun.__post_init__()` now enforces:

```text
queued_at <= started_at <= cancel_requested_at <= finished_at
```

for timestamps that exist, including `cancel_requested_at` requiring `started_at`. RUNNING forbids `cancel_requested_at`; COMPLETED and
FAILED require `started_at`; Artifact reference globally requires Research Result reference. Existing QUEUED, active/terminal timestamp,
completion-reference and structured-failure contracts remain.

CANCELLED preserves both legal lifecycle facts: direct `QUEUED -> CANCELLED` has neither start nor cancellation-request timestamp, while
`RUNNING -> CANCEL_REQUESTED -> CANCELLED` has both. Mixed shapes are rejected. Completion and failure after CANCEL_REQUESTED remain valid,
and FAILED can retain an already committed Result reference. Every transition still reconstructs `OnlyResearchRun`, and the Store still
checks `is_exact_successor_of()` before CAS persistence.

Direct PostgreSQL writes now reject COMPLETED/FAILED without start, RUNNING with cancellation, cancellation before start, finish before
start, finish before cancellation, and Artifact without Result. Existing two-connection same-revision CAS still has exactly one winner.

## Verification evidence

- Initial `verify.py plan --base c1cdcbb...`: `DOCS_ONLY`, because only user-supplied Prompt changes existed before implementation.
- `research-run --coverage`: 42 passed; 100.00% lines and 100.00% branches.
- Real PostgreSQL 16.10 `research-postgres --coverage`: 29 passed; adapter 89.62% lines / 76.19% branches, aggregate gate 87.40% against the
  current 82% threshold; backup/isolated restore used matching PostgreSQL 16.10 client tools.
- M1 legal upgrade, invalid-M1 rollback, fresh M1+M2, divergence, direct constraints, CAS, admission/re-resolution and backup/restore all
  passed.
- Final impact plan: `COMPONENT`, selecting `release-static`, `research-run` and `research-postgres` only.
- `verify.py agent --base c1cdcbb...`: `IMPACT VERIFIED`; affected Ruff, format, mypy, import-linter and both selected lanes passed
  (6 gates; 42 Research Run and 29 PostgreSQL tests collected).
- Verification infrastructure was not modified, so no FULL_LOCAL self-change escalation was required.

## Known limitations and P8.2 readiness

This closure does not make PostgreSQL a semantic authority and does not add long-running execution. Manual investigation remains required
for a diverged history; there is intentionally no repair/force/skip path. PostgreSQL 16.10 is the tested authority, not a broad deployment
matrix. Within the P8.1 boundary, migration history and ResearchRun now have strictly proven legal state spaces and are ready for P8.2 to
build Attempt/claim/lease/Worker behavior through a future forward migration. P8 itself remains in progress and uncertified.
