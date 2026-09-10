# FP-DATA-003 — Corporate-action adjustment and historical revision drift

## Failure family

Adjusted historical prices change because corporate-action interpretation, vendor history, suspension handling, or adjustment logic changes without an explicit data revision.

## External / internal evidence

- RQAlpha issue #805: post-adjusted price changed during a suspension interval and diverged from another vendor.
  - https://github.com/ricequant/rqalpha/issues/805
- RQAlpha issue #359: reported inaccurate pre/post-adjusted historical values.
  - https://github.com/ricequant/rqalpha/issues/359
- RQAlpha issue #451: reported adjustment not taking effect consistently in strategy/history paths.
  - https://github.com/ricequant/rqalpha/issues/451
- Evidence status: observed upstream data/adjustment defects.

## Observed symptom

A historical period that should be reproducible produces changed adjusted prices, discontinuities during suspension, or inconsistent values across APIs/runs after provider or adjustment changes.

## Generalized root cause

Vendor raw facts, corporate-action evidence, adjustment convention and derived adjusted series were collapsed into one mutable historical representation.

## Risk to OnlyAlpha

Research/Backtest results can silently change, historical Evidence can become unreproducible, and a Dataset Snapshot can no longer explain which corporate-action/vintage assumptions produced its values.

## OnlyAlpha invariant

Historical correction or changed corporate-action interpretation MUST create an explicit new immutable data/canonical revision. Existing Dataset Snapshots and historical Evidence remain reproducible against their original exact inputs.

## Required protection

- preserve raw provider evidence separately from adjusted/normalized canonical revisions;
- bind adjusted output to exact corporate-action/reference inputs and adjustment semantics;
- never silently rewrite a sealed historical revision;
- materialize Research/Backtest input through immutable Dataset Snapshot identity;
- distinguish provider-current history from point-in-time or historically reconstructed truth.

## Required tests

- change corporate-action evidence/adjustment implementation → new revision/fingerprint, old revision unchanged;
- suspension interval adjustment produces no unexplained synthetic movement under the chosen canonical contract;
- two Dataset Snapshots bound to different historical revisions remain independently reproducible;
- provider history changes after a snapshot is sealed → prior Research result remains loadable and unchanged.

## Non-solutions / rejected shortcuts

Overwriting old adjusted bars, using today's provider-adjusted history as an implicit truth for every old backtest, or comparing only final prices does not preserve historical semantics.

## Scope notes

Especially relevant to A-share equities, funds and other instruments with splits/dividends/rights events, but the revision principle also applies to any vendor that can restate historical market/reference data.