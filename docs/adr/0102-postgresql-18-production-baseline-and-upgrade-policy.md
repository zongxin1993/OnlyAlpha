# ADR 0102: PostgreSQL 18 Production Baseline and Upgrade Policy

- Status: Accepted
- Date: 2026-08-26
- Related: ADR 0089, ADR 0101

## Context

OnlyAlpha's current PostgreSQL operational authority is verified against PostgreSQL 16.10. The repository pins `postgres:16.10` and
`postgresql-client-16`, and ADR 0089 records that version as tested evidence. PostgreSQL 18 is the intended future production major
baseline, but a target declaration is not migration or verification evidence.

The project must record the future direction without rewriting current truth, changing authoritative SQL prematurely, or allowing a
database implementation version to enter semantic identity.

## Decision

The baseline states are frozen as follows:

```text
CURRENT VERIFIED BASELINE
PostgreSQL 16.10

FUTURE TARGET MAJOR BASELINE
PostgreSQL 18.x

MIGRATION STATUS
PLANNED / NOT YET VERIFIED
```

The following rules apply:

1. The future OnlyAlpha PostgreSQL production major baseline is PostgreSQL 18.
2. Migration to PostgreSQL 18 is a separate infrastructure correctness task.
3. CI and production must pin one exact supported 18.x patch when that migration occurs. A floating `postgres:18` image is not
   verification evidence.
4. Existing ordered, checksummed migration history remains the sole schema authority.
5. Application startup remains compatibility-check only. It never performs a PostgreSQL major upgrade and never auto-migrates a
   production schema.
6. A major upgrade requires an explicit operator procedure and evidence from real pinned PostgreSQL installations.
7. PostgreSQL-18-specific SQL or features are forbidden in authoritative paths until the PostgreSQL 18 migration task is VERIFIED.
8. PostgreSQL major version must not affect Dataset, Calculation, Candidate, Strategy, Research Result, Artifact, or other semantic
   identity.
9. A database major-version baseline change is an architecture event and requires ADR, migration, recovery, and operator evidence.
10. P9.K.3 does not change container images, client packages, schema SQL, migration SQL, Research Run UUID semantics, or production
    deployment configuration. UUID4 remains unchanged; PostgreSQL 18 capability does not authorize UUIDv7 migration.

## Required PostgreSQL 18 migration evidence

A later migration task must verify at least:

```text
fresh PostgreSQL 18 database
→ full canonical migration history

existing PostgreSQL 16 operational database
→ explicit supported major-upgrade path
→ PostgreSQL 18

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

research-postgres --coverage
→ PASS
```

The exact supported PostgreSQL 18.x patch must be selected, pinned, and recorded at migration time.

## Rejected alternatives

- Treating the future target as if it were already verified.
- Switching CI or client packages during P9.K.3 without PostgreSQL 18 migration evidence.
- Floating major-version container tags as reproducible evidence.
- Startup-driven major upgrade, automatic production migration, or schema repair.
- Using PostgreSQL version or database-generated capabilities as semantic identity input.

## Consequences

PostgreSQL 16.10 remains the current verified authority while PostgreSQL 18.x is a clear future production target. The later migration
has an explicit correctness boundary and cannot silently alter schema authority, application startup, operational identity, or semantic
fingerprints.
