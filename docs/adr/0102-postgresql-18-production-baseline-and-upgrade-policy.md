# ADR 0102: PostgreSQL 18 Production Baseline and Upgrade Policy

- Status: Accepted
- Date: 2026-08-26
- Related: ADR 0089, ADR 0101

## Context

P9.3 requires one PostgreSQL production, runtime and CI baseline matching the deployed infrastructure. Maintaining fixtures, operator
commands or CI services for another server family would create a parallel compatibility surface without current product authority.

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
2. Runtime compatibility accepts major 18 and fails closed for every other major, unknown versions and unsupported future majors.
3. CI and production pin `postgres:18.6`; a floating `postgres:18`, `18` or `latest` image is not verification evidence.
4. Existing ordered, checksummed migration history remains the sole schema authority.
5. Application startup remains compatibility-check only. It never performs a PostgreSQL major upgrade and never auto-migrates a
   production schema.
6. A future major upgrade requires a new explicit architecture decision, operator procedure and evidence from real pinned PostgreSQL
   installations; the current repository provides no legacy-major upgrade command or test topology.
7. PostgreSQL major version must not affect Dataset, Calculation, Candidate, Strategy, Research Result, Artifact, or other semantic
   identity.
8. A future database major-version baseline change remains an architecture event and requires ADR, migration, recovery, and operator
   evidence.
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

Client `pg_dump`, `pg_restore` and `psql` must all be major 18. No other PostgreSQL server family is part of the application, test,
deployment or CI contract.

## Rejected alternatives

- Keeping another server family as a parallel application, migration-test or CI baseline.
- Floating major-version container tags as reproducible evidence.
- Startup-driven major upgrade, automatic production migration, or schema repair.
- Using PostgreSQL version or database-generated capabilities as semantic identity input.

## Consequences

PostgreSQL 18.6 is the single deployment, application and CI baseline. Normal application startup rejects every other major and never
performs upgrade or schema mutation. Backup/restore testing remains within the admitted PostgreSQL 18 family. The baseline policy does
not alter schema authority, operational identity or semantic fingerprints.
