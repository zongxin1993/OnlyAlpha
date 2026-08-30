# OnlyAlpha P9.3 — Durable Market Data Platform
## Codex Implementation Task Prompt

> Repository: `zongxin1993/OnlyAlpha`
>
> Task: **P9.3 — Production Data Foundation / Durable Market Data Platform**
>
> Current execution scope: **Binance Spot Golden Vertical only**
>
> Reference instruments: `BTCUSDT`, `ETHUSDT`
>
> Required first data families: **Raw Provider Evidence + Canonical Trade + Closed 1m Bar + Market Reference**
>
> Task type: **High-risk persistence / authority / recovery task**

---

# 0. Mission

Implement the first production-grade, provider-neutral durable market-data authority for OnlyAlpha.

This is **not** a task to “store Binance data in ClickHouse”.

The real problem is:

```text
provider facts are transient
+ processes crash
+ networks disconnect
+ databases can be unavailable
+ historical data can later be repaired
+ normalizers can later be corrected
+ realtime and REST backfill can overlap

therefore

mutable database rows cannot be the semantic truth
```

P9.3 must establish one deterministic evidence chain:

```text
Provider Raw Evidence
        ↓
Canonical Market Fact
        ↓
Durable WAL / Segment
        ↓
ClickHouse Typed Fact Storage
        ↓
Verification
        ↓
PostgreSQL Manifest / Coverage / Revision
        ↓
SEALED Market Data Revision
        ↓
Immutable Dataset Snapshot
        ↓
Research / Backtest
```

The permanent target is:

> **No overwrite. No silent correction. No mutable historical truth.**

And:

> **At-least-once physical processing is acceptable; duplicate semantic truth is not.**

---

# 1. Mandatory repository authority rules

Before editing, read the current repository and obey the current repository truth.

Read at minimum:

```text
AGENTS.md
docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md
docs/adr/0105-repository-truth-and-bounded-task-acceptance.md
docs/p9_binance_spot_golden_vertical_execution_plan.md
docs/p9_production_trading_vertical_architecture.md
```

Also inspect the current implementations of:

```text
Binance Spot DataSource
Binance historical/realtime normalization
OnlyHistoricalCacheService
market-data canonical identities/models
Dataset Snapshot / Dataset materialization
PostgreSQL migration authority
scripts/database.py
existing persistence/store interfaces
current test-suite / quality-policy lanes
```

Rules:

1. Current source + current tests + current executable behavior define what is currently implemented.
2. ADR / Architecture / Contract define frozen long-term constraints.
3. Do not use old reports, old prompts, old Final-SHA records, or removed project-state machinery as completion authority.
4. Do not create a new progress/status/closure-report authority.
5. Do not perform an open-ended repository audit.
6. Do not reopen P9.1/P9.2 foundations unless a real P9.3 dependency proves a current defect.
7. If current source has evolved, adapt class/file names to repository truth while preserving the invariants in this task.

At task start, state in the working response only:

```text
Base SHA
Goal
Modification Scope
Expected Impact Scope
Required Behavior
Acceptance Tests
Out of Scope
Stop Condition
```

Do not commit a task-state file for these fields.

---

# 2. Current sequencing constraint

ADR 0099 is authoritative for the current P9.1+ implementation order.

P9.3 is **Spot-only for the first Golden Vertical**.

Implement now:

```text
Provider: Binance Spot
Symbols: BTCUSDT, ETHUSDT

Data:
- raw provider evidence
- canonical raw Trade
- canonical closed 1m Bar
- canonical Market Reference already provided by current P9.2
```

Do NOT make Binance USD-M Futures provider implementation a P9.3 completion dependency.

Future-capable provider-neutral Core contracts are allowed only where they are naturally required by the current stable abstraction.

Do not implement speculative data families merely because they may exist later.

---

# 3. First-principles correctness model

P9.3 must preserve four different truths.

## 3.1 External raw truth

```text
Raw Provider Evidence
=
“What did the provider actually send / return?”
```

This evidence must preserve provider payload and provenance without making provider DTO types part of Core.

## 3.2 Canonical semantic truth

```text
Canonical Market Fact
=
“How did OnlyAlpha interpret this provider evidence?”
```

This is provider-neutral typed data such as Trade, Bar and Market Reference.

## 3.3 Historical set truth

```text
Market Data Revision / Manifest
=
“Which exact verified set of canonical facts constitutes this historical version?”
```

This is not equivalent to “whatever rows are currently in ClickHouse”.

## 3.4 Research input truth

```text
Immutable Dataset Snapshot
=
“What exact immutable data did this Research / Backtest consume?”
```

A Dataset Snapshot remains the formal Research/Backtest input boundary.

These four truths must never be collapsed into one table or one mutable `latest` query.

---

# 4. Accuracy requirements

Accuracy is not just numeric price equality.

P9.3 must preserve all of the following dimensions.

## 4.1 Semantic accuracy

A Trade remains a Trade.
A closed external Bar remains an external Bar.
A venue-declared Market Reference remains its exact semantic kind.
Raw evidence is not canonical evidence.

No provider payload may be reinterpreted through a generic untyped JSON path.

## 4.2 Identity accuracy

The same semantic provider fact must resolve to the same canonical identity independent of:

```text
realtime delivery
REST backfill
replay after crash
duplicate transport delivery
restart
```

Reuse existing OnlyAlpha canonical identity functions where they already express the correct identity.
Do not create a competing fact-ID algorithm.

## 4.3 Temporal accuracy

Preserve exact canonical timestamp precision.
Do not silently reduce nanosecond or exact integer time semantics to lower-precision database fields.

Keep distinct where applicable:

```text
provider/event time
receive time
ingest time
```

Only event/effective time belongs to semantic market-fact identity unless the existing domain contract explicitly says otherwise.

## 4.4 Decimal accuracy

Financial price/quantity/notional values must round-trip exactly.
Do not convert authoritative Decimal values to binary float for persistence convenience.

Select ClickHouse physical types from the current canonical Decimal contract and prove exact round-trip in tests.

## 4.5 Coverage accuracy

“Rows exist” is not “history is complete”.

Coverage must be an explicit verified fact appropriate to the data family.

Examples:

```text
Bar
→ expected time-grid/range continuity

Trade
→ provider event identity / history coverage semantics

Market Reference
→ explicit state/event coverage semantics, not fake continuous events
```

Do not invent missing data to satisfy coverage.

## 4.6 Provenance accuracy

The system must be able to distinguish at least:

```text
REALTIME_STREAM
REST_BACKFILL
REPAIR
REPLAY
```

Two different evidence paths may prove the same canonical fact.
That must not create two semantic facts.

## 4.7 Revision accuracy

A correction changes the historical revision, not the past.

```text
R1 remains immutable
correction evidence arrives
R2 is created
```

Never UPDATE sealed historical facts merely to make current queries look clean.

---

# 5. Uniqueness requirements

OnlyAlpha uniqueness is semantic, not merely a database UNIQUE constraint.

P9.3 must enforce:

```text
One semantic fact
→ one canonical identity

One segment
→ one immutable content identity

One sealed revision
→ one exact ordered manifest fingerprint

One coverage conclusion
→ one explicit revision-scoped proof

One Dataset materialization request + one sealed revision
→ deterministic Dataset fingerprint
```

Important:

Do NOT attempt to solve the whole pipeline with a fictional distributed “exactly once” transaction across:

```text
local filesystem WAL
ClickHouse
PostgreSQL
```

There is no single natural atomic commit across those three systems.

Correct model:

```text
at-least-once replay
+
deterministic identities
+
immutable segment content
+
idempotent store/verify
+
explicit commit protocol
=
exactly-one semantic result
```

---

# 6. Authority split — must remain explicit

Freeze this authority model.

## 6.1 Provider adapter

Owns:

```text
provider protocol interpretation
raw payload capture metadata
provider-specific normalization
```

Does NOT own:

```text
ClickHouse SQL
PostgreSQL schema
Market Data Revision selection
Dataset identity
```

## 6.2 WAL / spool

Owns:

```text
durable uncommitted ingress evidence
crash boundary before database commit
```

It is not the long-term semantic query authority after committed revision creation.

## 6.3 ClickHouse

Owns physical durable high-volume market facts / query storage.

It does NOT own:

```text
which historical revision is authoritative
coverage completeness
runtime lifecycle
strategy
promotion
```

## 6.4 PostgreSQL

Owns control/catalog facts such as:

```text
capture session
ingest segment metadata
coverage manifest
market-data revision
seal / recovery records
schema/provenance catalog
```

It does NOT store billions of market rows.

## 6.5 Dataset Snapshot store

Owns immutable Research/Backtest input.

It must never be replaced by a mutable ClickHouse query.

## 6.6 Historical Cache

Existing cache remains:

```text
performance/reuse layer
rebuildable
non-authoritative
```

Do not silently promote `OnlyHistoricalCacheService` or its store into production durable market-data truth.

---

# 7. Required domain model — Domain First, Schema Second

Before writing database DDL, define the minimal provider-neutral domain/API contracts.

Use current naming conventions and existing identifiers where possible.
Do not create duplicates of existing concepts.

Conceptually the model must cover the following.

## 7.1 Capture session

Represents one bounded provider capture context.

Equivalent facts:

```text
capture_session_id
source_id
provider/venue/market identity
started_at
ended_at when closed
schema/codec identities
capture mode / provenance
```

## 7.2 Raw provider evidence

Provider-neutral envelope; provider payload remains opaque bytes/text plus metadata.

Equivalent fields:

```text
raw_event_id
source_id
capture_session_id
provider event type
provider event id if available
provider sequence if available
provider/event time if available
receive time
payload codec
provider schema identity/version
raw payload
raw SHA-256
stream/endpoint identity
```

Forbidden:

```text
pickle SDK objects
repr(Python DTO)
provider object stored as Core domain
```

## 7.3 Canonical fact record

Bind current canonical fact identity to raw evidence and normalization provenance.

Equivalent fields:

```text
canonical_fact_id
raw_event_id or evidence references
canonical data kind
instrument_id
semantic event/effective timestamp
canonical payload hash
normalizer identity/version
quality state
provenance
```

A raw event may legally produce zero canonical facts, e.g. ignored/provisional provider updates.
A normalization failure must not fabricate a canonical fact.

## 7.4 Ingest segment

Finite immutable WAL/store commit unit.

Equivalent fields:

```text
segment_id
capture_session_id
source/market/stream scope
schema_version
first/last event identity
first/last provider sequence where meaningful
record_count
raw count
canonical count
content hash
created/sealed timestamps
```

Segment identity is generated once and survives retry/replay.
Do not generate a new segment identity merely because a database retry occurred.

## 7.5 Coverage manifest

Represents explicit verified coverage for one exact scope.

Equivalent scope dimensions:

```text
source
market product / venue
instrument
data kind / bar type where relevant
time range
schema/data version
selected segments
coverage proof / issues
manifest fingerprint
```

## 7.6 Market Data Revision

Immutable historical set identity.

Equivalent fields:

```text
revision_id
scope
parent/superseded revision when applicable
ordered selected segment identities + hashes
schema/normalizer identities required for interpretation
coverage manifest identity
creation reason
revision fingerprint
```

Prefer content-derived canonical fingerprint for semantic identity.
A random database row ID may exist operationally but must not replace the canonical fingerprint.

## 7.7 Seal record

`SEALED` means the exact revision passed all declared checks.

At minimum:

```text
coverage
schema
identity/dedup
sequence/temporal checks where applicable
segment hash verification
canonical conflict checks
```

A sealed revision never reopens.
A new repair creates a new revision.

---

# 8. Raw evidence capture boundary

Current P9.2 provider code already terminates Binance DTO semantics inside the plugin.
Preserve that boundary.

P9.3 may need the smallest explicit provider-neutral capture/evidence port so the provider can expose raw payload evidence without leaking Binance types.

Acceptable conceptual shape:

```text
Provider transport
    ↓
Raw Evidence Envelope
    ↓
Provider normalizer
    ↓
Canonical Market Fact
    ↓
Market Data Ingress / Recorder Port
```

or an equivalent current-architecture design.

Requirements:

1. Raw payload must be captured before it is irreversibly lost.
2. Core sees opaque payload + provider-neutral provenance, never Binance JSON schema as domain.
3. Canonical fact links to the evidence that produced it.
4. Provider does not import ClickHouse/PostgreSQL persistence modules.
5. Persistence modules do not import Binance codec/domain types.

Do not create a generic event-bus framework unless the current architecture already has an appropriate stable boundary.

---

# 9. WAL / Segment protocol

This is the first durability barrier.

## 9.1 Required path

```text
Provider / Historical Backfill
        ↓
Market Data Ingress
        ↓
Raw + Canonical record bundle
        ↓
LOCAL DURABLE WAL
        ↓
Store Writer
        ↓
ClickHouse
        ↓
Verification
        ↓
PostgreSQL commit
```

Remote database availability must not be required by the provider callback.

## 9.2 WAL record format

Use an explicit versioned binary or exact canonical framed format.

Every record must be independently detectable as complete/corrupt.

Use evidence equivalent to:

```text
magic/version
record length
record ordinal
payload
checksum/hash
```

Do not use Python pickle.

## 9.3 Durability semantics

Define exactly when a record is considered durably accepted.

A record must not be reported as durably recorded before its declared filesystem durability boundary is satisfied.

Batching fsync is allowed only if the acceptance semantics reflect the batch flush boundary.

Do not pretend an in-memory queue is a WAL.

## 9.4 Segment lifecycle

Use finite segments:

```text
OPEN
→ SEALED
→ STORE_WRITTEN
→ VERIFIED
→ COMMITTED
→ GC_ELIGIBLE
```

The exact implementation state vocabulary may differ, but the semantic phases must remain distinguishable.

## 9.5 Torn-write recovery

On restart:

- scan open/uncommitted segments;
- validate framing/checksums;
- keep only complete valid records as accepted evidence;
- quarantine or explicitly reject corrupt/incomplete tails;
- never modify a previously SEALED segment;
- never silently skip corruption.

## 9.6 Capacity

WAL capacity is bounded.

Expose explicit state such as:

```text
HEALTHY
DEGRADED
FULL / FAILED
```

or current-equivalent vocabulary.

Silent unrecorded dropping is forbidden.

---

# 10. ClickHouse durable storage

Implement provider-neutral typed tables for the current first families.

At minimum:

```text
market_raw_event
market_trade
market_bar
market_reference_price / current equivalent semantic name
```

Do not create speculative Depth/Futures tables merely to look complete.
The schema architecture should make adding future typed families straightforward.

## 10.1 Stable envelope fields

Typed tables should share exact cross-cutting identity/provenance fields where appropriate:

```text
canonical_fact_id
source_id
provider/venue/market identity
instrument_id
data kind/schema version
segment_id
capture_session_id
raw_event_id
provider event id/sequence where relevant
ts_event/effective
ts_receive
ts_ingest
provenance
quality state
record hash
```

Do not force fields that are semantically meaningless for a family.

## 10.2 Exact values

Financial Decimal and timestamp fields must round-trip exactly.

No authoritative numeric market field may be silently persisted as Float32/Float64 if that loses canonical precision.

## 10.3 MergeTree dedup is not semantic authority

Do NOT depend on:

```text
ReplacingMergeTree background merge timing
FINAL everywhere
non-deterministic merges
limited deduplication windows
```

as the proof that OnlyAlpha has one market fact.

ClickHouse insert deduplication may be used as an optimization/extra guard, but correctness must remain recoverable from:

```text
deterministic fact identity
segment identity
record hashes
explicit verification
revision manifest
```

## 10.4 Explicit insert behavior

The P9.3 writer must explicitly configure the ClickHouse insert mode it relies on.
Do not rely on changing server defaults.

For the first version, prefer deterministic synchronous segment batch acknowledgement over hidden asynchronous buffering because the provider is already decoupled by WAL.

If the current implementation chooses async insert, it must explicitly wait for the durability condition it claims and prove retry behavior.

## 10.5 Segment verification

After a write, verify the exact segment content before PostgreSQL marks it committed.

Verification must use deterministic evidence, for example:

```text
expected row count
record ordinals / fact identities
record hashes
segment hash
```

Do not treat `INSERT returned 200` alone as proof of exact durable semantic content.

## 10.6 Unknown write outcome

A ClickHouse timeout is an UNKNOWN storage outcome, not evidence that nothing was written.

Recovery must:

```text
query by segment identity
→ verify exact content
→ if exact: continue without duplicate semantic commit
→ if absent: write
→ if partial/conflicting: fail closed / explicit recovery path
```

Do not blindly append another semantically identical “new” segment just because an acknowledgement was lost.

---

# 11. PostgreSQL market-data catalog

Reuse the existing PostgreSQL migration authority and operator discipline.

Do NOT create a second independent PostgreSQL migration framework for P9.3.

Add forward-only immutable migrations to the existing repository migration history.

Application startup must verify schema compatibility but must not auto-migrate/repair production schema.

Minimum conceptual catalog:

```text
market_source
capture_session
ingest_segment
coverage_manifest
market_data_revision
revision_segment relation
seal_record
recovery_event
schema/provenance registry where required
```

Keep PostgreSQL control-oriented.

Do NOT store high-volume Trade/Bar rows in PostgreSQL.

## 11.1 Append-only history

Do not implement semantic truth as mutable fields such as:

```text
revision.is_current = true/false
segment.valid = overwritten repeatedly
```

when an append-only superseding/recovery record can preserve history.

A convenience projection/view may expose “current verified revision”, but it must be derivable from immutable revision/supersession facts.

## 11.2 Transaction boundary

PostgreSQL commit is the authoritative catalog commit only after ClickHouse segment content is verified.

Conceptual commit protocol:

```text
WAL SEALED
→ ClickHouse write/verify raw
→ ClickHouse write/verify canonical typed facts
→ build/verify coverage
→ PostgreSQL transaction commits segment/manifest/revision facts
→ WAL may become GC eligible
```

No WAL deletion before the durable catalog commit that makes replay unnecessary.

---

# 12. Cross-system commit / recovery protocol

This section is mandatory.

Do not attempt a distributed XA/two-phase transaction across filesystem + ClickHouse + PostgreSQL unless the existing architecture already has a proven need and support. It is not required for P9.3.

Use a deterministic recovery protocol.

The system must converge correctly from at least these crash boundaries:

```text
C1  raw/canonical event created, before WAL durable append
C2  WAL record durable, before segment seal
C3  segment sealed, before ClickHouse write
C4  ClickHouse raw evidence written, canonical facts not fully written
C5  ClickHouse fact writes completed, before verification
C6  ClickHouse verified, before PostgreSQL manifest/revision commit
C7  PostgreSQL commit completed, before WAL cleanup/GC
```

Each boundary must have a deterministic recovery outcome.

Required principle:

```text
replay may repeat physical work
but must not create a second semantic fact or second committed revision for identical content
```

Use barriers/fault-injection hooks for tests.
No `sleep()` correctness proof.

---

# 13. Realtime + REST backfill convergence

Realtime and historical repair must converge into the same canonical storage semantics.

## 13.1 Same fact, same identity

Example:

```text
BTCUSDT trade id X from realtime
BTCUSDT trade id X from REST backfill
```

If semantic payload matches:

```text
one canonical fact identity
multiple provenance/evidence observations allowed
```

If the same canonical identity has different semantic content:

```text
SOURCE_CONFLICT / DATA_CONFLICT
```

Do NOT “last write wins”.

## 13.2 Closed 1m Bar

A realtime closed Binance 1m Bar and the historical REST Bar for the exact same external Bar identity must converge identically when their semantic payload matches.

If they disagree:

```text
explicit conflict
→ revision cannot silently seal
```

## 13.3 Provenance preservation

Deduplication must not erase the fact that the same semantic event was observed via realtime and REST.

Physical storage may preserve multiple raw evidence rows while the revision resolves to one canonical semantic fact.

---

# 14. Coverage / Revision / Seal protocol

## 14.1 Coverage is explicit

Build a provider-neutral Historical Query/Coverage Service over durable storage.

It must answer:

```text
what exact revision?
what exact scope?
which segments?
is coverage complete?
which quality/conflict issues exist?
```

Do not answer merely:

```text
SELECT count(*) > 0
```

## 14.2 Revision construction

A revision fingerprint must be deterministic from canonical serialized semantic inputs, including the exact selected segment/fact-set identities required for the revision.

Canonical ordering must be explicit.

Equivalent revision content must generate the same fingerprint.

## 14.3 Seal

A revision becomes SEALED only after all required checks pass.

At minimum for current Bar/Trade vertical:

```text
segment hash verification
schema compatibility
canonical identity uniqueness/conflict check
requested scope verification
Bar temporal/grid coverage
Trade provider-history/identity coverage required by the current request contract
no unresolved corruption
```

## 14.4 Correction / Repair

Never reopen R1.

Correct flow:

```text
R1 SEALED
→ new repair/backfill evidence
→ new segment(s)
→ R2 manifest
→ verify
→ R2 SEALED
```

R1 remains queryable/reproducible by exact revision identity.

---

# 15. Historical Query Service

Create one provider-neutral durable historical read path.

The service must not expose raw ClickHouse SQL to providers or Research.

Conceptual APIs should support:

```text
resolve exact sealed revision
inspect coverage
read exact revision + exact scope
verify revision fingerprint
```

A convenience “latest verified” resolution may exist only if it returns an exact revision identity which the caller then binds.

Research/Backtest must never carry the word `latest` as semantic input.

---

# 16. Dataset Snapshot integration

Preserve existing Dataset authority.

Required chain:

```text
SEALED Market Data Revision
+ exact instruments
+ exact time range
+ exact data-kind/bar-type request
        ↓
Dataset Materializer
        ↓
current canonical Dataset validation/canonicalization
        ↓
Immutable Dataset Snapshot
        ↓
Dataset fingerprint
```

Acceptance invariant:

```text
same sealed revision
+ same exact materialization request
→ byte/semantic-equivalent Snapshot content
→ same Dataset fingerprint
```

After a repair creates R2:

```text
R1 materialization remains reproducible
R2 may produce a different Dataset fingerprint
```

Do not modify existing Snapshot content in place.

---

# 17. Cache relationship

Do not delete the current historical cache just because durable storage now exists.

Freeze:

```text
Durable Market Data Platform
→ authoritative historical storage/revision

Historical Cache
→ optional acceleration/reuse layer
→ disposable/rebuildable
```

If current APIs require adaptation, make dependency direction explicit.

Forbidden:

```text
BinanceDataSource → ClickHouse SQL
Research → raw ClickHouse query
Cache manifest → production MarketDataRevision authority by aliasing names
```

---

# 18. ClickHouse schema lifecycle / HOT-COLD

P9.3 must make the already deployed ClickHouse part of the product path.

## 18.1 Explicit schema authority

Create the minimum repository-controlled, versioned ClickHouse schema/migration discipline required for the market-data tables.

Do not execute hidden CREATE/ALTER migrations at ordinary application startup.

Provide explicit operator tooling for:

```text
status
plan
migrate
validate
```

or integrate with an existing appropriate repository operator surface.

Do not create a second PostgreSQL migration authority.

## 18.2 HOT/COLD

Market-data tables must use the configured ClickHouse storage policy rather than hardcoding host paths in Core.

Physical tier movement:

```text
HOT NVMe
→ COLD HDD
```

must not change:

```text
canonical fact identity
segment hash
revision fingerprint
historical query semantics
Dataset fingerprint
```

Add an integration proof that moving a test partition/part to the cold volume preserves exact logical results.

Do not create separate `hot_market_bar` / `cold_market_bar` semantic tables.

## 18.3 No destructive retention in P9.3

P9.3 establishes long-term retention semantics for the first supported data families.

Do not add automatic DELETE/TTL deletion of authoritative market history unless explicitly required by the current frozen contract.

TTL MOVE for physical tiering is different from TTL DELETE.

---

# 19. PostgreSQL backup / restore and critical data backup policy

ADR 0099 requires database maintenance to be implementation scope.

Reuse and extend current operator tooling.

## 19.1 PostgreSQL

Current repository already has explicit migration, backup and isolated restore-test discipline.

P9.3 must ensure the new market-data catalog is included in:

```text
schema compatibility verification
backup
restore-test
domain validation
```

Do not create a parallel backup script with weaker semantics.

## 19.2 ClickHouse / WAL critical recovery

Implement the minimum explicit policy/tooling/tests proving:

```text
schema is reproducible from repository migrations
uncommitted data is recoverable from WAL
committed segment content is integrity-verifiable
critical first-vertical facts can be backed up/restored or reconstructed according to the documented policy
```

Do not pretend a full multi-terabyte backup can be validated in CI.
Use a bounded representative integration dataset for automated restore/integrity proof.

---

# 20. Operational health / metrics

Operational metrics are projections, not semantic authority.

Expose enough inspectable state to operate P9.3 safely.

At minimum make available, directly or through the existing observability surface:

```text
WAL bytes used / capacity
open segments
sealed-uncommitted segments
oldest uncommitted segment age
writer queue depth
last ClickHouse verified segment
last PostgreSQL committed segment
recording state: healthy/degraded/failed
recovery count / last recovery error
coverage/revision lag
ClickHouse write latency/backlog
PostgreSQL commit latency/errors
```

Do not build a new monitoring platform.

---

# 21. Explicit failure behavior

The following must fail closed or degrade explicitly.

## 21.1 WAL full

Forbidden:

```text
drop events and continue HEALTHY
```

Required:

```text
explicit DEGRADED/FAILED recording state
+ no false durability claim
```

## 21.2 WAL corruption

Do not silently skip corrupt sealed records.
Quarantine/fail verification and preserve evidence.

## 21.3 ClickHouse unavailable

Provider/database failure domains remain separate.

Required:

```text
WAL continues until bounded capacity
writer backs off in bounded/deterministic policy
recording state exposes lag/degradation
on recovery: replay/verify/commit
```

No silent loss.

## 21.4 PostgreSQL unavailable after ClickHouse write

Do not treat uncommitted ClickHouse rows as a sealed revision.

On recovery:

```text
verify exact segment in ClickHouse
→ commit PostgreSQL catalog if exact
→ otherwise explicit recovery failure
```

## 21.5 Conflicting duplicate semantic fact

Same canonical identity + different canonical payload hash:

```text
CONFLICT
→ revision cannot seal
```

Never choose “latest row”.

---

# 22. Required tests

P9.3 is high-risk because it changes persistence, authority and recovery.

Use deterministic, offline-first tests and real local database integration where database semantics are irreplaceable proof.

## 22.1 Domain / identity tests

Must prove:

```text
same semantic fact → same identity
semantic change → different semantic hash/identity as defined by existing contract
same segment content → same segment hash
record order/canonical ordering is deterministic
same manifest → same revision fingerprint
```

## 22.2 Raw/canonical linkage tests

Fixtures must prove:

```text
raw Binance payload preserved exactly
raw hash verifies
canonical fact links to raw evidence
provider DTO does not escape adapter
normalization failure cannot create fake canonical fact
```

## 22.3 WAL tests

At minimum:

```text
append/read round-trip
torn final record
checksum mismatch
open-segment recovery
sealed segment immutability
bounded capacity
restart scan
corrupt sealed segment fail-closed
```

No `sleep()`.

## 22.4 ClickHouse integration tests

Use an actual supported ClickHouse environment when required.

Prove:

```text
DDL/migration compatibility
exact Decimal round-trip
exact timestamp round-trip
batch insert/read
segment verification
unknown/retry path
physical duplicate cannot become duplicate semantic revision
HOT → COLD move keeps logical/fingerprint result unchanged
```

## 22.5 PostgreSQL integration tests

Use actual supported PostgreSQL.

Prove:

```text
forward-only migration
migration history exact-prefix rule remains intact
constraints
append-only revision/seal behavior
concurrent duplicate commit converges or rejects deterministically
backup includes market-data catalog
isolated restore-test verifies restored catalog
```

## 22.6 Cross-system deterministic fault injection

Create explicit barriers for C1–C7 crash points.

For each:

```text
reach barrier
inject crash/failure
restart
recover
verify invariant
```

Required invariants:

```text
no committed revision references unverified segment
no committed segment loses its exact content
no duplicate semantic fact after replay
no WAL GC before catalog commit
no SEALED revision changes after restart
```

## 22.7 Realtime/backfill overlap tests

Use recorded deterministic P9.2 fixtures.

Prove for Trade and closed 1m Bar:

```text
realtime first + REST later
REST first + realtime later
same fact delivered twice
replay after crash
```

all converge to the same canonical revision when payloads match.

Conflicting payloads must fail the seal path.

## 22.8 Dataset determinism

Prove:

```text
R1 + exact request → Dataset D1
repeat → same Dataset fingerprint

repair → R2
R1 still → D1
R2 → D2 if content changed
```

## 22.9 Architecture tests

Add explicit protection against:

```text
Binance imports in durable Core storage/catalog
ClickHouse SQL in Binance provider
PostgreSQL SQL in Binance provider
Research direct mutable ClickHouse reads
DataSource bypassing market-data ingress authority
mutable sealed revision update
```

---

# 23. Real external dependency policy

P9.3 default correctness tests must not require live Binance.

Use deterministic captured P9.2 fixtures for provider input.

Real dependencies are required where their behavior cannot be proven otherwise:

```text
real/local PostgreSQL integration
real/local ClickHouse integration
real filesystem durability/restart tests
```

Do not label an unavailable real database proof as PASS.
Do not require public Binance just to prove P9.3 storage correctness.

---

# 24. Performance requirements

Correctness dominates performance.

But avoid obviously destructive designs.

Required operational shape:

```text
provider callback
→ no synchronous remote DB insert

WAL
→ finite segments

ClickHouse
→ batch insert

PostgreSQL
→ segment/revision metadata, not per-tick row transactions
```

Do not optimize for HFT.
Do not introduce Kafka/Redis/Kubernetes/distributed queues.

The first Golden Vertical has only BTCUSDT/ETHUSDT and should prefer transparent deterministic code over premature scale machinery.

---

# 25. Implementation sequence

Implement in dependency order.

## P9.3.0 — Universal Market Data Storage Contract

Freeze provider-neutral domain identities, ports, state/error vocabulary and authority boundaries.

No database-first design.

## P9.3.1 — Raw Provider Evidence Model

Add opaque provider-neutral raw evidence + exact payload hash/provenance linkage.

Integrate with current Binance Spot adapter with minimal bounded changes.

## P9.3.2 — Canonical Typed Fact Persistence Model

Map current Trade/closed Bar/Market Reference canonical facts to durable typed records without changing their semantic identity.

## P9.3.3 — Append-only WAL / Segment Protocol

Implement finite, checksummed, versioned, crash-recoverable segments and bounded capacity.

## P9.3.4 — ClickHouse Durable Fact Storage

Add versioned schema/operator tooling and typed first-family tables.
Implement exact segment write + verification.

## P9.3.5 — PostgreSQL Catalog / Manifest / Coverage

Add forward-only migrations and stores for capture/segment/revision/coverage/seal/recovery.
Reuse current migration authority.

## P9.3.6 — Revision / Correction / Backfill / Seal Protocol

Implement deterministic manifest construction, conflicts, append-only repairs and immutable seal.

## P9.3.7 — Historical Query & Coverage Service

One provider-neutral exact-revision query path.
No raw SQL leakage to Research/provider.

## P9.3.8 — Immutable Dataset Materialization Integration

Bind exact sealed Market Data Revision to the existing Dataset materializer/snapshot authority.

## P9.3.9 — Crash / Replay / Corruption / Gap Closure

Add deterministic crash barriers, DB outage recovery, overlap/dedup/conflict proofs, HOT/COLD and backup/restore validation.

Do not create separate persistent “DONE” status documents for these substeps.

---

# 26. Explicit non-goals

DO NOT implement in P9.3:

```text
Binance private API
API keys/signatures
Broker
orders
balances
positions
userDataStream
reconciliation of execution facts
LIVE Runtime
LIVE execution permission
Binance Futures provider
QMT
CTP
Depth/L2 unless current P9.3 first-family implementation truly requires it
Kafka
Redis
Kubernetes
new distributed scheduler
generic actor framework
generic event-sourcing framework
full observability platform
full multi-terabyte backup platform
alpha strategy work
```

Do not modify Strategy Revision or Promotion semantics unless a proven current defect blocks P9.3.

---

# 27. Engineering structure guidance

Prefer boundaries similar to current repository style, conceptually:

```text
onlyalpha.data / domain
    market-data identities / typed canonical contracts

onlyalpha.market_data (or nearest existing stable package)
    ingress
    wal
    segment
    revision
    coverage
    historical query

onlyalpha.persistence.clickhouse
    config
    schema/migrations
    typed stores
    segment verifier

onlyalpha.persistence.postgres
    existing migration authority
    new market-data catalog stores

provider/onlyalpha-plugin-binance
    raw capture + normalization only
    no DB dependencies

scripts/
    explicit DB / market-data operator tooling
```

Do not force these exact paths if current repository organization indicates a better existing stable boundary.

Avoid God classes such as:

```text
MarketDataPlatformManager
```

that own provider, WAL, database, revision, Dataset and recovery semantics simultaneously.

Keep responsibilities explicit.

---

# 28. Migration rules

## PostgreSQL

- published migration bytes remain immutable;
- add only new ordered migration(s);
- repository migration history remains exact ordered prefix authority;
- startup verifies compatibility only;
- explicit operator command performs migration;
- update backup/restore validation to include new domain.

## ClickHouse

- repository owns explicit versioned DDL history;
- do not hide schema creation in application startup;
- schema status/plan/migrate/validate must be explicit;
- DDL must be deterministic and tested against the supported deployment version;
- physical storage policy must be validated separately from semantic schema.

---

# 29. Independent review requirements

Because P9.3 is high-risk, perform one bounded independent review after implementation and tests.

Review only:

```text
Modification Scope
+ actual Impact Scope
+ directly related architecture invariants
```

Review must inspect specifically:

1. Is there exactly one semantic identity per market fact?
2. Can realtime + REST create duplicate semantic facts?
3. Can a DB timeout create ambiguous committed state?
4. Can a segment be committed without exact verification?
5. Can a SEALED revision mutate?
6. Can a Dataset consume mutable latest state?
7. Can provider code reach ClickHouse/PostgreSQL directly?
8. Can WAL data be deleted before durable catalog commit?
9. Can partial/corrupt recovery silently continue?
10. Does any test use timing luck/sleep as correctness proof?
11. Does ClickHouse background merge/dedup accidentally become semantic authority?
12. Did the task accidentally start P9.4/Futures/QMT scope?

Blocking rule from current AGENTS.md:

```text
Critical = blocker
High = blocker
Medium/Low = non-blocking unless they directly violate this Task Contract or a frozen invariant
```

---

# 30. Acceptance criteria

P9.3 is accepted when current repository evidence proves all of the following.

## Authority

- raw provider evidence and canonical facts are separate explicit evidence layers;
- ClickHouse owns high-volume physical fact storage, not revision authority;
- PostgreSQL owns manifest/coverage/revision metadata, not market rows;
- Dataset Snapshot remains Research/Backtest semantic input authority;
- cache remains non-authoritative.

## Durability

- provider callbacks do not synchronously require remote DB writes;
- accepted ingress is durably represented in bounded WAL according to explicit durability semantics;
- unfinished WAL segments are recoverable after process crash;
- corrupt segments fail closed.

## Idempotency / uniqueness

- deterministic fact identities survive replay;
- deterministic segment identities survive retry;
- ClickHouse unknown write outcomes are verified before retry/commit;
- duplicate physical delivery cannot produce a duplicate semantic fact in a sealed revision;
- same realtime/REST fact converges;
- conflicting duplicate fact blocks sealing.

## Revision

- revision/manifest fingerprint is stable;
- R1 never mutates after seal;
- repair creates R2;
- R1 remains reproducible;
- no mutable `latest` query is accepted as formal Research input.

## Dataset

- same R1 + same exact request materializes same Dataset fingerprint repeatedly;
- R2 does not alter D1 built from R1.

## Databases

- PostgreSQL forward migration + backup + isolated restore test pass;
- ClickHouse schema migration/validation pass;
- exact Decimal/timestamp round-trip passes;
- HOT/COLD movement preserves logical query/revision/Dataset identity.

## Recovery

- all defined C1–C7 fault boundaries converge deterministically;
- DB outage/drain recovery is explicit and bounded;
- WAL is never GC'd before authoritative commit;
- no recovery path uses `sleep()` as proof.

## Architecture

- Core remains provider-neutral;
- Binance provider has no ClickHouse/PostgreSQL dependency;
- Research has no direct mutable ClickHouse semantic path;
- no P9.4/Futures/QMT scope leakage.

## Validation

- targeted tests PASS;
- affected Ruff check PASS;
- affected Ruff format check PASS;
- affected mypy PASS;
- nearest affected canonical lanes PASS;
- real PostgreSQL integration PASS where required;
- real ClickHouse integration PASS where required;
- bounded Independent Review completed;
- Critical = 0;
- High = 0.

---

# 31. Stop condition

Stop when:

```text
Required Behavior implemented
+
Acceptance Tests PASS
+
Impact-Aware validation PASS
+
required PostgreSQL/ClickHouse real integration proof PASS
+
bounded Independent Review complete
+
Critical = 0
+
High = 0
=
STOP
```

Do NOT continue with speculative optimization, P9.4 work, broad repository audit, or extra closure loops after this condition is met.

Do NOT create a permanent task completion report merely to say P9.3 is done.

At completion, report in the Codex response only:

```text
1. What changed
2. Exact authority model implemented
3. Key files changed
4. Migrations added
5. Tests/commands executed and results
6. Fault/recovery cases proven
7. Independent-review Critical/High findings
8. Any real external proof that could not run, clearly marked NOT RUN / NOT PROVEN
9. Why Stop Condition is or is not satisfied
```

Do not claim PASS for unavailable evidence.

---

# 32. Final architectural invariant

After P9.3, this must be mechanically true:

```text
                    Binance Spot
                         │
                  provider evidence
                         │
                         ▼
                 Raw Evidence Layer
                         │
                    normalization
                         │
                         ▼
                Canonical Market Fact
                         │
                   durable ingress
                         │
                         ▼
                 Append-only WAL
                         │
                    batch/verify
                         │
                         ▼
                    ClickHouse
                   typed fact rows
                         │
                      verify
                         │
                         ▼
                    PostgreSQL
            Manifest / Coverage / Revision
                         │
                      SEALED
                         │
                         ▼
               Exact Historical Query
                         │
                         ▼
               Dataset Materializer
                         │
                         ▼
             Immutable Dataset Snapshot
                         │
                ┌────────┴────────┐
                ▼                 ▼
             Research          Backtest
```

And none of the following may be true:

```text
mutable ClickHouse latest rows = Research truth
Historical Cache = production authority
provider callback = ClickHouse INSERT
Binance plugin = database owner
SEALED revision = mutable
repair = UPDATE old history
reconnect/retry = new semantic identity
physical duplicate = second semantic fact
DB acknowledgement = unverified semantic commit
```

Build the smallest clear implementation that makes these invariants true.
