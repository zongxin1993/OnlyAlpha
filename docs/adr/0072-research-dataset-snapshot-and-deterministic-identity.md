# ADR 0072: Research Dataset Snapshot and Deterministic Identity

Status: Accepted

Date: 2026-08-13

## Context

Research calculations must identify the exact normalized historical facts they consume. A DataFrame, provider request, cache
directory or Parquet path cannot provide immutable, reproducible semantic identity. Historical request/result/quality contracts
also lived under the cache namespace, and MiniQMT's cache provider retained an entire Trading DataSource create request.

## Decision

OnlyAlpha supports one P7.1 Dataset type: finite `HISTORICAL_BAR` v1 containing strictly validated closed `OnlyBar` facts. A
resolved Definition freezes exact instruments, Bar semantics, UTC half-open range, adjustment semantics and strict quality policy.
Definition identity uses `onlyalpha.canonical`.

Dataset identity separates three authorities. Definition fingerprint answers what data was requested. Canonical content fingerprint
streams length-delimited canonical normalized rows in stable instrument/interval/event/revision order. Snapshot fingerprint combines
Definition fingerprint, exact Dataset Schema fingerprint, canonical content fingerprint and row count. Provider identity, plugin
version, source metadata, cache fingerprint, storage path, partition layout and creation time are excluded and persisted as
provenance or storage evidence. Parquet byte SHA256 verifies storage integrity and never defines semantic content identity.

The exact columnar schema uses decimal128 rather than float and retains every price, quantity and currency precision plus currency
type. `OnlyBar -> Arrow -> Parquet -> Arrow -> OnlyBar` must be exact. Dataset validation performs no fill, resample, timezone guess,
duplicate selection or adjustment repair.

The immutable Dataset Store uses a content-addressed `research/datasets/sha256/<prefix>/<snapshot>/` layout, writes sibling staging
directories, verifies files and semantic hashes, then performs an atomic final rename. Existing valid targets are verified and
reused; corrupt targets fail closed and are never overwritten. The public Store has no append, update, overwrite, invalidate or
delete API.

Historical acquisition semantics now belong to `onlyalpha.data.historical`; cache retains cache key, manifest, policy and storage
authority. A narrow provider create request contains only source, immutable instrument/calendar context, data version, batching and
configuration location. It contains no Runtime, Clock, EventBus, Engine, Cluster, Broker or Market Product authority. Tushare and
MiniQMT reuse their normalization implementations through this SPI while Trading resources continue to wrap normalized Bars as
runtime inbound updates.

Research Dataset code may not import Trading authorities. P7.1 does not enable Research Runtime, Research Job, Calculation backend,
Calculation Store, Research Result or Artifact product workflows.

## Failure Semantics

Invalid provider ordering fails in historical validation. Unknown/open/out-of-contract/conflicting Dataset rows fail before commit.
Malformed persisted fields, unsupported schema versions, non-UTC times, invalid SHA256 and corrupt/missing partitions fail closed.
Failure before final rename leaves no visible Snapshot; rerun produces the same identity.

## Consequences

Historical Cache remains an acquisition optimization rather than Research Dataset authority. Equivalent normalized content from
different providers, roots, compression settings or partition layouts has one semantic Snapshot identity. Provenance remains
auditable without contaminating reproducibility. Future Dataset types require a new proven contract rather than a generic DataFrame
abstraction.

## Rejected Alternatives

Rejected alternatives include cache fingerprint as Dataset identity, Parquet bytes as content identity, provider identity in the
semantic hash, mutable refresh/append Snapshots, implicit repair, float durable values, fake Trading objects and a partially enabled
Research Runtime.
