# ADR 0085: Research Read Model and Read-only Query/API Boundary

- Status: Accepted
- Date: 2026-08-16

## Context

P7.9 established a portable, immutable Research Artifact that independently verifies exact Statistics, Research Result, and
Artifact identities. CLI, Notebook, and future Web consumers still lacked one stable contract and would otherwise need to understand
Parquet layout or execution-store topology.

## Decision

`onlyalpha.research.query` is the transport-neutral public consumer boundary. Its only upstream Port is
`OnlyResearchArtifactReader.load_verified(exact_research_result_fingerprint)`. Query results are immutable ephemeral projections,
not durable authorities: they have schema version 1 but no Query/Plan/Result fingerprint, Store, cache, mutable index, latest pointer,
or recovery state.

V1 supports exact Artifact summary, a canonical exact Statistics catalog, and one Statistics series. Series filtering uses UTC
nanosecond `[from,to)`, cursor semantics use `ts_event_ns > after_ts_event_ns`, and pagination reads `limit + 1`; only a non-terminal
page returns its last timestamp as the next cursor. Query may select, sort, filter, paginate, and project existing Artifact facts. It
may not recompute Statistics or analytics, scan upstream Stores, inspect physical Artifact files, or infer composition.

The HTTP adapter is a separate `onlyalpha-http-server` workspace package. It owns FastAPI/Pydantic/Uvicorn dependencies and exposes exactly
three GET product endpoints under `/api/v1`; Core has no reverse dependency. Decimal values are JSON strings, event timestamps retain
exact nanosecond integers, and audit `created_at` is UTC ISO-8601. Exact lower-case SHA256 addressing is mandatory. Missing Artifact,
corrupt Artifact, unknown Statistics, and invalid query remain distinct stable errors; corruption is never empty, missing, repaired,
or rebuilt.

Research and Live Runtime factories remain unsupported. Web UI remains future work.

## Rejected Alternatives

- Direct API access to Dataset, Calculation, Statistics Result, or Research Result Stores would expose the execution plane.
- Reading Parquet in routes would couple transport to physical persistence.
- Offset pagination would not provide the frozen timestamp-cursor contract.
- Decimal JSON numbers would lose exact semantics through float consumers.
- Artifact catalog/search/latest would invent an authority that does not exist.
- Query caching or persisted Query Results would add unnecessary state and recovery ownership.
- Calculating mean IC, ranking, optimization, or new rolling values would create a second analytics plane.

## Consequences

CLI, Notebook, and future Web clients can share one versioned read contract while execution persistence remains hidden. Each request
may repeat full Artifact verification; correctness takes priority until profiling justifies a separately designed disposable cache.
P7.10 adds no Web UI, authentication, Trading API, Runtime control, Research Runtime lifecycle, or new Statistics semantics.
