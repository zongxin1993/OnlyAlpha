# ADR 0102: PostgreSQL 18 Production Baseline and Upgrade Policy

- Status: Accepted
- Date: 2026-08-26
- Related: ADR 0089, ADR 0101

## Context

OnlyAlpha's earlier PostgreSQL operational authority was verified against an older major version. The current product requires one
production, runtime, deployment, CI and test baseline matching the deployed infrastructure. Compatibility and operator support for that
older major are now retired; the immutable migration ledger remains intact.

The transition must preserve existing migration truth and must not allow a database implementation version to enter semantic identity.

## Decision

The supported baseline is frozen as follows:

```text
SERVER / CI IMAGE
PostgreSQL 18.6

CLIENT TOOL MAJOR
18

SUPPORTED RUNTIME FAMILY
18.x, pinned to 18.6 for deployment and CI evidence
```

The following rules apply:

1. The OnlyAlpha PostgreSQL production and integration baseline is PostgreSQL 18.6.
2. Runtime compatibility accepts major 18 only and fails closed generically for every other major.
3. CI and production pin `postgres:18.6`; a floating `postgres:18`, `18` or `latest` image is not verification evidence.
4. Existing ordered, checksummed migration history remains the sole schema authority.
5. Application startup remains compatibility-check only. It never performs a PostgreSQL major upgrade and never auto-migrates a
   production schema.
6. No legacy-major upgrade command, deployment topology, CI service, test fixture or compatibility contract is supported.
7. PostgreSQL major version must not affect Dataset, Calculation, Candidate, Strategy, Research Result, Artifact, or other semantic
   identity.
8. A future database major-version baseline change remains an architecture event and requires a new explicit ADR and task with migration,
   recovery, compatibility and operator evidence.
9. PostgreSQL 18 does not change Research Run UUID4, Dataset identity, Strategy identity or any semantic fingerprint.

## Required baseline and migration evidence

The application and operator path must continue to verify at least:

```text
fresh PostgreSQL 18 database
→ full canonical migration history

schema ledger/checksums
→ preserved

Research Run
→ load / transition / CAS

Attempt / lease
→ concurrency / fencing

backup
→ restore-test

research-product-closure
→ PASS

research-postgres
→ PASS
```

Client `pg_dump`, `pg_restore` and `psql` must all be major 18. No older-major server is part of current deployment, CI, tests or operator
support.

## Rejected alternatives

- Keeping an older major as a parallel supported application baseline or upgrade topology.
- Floating major-version container tags as reproducible evidence.
- Startup-driven major upgrade, automatic production migration, or schema repair.
- Using PostgreSQL version or database-generated capabilities as semantic identity input.

## Consequences

PostgreSQL 18.6 is the single production, deployment, CI and test baseline. Normal application startup rejects every other major and never
performs upgrade or schema mutation. No legacy-major upgrade command or compatibility topology remains. This policy does not alter schema
authority, operational identity or semantic fingerprints.
