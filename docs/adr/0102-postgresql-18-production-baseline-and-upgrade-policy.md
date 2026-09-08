# ADR 0102: PostgreSQL 18 Production Baseline and Upgrade Policy

- Status: Accepted
- Date: 2026-08-26
- Related: ADR 0089, ADR 0101

## Context

OnlyAlpha's earlier PostgreSQL operational authority was verified against PostgreSQL 16.10. P9.3 now requires one production,
runtime and CI baseline matching the deployed infrastructure, plus an explicit path that preserves existing 16.10 facts while moving
them into that baseline.

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
2. Runtime compatibility accepts major 18 and fails closed for major 16, unknown majors and unsupported future majors.
3. CI and production pin `postgres:18.6`; a floating `postgres:18`, `18` or `latest` image is not verification evidence.
4. Existing ordered, checksummed migration history remains the sole schema authority.
5. Application startup remains compatibility-check only. It never performs a PostgreSQL major upgrade and never auto-migrates a
   production schema.
6. A major upgrade requires an explicit operator procedure and evidence from real pinned PostgreSQL installations.
7. The supported 16.10→18.6 path is an isolated logical custom-format dump/restore using client major 18. It verifies the exact
   migration ledger, schema compatibility and table counts before the target can be admitted.
8. PostgreSQL major version must not affect Dataset, Calculation, Candidate, Strategy, Research Result, Artifact, or other semantic
   identity.
9. A future database major-version baseline change remains an architecture event and requires ADR, migration, recovery, and operator
   evidence.
10. PostgreSQL 18 does not change Research Run UUID4, Dataset identity, Strategy identity or any semantic fingerprint.

## Required baseline and migration evidence

The application and operator path must continue to verify at least:

```text
fresh PostgreSQL 18 database
→ full canonical migration history

existing PostgreSQL 16.10 operational database
→ isolated logical dump/restore test
→ PostgreSQL 18.6

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

Client `pg_dump`, `pg_restore` and `psql` must all be major 18. A 16.10 server may appear only as the explicit upgrade source; it is
not a supported application runtime after this decision.

## Rejected alternatives

- Keeping 16.10 as a parallel supported application baseline.
- Floating major-version container tags as reproducible evidence.
- Startup-driven major upgrade, automatic production migration, or schema repair.
- Using PostgreSQL version or database-generated capabilities as semantic identity input.

## Consequences

PostgreSQL 18.6 is the single deployment and CI baseline. Existing PostgreSQL 16.10 facts have one explicit isolated upgrade path,
while normal application startup rejects major 16 and never performs upgrade or schema mutation. The baseline change does not alter
schema authority, operational identity or semantic fingerprints.
