# ADR 0063: CN A-Share Production Fee Authority

Status: Accepted

## Context

ADR 0060 separated Market Fee Packs from Broker Fee Contracts, but default `CN_A_SHARE_CASH` composition still installed an
architecture-only test pack. Real account commission snapshots could only arrive through a software plugin.

## Decision

OnlyAlpha installs `CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30` in default composition. Verified scope is ordinary CNY
A-share common-stock cash trading on SSE (`XSHG`) and SZSE (`XSHE`). Coverage begins on 2025-06-30; earlier days have no
verified coverage and fail with `FEE_SCHEDULE_NOT_FOUND`. Separate venue-scoped stamp-duty and transfer-fee families feed the
existing market-neutral Fee Engine. Stamp duty is SELL-only.

Official source identity is a stable canonical string; locator and document metadata live in a small source manifest. Sources
are the Stamp Tax Law, MOF/STA Announcement 2023 No. 39, CSDC SSE/SZSE fee tables updated 2025-06-30, and CSDC settlement
interface specifications that define two-decimal fee amount representation and monetary rounding. Pack and Schedule versions
are independent. Stamp duty preserves its 2022 and 2023 versions; complete Pack coverage begins when the verified transfer-fee
tables begin. Historical payloads are immutable and no current/latest selector exists.

Regulatory and exchange handling fees are not added as separate investor debits because the official client commission concept
includes them. They constrain the Broker commission contract and must not double-charge the Account.

Real Broker commission is provisioned as a strict immutable document under `authorities.broker_fee_contracts`. Accounts only
select `(contract_id, contract_version)`. Engine composition installs the snapshot before Runtime assembly; factories do not
read documents or manufacture Authority. Source is `BROKER_CONTRACT:<contract-id>:<version>`. Wrong broker/account/currency,
invalid source, duplicate identity and fingerprint conflict fail closed. Minimum commission uses `ORDER_CUMULATIVE`.

Independent JSON vectors contain manually reviewed per-component expected amounts and never generate expectations with the
production engine. The test pack is available only from `onlyalpha.fee.testing`, absent from defaults and public pack exports.

## Product boundary

This does not enable `CN_A_SHARE_CASH` durable execution. BSE, B shares, ETF-specific regimes, bonds, convertible bonds,
options, margin, lending, Stock Connect, block trades, cross-border fees and multi-currency remain unsupported.

## Consequences

A fee change adds Source Record, Schedule version, Pack version when the set changes, and vectors. It does not change Fee
Engine, Order, Position, Account, Runtime Transaction, Recovery or Reconciliation algorithms.
