# ADR 0111: Private Quant Asset Source and Distribution Loading

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0069, 0098, 0108, 0110

## Context

L3 Factor and L4 Strategy authoring libraries have the highest expected change rate and will normally live in private repositories.
Development and Agent research need a short edit/test cycle from a checkout, while controlled environments need reproducible installation
from a wheel or private package index. Repository-relative paths in OnlyAlpha consumers would couple those assets back to this monorepo.

## Decision

Private quantitative asset libraries support two packaging modes without creating two semantic authorities:

1. A source checkout may be used through an explicit Python source path or an editable local installation during development, testing and
   controlled Agent research.
2. A built distribution may be installed through `uv` or `pip`. Installed L3 packages expose the standard
   `onlyalpha.calculations` entry point; installed L4 packages expose read-only Python resource APIs for authoring documents.

The L3 Python import surface returns the same exact Calculation registrations as its installed entry point. Direct source-path registration
is a development/admission mechanism, not a normal production control path. Production nodes discover admitted L3 implementations only from
installed distribution metadata.

The L4 asset API accepts either an explicit library root or package resources. Both return the same canonical authoring JSON. A path is only
an input location before Product Definition Resolve; it is never Strategy identity or Runtime authority. Verified Research Candidate Freeze
still creates the immutable StrategyRevision used by Backtest, SIM and LIVE.

No Core module scans directories, mutates `sys.path`, selects a latest version, or imports arbitrary files automatically. Missing packages,
entry points, named assets or files fail explicitly. Distribution/version and implementation evidence continue to be bound by existing
Calculation, Freeze and admission authorities.

ADR 0112 adds the shared `onlyalpha.quant_assets` management entry point and immutable catalog generations. It does not replace the
Calculation SPI or permit in-place module reload.

## Consequences

L3/L4 private repositories can change frequently and be consumed from local checkouts without editing OnlyAlpha source. The same repository
can later be built and installed from a private index without changing semantic type IDs or Strategy authoring content. OnlyAlpha consumers
no longer depend on the main repository's `examples/` filesystem topology.

## Rejected alternatives

- Making a mutable filesystem path a Strategy or Calculation identity.
- Runtime-wide `PYTHONPATH` mutation or recursive arbitrary-code discovery.
- A second plugin SPI for private Alpha.
- Loading L4 JSON directly into Trading Runtime without verified Freeze.
