# FP-DATA-002 — Authoritative historical data mutated by a derived transform

## Failure family

A derived transformation mutates cached/source historical data in place, so repeated identical queries no longer return identical results.

## External / internal evidence

- RQAlpha issue #632: `history_bars` cached source data was adjusted in place; repeated identical calls could apply adjustment repeatedly and return different values.
  - https://github.com/ricequant/rqalpha/issues/632
- Evidence status: upstream issue contains a concrete reproduction and described root cause.

## Observed symptom

Calling the same historical-data API twice with the same arguments returns different values, or one consumer's adjustment/normalization changes data subsequently observed by another consumer.

## Generalized root cause

Authoritative/source data and derived views shared mutable storage. A transformation that should have produced a new value modified the cached/source representation instead.

## Risk to OnlyAlpha

Dataset reproducibility, canonical Market Data truth, Research determinism and cross-run comparability can be violated without any explicit data revision.

## OnlyAlpha invariant

For the same immutable source/revision and the same canonical query/transform inputs, repeated evaluation MUST return the same result.

Derived adjustment, normalization, preprocessing or feature computation MUST NOT mutate authoritative source facts or immutable cache content in place.

## Required protection

- immutable canonical facts / Dataset Snapshots;
- copy-on-transform or immutable execution structures where mutation would alias source truth;
- explicit derived identity/fingerprint for transformations that change semantic values;
- no writable alias from Calculation/Research code into authoritative market-data storage.

## Required tests

- perform the same historical query/adjustment twice → byte/semantic-equivalent result;
- execute a derived transform and then reload the authoritative source → source fingerprint unchanged;
- two consumers transform the same source independently → order of execution cannot change either result;
- cache reuse and cache-miss rebuild produce the same canonical output.

## Non-solutions / rejected shortcuts

Clearing caches between calls, applying the inverse transformation later, or documenting that callers must copy manually does not protect authoritative truth.

## Scope notes

Applies to corporate-action adjustment, normalization, winsorization, neutralization, factor preprocessing, Dataset materialization and any derived transformation over shared historical facts.