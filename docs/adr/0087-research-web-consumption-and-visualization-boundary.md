# ADR 0087: Research Web Consumption and Visualization Boundary

- Status: Accepted
- Date: 2026-08-17
- Supersedes: ADR 0085 HTTP v1 nanosecond representation only

## Context

P7.9 established the portable immutable Research Artifact, P7.10 established the transport-neutral Query service and read-only
HTTP adapter, and P7.11 established finite Research Runtime composition. The HTTP v1 representation encoded nanosecond timestamps
as JSON integers. Although exact in Python, ordinary Research timestamps exceed JavaScript's safe integer range, so a browser could
silently lose authority precision before rendering.

## Decision

The deployable private application is `packages/onlyalpha-web-console`. Its Research feature consumes only same-origin `/api/v2` GET routes and
has no filesystem, Parquet, Store, Engine, Runtime, Trading, or mutation dependency. The Query Core contract remains schema version
1 with Python `int` timestamps and `Decimal` values. HTTP has the independent `RESEARCH_API_SCHEMA_VERSION = 2`: response timestamps
and cursors, plus request time filters and cursors, are canonical decimal strings. Decimal remains canonical fixed decimal text.
There is no v1 compatibility wrapper because no formal external v1 consumer existed before the first browser boundary.

FastAPI-generated deterministic OpenAPI is checked in under `contracts/research-api/v2`; generated TypeScript expresses compile-time
transport shape, while strict Zod schemas are the runtime admission firewall. Admitted timestamps map directly to `bigint`, never
through JavaScript `number`. Exact Decimal values remain strings. HTTP primitives do not become Web domain values.

URL routes own exact Research Result and Statistics selection. TanStack Query owns only disposable immutable server cache, with no
polling, automatic retries, localStorage, IndexedDB, or offline authority. There is no Redux/Zustand/global selection store and no
Artifact catalog, latest pointer, search, Runtime control, or new Statistics/Analytics.

Visualization is a one-way presentation projection. A pure adapter maps nanoseconds to chart seconds and Decimal text to finite
numbers; null becomes whitespace. Distinct nanosecond timestamps that collide at chart resolution, unsafe times, non-finite values,
or invalid order return structured `CHART_PROJECTION_ERROR`. They are never merged, averaged, dropped, or substituted. The exact
table remains visible and retains raw nanoseconds and Decimal text. Only `charts/lightweight` depends on Lightweight Charts, whose
React adapter owns mount/remove/resize lifecycle and displays TradingView attribution.

Deployment uses same-origin `/api/v2`: Vite proxies `/api` to loopback FastAPI for development, while production reverse-proxy
configuration remains out of scope. Web quality is an explicit static/unit/build/E2E evidence set. Web-only impact stops at the API
boundary; transport changes propagate through Query/Artifact regression and Web contract checks. P7 Final-SHA certification makes
Web evidence mandatory.

## Consequences

The browser is a typed, deterministic, read-only consumer independent of Research execution topology. Removing Web leaves every
Research authority unchanged. Chart coordinates are deliberately lossy and disposable; they can never be sent upstream or become
Research truth. Corrupt, missing, invalid, transport, contract, and chart failures remain visibly distinct and fail closed.

This decision adds no authentication/control platform, producer Store access, mutable Web persistence, deployment orchestration,
new Research semantic identity, Runtime lifecycle capability, or LIVE support.
