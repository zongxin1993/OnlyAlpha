# P3 CN A-Share Production Fee Product

## Baseline and scope

Prompt baseline, actual commit SHA and evaluated working-tree HEAD are
`0c0543765eeb124d3e87fdad5b3bfad2b38f69a1`. No later commit pre-completed an item; this report evaluates the uncommitted P3
implementation on that baseline. The user-supplied Prompt remains an untracked input and was not modified.

Supported: ordinary CNY A-share common-stock cash trading, XSHG/XSHE, Cash Account, Long-only/Netting fee semantics. Coverage
begins **2025-06-30**; earlier days fail closed.

Unsupported: BSE, B shares, ETF-specific fees, convertible bonds, bonds, options, margin, lending, Stock Connect, block-trade
regimes, cross-border fees and multi-currency.

## Official sources and fee matrix

| Component | Source ID | Issuer/document | Published | Effective evidence | Venue | Side | Basis | Rate | Scope/resolution |
|---|---|---|---|---|---|---|---|---|---|
| Stamp duty v1 | `PRC-NPC:STAMP-TAX-LAW:2021` | NPC Stamp Tax Law | 2021-06-10 | 2022-07-01 through 2023-08-27 | XSHG/XSHE | SELL | Notional | 0.001 | FILL/FILL_EFFECTIVE |
| Stamp duty v2 | `MOF-STA:ANNOUNCEMENT-2023-39:1` + `PRC-NPC:STAMP-TAX-LAW:2021` | MOF/STA Announcement 2023 No. 39; NPC Stamp Tax Law | 2023-08-27; 2021-06-10 | from 2023-08-28 | XSHG/XSHE | SELL | Notional | 0.0005 | FILL/FILL_EFFECTIVE |
| Transfer | `CSDC:SSE-FEE-TABLE:2025-06-30` | CSDC Shanghai table | 2025-06-30 | 2025-06-30 coverage | XSHG | both | Notional | 0.00001 | FILL/FILL_EFFECTIVE |
| Transfer | `CSDC:SZSE-FEE-TABLE:2025-06-30` | CSDC Shenzhen table | 2025-06-30 | 2025-06-30 coverage | XSHE | both | Notional | 0.00001 | FILL/FILL_EFFECTIVE |

Load-bearing records:

- `PRC-NPC:STAMP-TAX-LAW:2021` — 全国人大常委会，《中华人民共和国印花税法》（主席令第八十九号），
  published 2021-06-10, effective 2022-07-01; establishes seller-only securities stamp duty and transaction-notional basis;
  <https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html>.
- `MOF-STA:ANNOUNCEMENT-2023-39:1` — 财政部、国家税务总局，《关于减半征收证券交易印花税的公告》，
  published 2023-08-27, effective 2023-08-28; changes the statutory 1‰ rate to 0.5‰;
  <https://jx.mof.gov.cn/xxgk/zhengcefagui/202309/t20230904_3905337.htm>.
- `CSDC:SSE-FEE-TABLE:2025-06-30` and `CSDC:SZSE-FEE-TABLE:2025-06-30` — 中国结算 Shanghai/Shenzhen
  securities registration-and-settlement fee tables, published/evidence-effective 2025-06-30; establish bilateral ordinary
  A-share transfer fees at 0.01‰; <https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml>.
- `CSDC:SH-SETTLEMENT-INTERFACE:V3.102` — 中国结算上海分公司，participant interface V3.102, published/effective
  2026-07-17; corroborates two-decimal stamp/transfer fee fields and monetary rounding;
  <https://www.chinaclear.cn/zdjs/jshsc/202607/03060adf303a42009724bf4e2e6ec6f0/files/登记结算数据接口规范（结算参与人版V3.102）.pdf>.
- `CSDC:SZ-SETTLEMENT-INTERFACE:V5.17` — 中国结算深圳分公司，participant interface V5.17, published/effective
  2026-02-02; corroborates `N(12,2)` stamp/transfer fee fields;
  <https://www.chinaclear.cn/zdjs/jszsc/202601/1b4d49fa0dcb4385bdc47295723b5ccf/files/深市登记结算数据接口规范（结算参与人版Ver5.17）.pdf>.

Locators and normalized interpretations are in `src/onlyalpha/fee/packs/cn_a_share/sources.py`. The current CSDC Shanghai
and Shenzhen participant-interface specifications corroborate that stamp-duty and transfer-fee amounts are CNY values with
two decimal places; the Shanghai specification states monetary calculations are rounded to two decimal places. Rules
therefore use CNY-cent HALF_UP with no market minimum/maximum. Handling and regulatory fees are collected through settlement
participants and are included in client commission under the exchange commission rule, so they are not separately debited to
the investor.

## Authorities and provisioning

Pack identity is `CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`. Each venue has a stamp-duty family with versions `1` and `2`
and a transfer-fee family at version `1` (six Schedules total). Schedule input order does not affect fingerprint. Complete
ordinary-trade coverage still begins 2025-06-30 because that is the earliest verified transfer-fee table revision in this Pack.

`OnlyBrokerFeeContractDocumentLoader` parses a closed inline schema. `authorities.broker_fee_contracts` defines snapshots;
`accounts[].broker_fee_contract` only selects identity. Documents reject unknown fields, unquoted decimals, non-CNY P3
schedules, invalid source/authority, duplicates and conflicts. The production example provisions 0.03% commission with CNY 5
minimum via ORDER_CUMULATIVE.

## Deleted test/legacy production surfaces

`CN_A_SHARE_TEST_MARKET_FEE_PACK` was removed from production defaults, the production Pack factory, package exports, README
and examples. It remains available only from `onlyalpha.fee.testing` for explicit conformance-test installation. There is no
compatibility alias, production zero-commission fallback or implicit latest-version selection.

## Reference vectors

Independent vectors at `tests/reference_data/cn_a_share_fee_vectors.json` cover XSHG/XSHE BUY/SELL, small/large notionals,
complete context, Source IDs, Schedule/Rule identities, individual components and totals. The expected values are readable
JSON inputs and are not generated by the Fee Engine. Separate broker vectors cover below/exact/above minimum, two-fill below
minimum, two-fill crossing minimum and three fills.

## Partial/multi-fill results

The production combination is the XSHG transfer fee plus an exact-account 0.03% broker commission with CNY 5 minimum. The
three-fill cumulative-notional path CNY 10,000 → 20,000 → 30,000 applies commission increments CNY 5.00, 1.00 and 3.00 and
transfer-fee increments CNY 0.10, 0.10 and 0.10. Final cumulative charges are CNY 9.30. Retrying the third Trade fails as a
duplicate instead of charging again.

## Recovery results

The P3 recovery test performs Fill 1 → JSON checkpoint/restore → Fill 2 → JSON checkpoint/restore → Fill 3 over the exact
production Market Pack and broker minimum-commission Contract. Final accrual state, every Fee Application and increments are
identical to uninterrupted execution. The full formal `recovery` lane separately proves the unchanged durable transaction,
Account and Strategy Ledger projection/recovery kernel.

The two proofs are intentionally not represented as a CN A-share Engine run: the P4 execution Capability Gate still rejects
CN A-share durable Trade planning, and P3 forbids a test-only Runtime bypass. This preserves the mandatory product boundary
while proving production fee Authority stability and unchanged kernel recovery semantics.

## Reconciliation results

Production local components enter the existing P2 component reconciliation path. Exact component evidence returns `MATCHED`.
When external transfer fee remains equal but broker commission is CNY 0.50 higher, the planner returns
`RECONCILED_WITH_ADJUSTMENT`, creates exactly one CNY 0.50 broker-commission adjustment, and leaves the transfer component at
zero difference. No A-share-specific reconciliation implementation was added and no network Broker evidence was used.

## Determinism and architecture

Production defaults/examples/public exports no longer expose the test pack. Guards prohibit Broker commission in Market Pack,
unknown/1970/current/latest production data, A-share Kernel branches and symbol-prefix selection.

## Quality gates

All required gates passed on 2026-08-09. No `skip`, `xfail`, weakened assertion or fallback was added. The one skip in `fast`
and `core-full` is the existing Windows console-event contract on this macOS host. Performance-budget diagnostics remained
warnings under the repository's unchanged lane policy.

| Gate | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS; 67 packages audited |
| Ruff check | PASS |
| Ruff format check | PASS; 1,100 files |
| Core mypy | PASS; 492 source files |
| Tushare provider mypy | PASS; 15 source files |
| MiniQMT provider mypy | PASS; 36 source files |
| Virtual Broker mypy | PASS; 14 source files |
| Version sync | PASS; all packages `0.3.4` |
| `fast` | 997 passed, 1 skipped / 998 collected; 22.08 s |
| `integration` | 130 passed / 130 collected; 62.17 s |
| `core-full` | 1,127 passed, 1 skipped / 1,128 collected; 70.47 s |
| `recovery` | 295 passed / 295 collected; 155.75 s |
| `ashare` | 5 passed / 5 collected; 1.93 s |
| `miniqmt-contract` | 32 passed / 32 collected; 3.49 s |
| `exhaustive` | 112 passed / 112 collected; 8.34 s |
| `uv build --all-packages` | PASS; all four sdists and wheels built |

## Not implemented in P3

CN A-share durable execution; capability-driven execution resolver; Market Reference composition neutralization; real MiniQMT
fee evidence; real Broker commission query; Paper streaming recovery; durable outbound commands; Live Runtime; multi-account;
multi-broker; vectorized Backtest. These remain P4 or later work.
