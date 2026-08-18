# P8.3.1 Research HTTP Contract Boundary Closure

## Problem and root cause

`create_research_app()` starts from the portable Artifact app and then registered another global FastAPI
`RequestValidationError` handler for Research Run commands. That later registration replaced the Artifact validation handler, so an
invalid Artifact query returned the Run command envelope in the full app.

## Invariant and implementation

Artifact routes retain the versioned `{schema_version,code,detail}` query error contract in both the portable and full applications.
Run routes retain `{error:{phase,code,detail}}`. The full app now has one explicit validation handler that dispatches only on the
bounded `/api/v2/research/runs` path family and reuses the two existing response DTOs.

No generic error framework, persistence authority, Run state transition, idempotency rule, Scheduler, Worker, Runtime or Engine behavior
was added or changed. The portable Artifact app remains PostgreSQL-free.

## Regression evidence

The full-app regression covers both an invalid integer `limit` and a non-canonical timestamp query and asserts that neither can leak into
the Run envelope. Existing Run validation tests continue to assert the command envelope, while existing portable Artifact tests retain
the same two Artifact validation cases.

## Verification

- `research-command`: 24 passed; coverage 96.09% (90% gate).
- `research-query`: 78 passed; coverage 100.00% (95% gate).
- OpenAPI export check: byte-stable.
- Web static check: generated TypeScript synchronized; ESLint, Prettier and TypeScript passed.
- Impact verification from task base `d6bcbd3109b791663d1763eee44395877733ddac`: `IMPACT VERIFIED`, 11 gates. Affected
  Ruff/format/mypy, `onlyalpha-api` build, Web static/unit/build/E2E, Research Command (24), Research Query (78), and Research Artifact
  (53) all passed.

P8 remains `IN_PROGRESS`; the next semantic direction remains P8.4 Research Studio Web.
