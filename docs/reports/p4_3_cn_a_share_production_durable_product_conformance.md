# P4.3 CN A-Share Production Durable Product Conformance

## Certification record

| Field | Value |
|---|---|
| Certification verdict | **CERTIFIED** |
| Product | `CN_A_SHARE_DURABLE_BACKTEST_V1` |
| Product contract version | `1` |
| Prompt baseline | `f8ef7859a077ea72ca1a972ee60f1161add24b58` |
| Actual implementation baseline | `f8ef7859a077ea72ca1a972ee60f1161add24b58` |
| Certification commit | `a710f89e389c903e80d30701d349b6bc94507b1d` |
| Layered Quality | Run 27, `31353356992` |
| Workflow head SHA | `a710f89e389c903e80d30701d349b6bc94507b1d` |
| `quality-gate` | `success` |

The prompt baseline and the fetched `origin/master` baseline were identical, so there was no baseline difference to reconcile.
Run 27 completed successfully in 13 minutes 13 seconds with four lane-metrics artifacts. The containing documentation commit
must also pass its own same-SHA Layered Quality run; a documentation-only commit does not inherit Run 27's status.

This report records certification of one finite Backtest product contract. It does not promote the whole
`CN_A_SHARE_CASH` Profile family, which remains `EXPERIMENTAL`, and it does not certify Paper or Live trading.

## Certified supported surface

The certified surface is exactly:

- Runtime: `BACKTEST` through `OnlyEngine` and the production composition root.
- Market: `CN_A_SHARE_CASH@2025.1` for the frozen ordinary XSHG/XSHE fixture dates only.
- Instruments: `600000.XSHG` and `000001.XSHE`, both CNY `COMMON_STOCK` records in the frozen fixture.
- Account and execution shape: `CASH`, `LIMIT`, `LONG`, `NETTING`, `BUY OPEN`, and `SELL CLOSE`.
- Broker lifecycle: Accepted, Trade, Cancelled, Rejected, and Expired.
- Fill lifecycle: Whole, Partial, and Multi-Fill, including cumulative minimum commission.
- Settlement: ordinary trading-day-based T+1 asset sellability.
- Persistence: Memory economic equivalence and SQLite durability.
- Recovery: checkpoint, restart with fresh Engine/Runtime instances, and forward recovery including A to B to C restart.
- Output: deterministic Result, Artifact, transaction history, and authority fingerprints.

## Explicitly unsupported surface

Certification does not cover `CN_A_SHARE_CASH@2026.07`, every A-share instrument or historical regime, ST/new-listing/delisting
special cases, BSE, B shares, ETF, bonds, convertible bonds, Margin, Short, Hedging, Futures, Crypto, multi-account,
multi-broker, Paper production recovery, real Broker submission/synchronization, Live Runtime, distributed/vectorized Backtest,
or a Stable promotion of the Profile family. Synthetic Bars are not claimed to be exchange history.

## Frozen production inputs and authorities

### Dataset and Reference authority

The Product Gate uses `CN_A_SHARE_PRODUCTION_V1_SYNTHETIC_BARS` with data version
`cn-a-share-production-v1-synthetic-bars-v1`. It is frozen local-only synthetic market data: 32 one-minute Bars over
`2026-01-05` and `2026-01-06`, with network access and implicit fallback forbidden. Dataset content fingerprint is
`6647ba0cc6c6dc9867985978edd13a882c13e8c738c3d22ec46f4bc19d58f7c2`.

The four day-effective `OnlyAshareInstrumentReference` records are resolved by Instrument plus Trading Day. They bind SSE/SZSE,
main board, lot size `100`, tick `0.01`, non-ST, non-suspended, and official raw previous close `10.00`. The Reference data and
source version is `cn-a-share-production-v1-reference-v1`; Registry fingerprint is
`0d0bc84dd712778e6fc4719a22c16918c72729d9d3375ccd51df23de313ffec2`. Bar close is not Reference authority.

### Market, fee, Broker, and execution authorities

- Market Profile: `CN_A_SHARE_CASH@2025.1`, fingerprint
  `eb5746708759c1ad521b6d1667599b98f6073db6898b26e32020171bb8a7d732`.
- Market Fee Pack: `CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`, fingerprint
  `728260d19fd350ba1c25444f85ccf096ad43e490996999883167d16c7a7e5989`.
- Broker Fee Contract: `VIRTUAL:BACKTEST-ACCOUNT:COMMISSION@2025.01`, fingerprint
  `bb5c3f193cca6e3f9d347a2a601abd588a53c3559bf4fdae95b3041c0f91e7c6`, bound to Broker `virtual`, Account
  `backtest-account`, CNY rate `0.0003`, `ORDER_CUMULATIVE`, and minimum commission `5.00`.
- Execution Support Policy: version `2`, with durable Accepted, Trade, and Terminal capabilities. Market identity is evidence,
  not execution permission.

The authorities above are independently versioned and fingerprinted. No test fee pack, zero-fee fallback, Bar-derived Reference,
or market-identity execution shortcut participates in certification.

## Product conformance evidence

The `ashare` lane passed all 24 collected conformance tests. The evidence is owned by the following formal product tests:

- BUY OPEN, Whole Fill, XSHG/XSHE round trip, same-day SELL rejection, T+1 maturity, and SELL CLOSE:
  `test_production_round_trip_uses_canonical_authorities_and_t_plus_one`.
- Partial/Multi-Fill incremental economics, production fee components, and one cumulative minimum commission per Order:
  `test_multi_fill_applies_incremental_fees_and_minimum_commission_once_per_order`.
- Broker Reject and Expire as durable Terminal facts:
  `test_broker_reject_and_expire_are_durable_terminal_facts`.
- SELL Reject before Accepted with settled Position preserved and exact Reservation release:
  `test_sell_reject_before_accepted_preserves_settled_position_and_releases_reservation`.
- BUY/SELL Partial Fill plus Cancel preserving committed Fill economics and releasing only the remaining Reservation:
  `test_partial_fill_cancel_preserves_fill_and_releases_only_remaining_reservation`.
- Memory/SQLite economic equivalence: `test_memory_and_sqlite_execute_the_same_production_economics`.
- Result and Artifact determinism for Memory and SQLite:
  `test_same_product_input_has_deterministic_result_and_artifact`.
- SQLite A to B to C forward recovery versus uninterrupted canonical history:
  `test_sqlite_a_b_c_forward_recovery_equals_uninterrupted_product_history`.

The persistence tests compare `result_fingerprint`, `determinism_fingerprint`, Artifact content fingerprint, canonical transaction
identities/payloads, and Runtime snapshots. P4.3-close changed none of the fixture, expected economic values, Product Contract,
Profile, fees, Broker contract, Execution Policy, transaction schema, settlement, or execution kernel.

## Architecture boundary evidence

The architecture guards remained in `fast`, `core-full`, and the final remote gate. They prove:

- the Execution kernel has no A-share Reference/rule import or routing literal;
- the production conformance harness cannot bind test fee authority;
- the Product Harness cannot reach durable execution or Manager internals;
- no Product Framework or A-share compatibility layer was introduced.

No test was skipped, xfailed, weakened, removed from `core-full`, serialized globally, retried, or stabilized with sleep.

## Initial certification blocker and root cause

The initial P4.3 implementation commit `f8ef7859a077ea72ca1a972ee60f1161add24b58` was **NOT CERTIFIED** because its
same-commit Layered Quality Run 26 (`31351149179`) failed `core-full`; the dependent `quality-gate` therefore also failed.
Static, build, ashare, MiniQMT contract, and recovery jobs passed. The observed failing assertion was
`test_actual_worker_contract_normalizes_a_fake_xtquant_shape`: expected `SUCCESS`, received `TIMEOUT`, with runner duration about
5.08 seconds and an inherited five-second request deadline.

The root cause was a test responsibility error. `_request(timeout=5)` silently coupled the semantic result of normal SUCCESS,
query-failure, and protocol contract tests to runner scheduling and subprocess startup time. Production correctly treats
`OnlyHistoricalWarmupRequest.timeout` as a real worker execution deadline, so returning `TIMEOUT` after five seconds was valid
production behavior, not an A-share economic regression or a production timeout bug.

The correct authority boundary is:

```text
MiniQMT worker client -> subprocess deadline, termination, and protocol behavior
MiniQMT contract test -> explicit scenario deadline and expected semantic
CI                   -> scheduling and resources only
```

## Certification fix

Commit `a710f89e389c903e80d30701d349b6bc94507b1d` removed the helper's hidden timeout default. Every request now explicitly uses
one of two module-local responsibilities:

- `_FUNCTIONAL_WORKER_DEADLINE_SECONDS = 15` is a bounded hang guard for functional/query/protocol/abort contracts, not a
  performance SLA;
- `_TIMEOUT_SCENARIO_DEADLINE_SECONDS = 1` is reserved for the intentional timeout scenario.

Fifteen seconds reuses the module's pre-existing native-abort guard and gives scheduling margin over the observed 5.08-second
runner case. The strict timeout test still asserts `TIMEOUT`, diagnostics, and terminated worker PID. No production code,
production default, CI lane, xdist worker count, retry, lock, or product semantic changed.

## Regression and local quality evidence

All commands below passed on the certification change:

| Gate | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS, 72 packages audited |
| Historical worker module repeated 5 times | PASS, 15 tests per run |
| `fast` | PASS, 1060 passed, 1 skipped |
| `integration` | PASS, 130 passed |
| `exhaustive` | PASS, 112 passed |
| `core-full` repeat 1 | PASS, 1190 passed, 1 skipped |
| `core-full` repeat 2 | PASS, 1190 passed, 1 skipped |
| `miniqmt-contract` | PASS, 32 passed |
| `release` static checks | PASS, Ruff, format, Core/Tushare/MiniQMT mypy, version sync |
| `release` core-full | PASS, 1190 passed, 1 skipped |
| `release` recovery | PASS, 306 passed |
| `release` ashare | PASS, 24 passed |
| `release` miniqmt-contract | PASS, 32 passed |
| `uv build --all-packages` | PASS, four sdists and four wheels |
| `git diff --check` and commit hooks | PASS |

The first sandboxed build attempt could not fetch `hatchling` because network access was denied. The exact build command passed
unchanged in the approved network environment; this was not a code or gate failure. Performance-budget warnings remained
non-blocking diagnostics and were not pulled into P4.3 scope.

## Final remote Layered Quality evidence

Run 27 (`31353356992`) was triggered by push on `master` for exact head SHA
`a710f89e389c903e80d30701d349b6bc94507b1d`. Its final status was Success and `quality-gate` completed successfully after
static, build, core-full, recovery, ashare, and miniqmt-contract. Four metrics artifacts were produced. This is a root-cause
commit run, not a rerun of the failed SHA.

## Certification verdict

```text
Certification Verdict: CERTIFIED
Product: CN_A_SHARE_DURABLE_BACKTEST_V1
Product Contract Version: 1
Certification Commit: a710f89e389c903e80d30701d349b6bc94507b1d
Layered Quality: 31353356992
quality-gate: success
```

Certification means only that the frozen finite surface above has one production-path proof across market/reference/fee
authorities, durable lifecycle, persistence, forward recovery, deterministic output, architecture guards, local release gates,
and a same-SHA remote quality gate. P5 Market Product Composition Authority Neutralization is next; it is not implemented here.
