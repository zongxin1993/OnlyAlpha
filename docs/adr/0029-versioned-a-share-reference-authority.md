# ADR 0029: Versioned A-Share Reference Data Authority

- Status: Accepted
- Date: 2026-08-05
- Modules: reference, config, runtime planning, market rules, checkpoint, artifact, provider adapters

## Context

`CN_A_SHARE_CASH` previously received `board` and `st_status` from an unversioned configuration Mapping. Backtest
defaulted missing ST state to false, Paper built a different projection, and neither suspension nor the official raw
previous close had one historical authority. Symbol prefixes and the latest provider state cannot prove historical
board or ST status; the preceding Bar close cannot prove the official price-limit base after gaps, suspensions, or
corporate actions.

## Decision

`OnlyAshareInstrumentReference` is the immutable canonical record. Its effective range is left-closed and
right-open. All exact numeric inputs are quoted decimals. Exchange, security type, board, ST, suspension, previous
close, source, source version, and data version are mandatory. Its SHA-256 fingerprint covers the canonical payload.

`OnlyAshareReferenceRegistry` rejects overlapping ranges, conflicting source identities, and fingerprint conflicts.
`OnlyAshareReferenceQuery`/`resolve` is the sole `(Instrument, TradingDay)` resolution authority. Missing or invalid
data fails before A-share Runtime assembly. The resolved record is projected into the existing Market Rule contract;
the compiler and Runtime do not parse provider objects or configuration dictionaries.

The order-independent Registry fingerprint participates in the Runtime compatibility key and Engine runtime
manifest. Checkpointed Market Rule state records the same fingerprint and rejects restore against a different
Registry. Each Runtime artifact contains the Registry fingerprint and canonical reference snapshot table; compiled
rule diagnostics retain the record fingerprint actually used.

Provider adapters may only create a record from an explicitly joined historical payload. MiniQMT instrument detail
alone is insufficient and fails closed. Tushare network acquisition remains outside offline tests.

## Consequences

Generic profiles continue to use the generic Instrument projection and do not require A-share records. This decision
does not enable A-share durable execution, T+1 accounting, fees, price-limit rejection, or matching capability.
