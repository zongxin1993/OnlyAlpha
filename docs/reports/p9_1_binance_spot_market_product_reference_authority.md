# P9.1 Binance Spot Market Product & Reference Authority

- Base / HEAD: `504430db734687ece8e6b029ba4055f3657150bd` (dirty implementation worktree)
- Scope: Binance Spot public reference, BTCUSDT and ETHUSDT, offline Market Product composition
- Status: IMPLEMENTED; targeted/local evidence PASS; broad impact proof CI REQUIRED

## Implementation summary

Added the `onlyalpha-market-binance-spot` Market Product and `onlyalpha-plugin-binance` provider workspace packages. The provider performs credential-free bounded public HTTP capture and strict typed interpretation. The Market Product owns immutable semantic references, exact authority composition, provider-neutral 24x7 cash policy compilation, and an explicit configured-baseline fee pack. No DataSource, Broker, Runtime, LIVE, database, signing, or private-account surface was added.

Core changed only to export the existing market-neutral `OnlyOrderType` and `OnlyTimeInForce` vocabulary through `onlyalpha.plugin.api`. Root package metadata, forbidden-plugin imports, architecture checks, and impact mapping now include both packages.

## Authority ownership and identity

```text
Binance raw response bytes
→ OnlyBinanceSpotReferenceCapture (raw SHA-256 + captured_at)
→ strict normalizer
→ OnlyBinanceSpotReference (semantic fingerprint)
→ OnlyBinanceSpotReferenceAuthority (sorted reference fingerprints)
→ OnlyResolvedMarketProductBinding (exact authority + compiler + fee pack + economic config)
```

- Raw capture fingerprint includes exact bytes and changes with response ordering or `serverTime`.
- Semantic reference fingerprint includes canonical instrument/rule/status/capability/STP/permission values and excludes raw ordering, raw hashes, `serverTime`, and capture/observation time.
- Authority fingerprint is the stable sorted composition of per-instrument semantic fingerprints.
- Store publication is atomic and immutable; same semantic identity reuses the existing object, missing/corrupt/conflicting evidence fails closed.
- Day-only reference resolution rejects the observation day and earlier because exact pre-observation historical applicability cannot be proven.
- Factory selection requires an exact resource ID and expected authority fingerprint; it never accesses the network or resolves “latest”.

## Filter mapping

| Binance filter/rule | Classification | P9.1 handling |
|---|---|---|
| `PRICE_FILTER` | static economic | tick and optional static min/max price |
| `LOT_SIZE` | static economic | limit quantity min/max/step |
| `MIN_NOTIONAL`, `NOTIONAL` | static/order semantic | exact min/max notional preserved |
| `MARKET_LOT_SIZE` | order-type-specific | preserved separately from `LOT_SIZE` |
| `PERCENT_PRICE`, `PERCENT_PRICE_BY_SIDE` | dynamic market | typed canonical evidence; not misrepresented as static bounds |
| `PRICE_RANGE` execution rule | dynamic market | typed canonical evidence |
| `TRAILING_DELTA` | dynamic/order semantic | typed canonical evidence |
| order/count/position/list/amend limits | stateful capacity | parsed, classified, fingerprinted; no mutable enforcement in Instrument |
| unknown filter/rule discriminator | unknown critical | raw evidence retained; reference becomes ineligible |

## Capability mapping

`LIMIT`, `MARKET`, stop, stop-limit, touched and touched-limit orders map once to Core order vocabulary. `LIMIT_MAKER` maps to `LIMIT + POST_ONLY`, not a new Core order type. GTC/IOC/FOK are explicit protocol capabilities. OCO/OTO/OPO remain order-group venue capabilities. STP preserves `NONE`, `EXPIRE_MAKER`, `EXPIRE_TAKER`, `EXPIRE_BOTH`, `DECREMENT`, and `TRANSFER`; permission sets preserve outer-AND/inner-OR structure. Quote-order-quantity, trailing, cancel-replace, amend, and peg flags remain venue capabilities, not claims of OnlyAlpha Broker execution support.

## Policy and fees

Compiled policy is UTC continuous 24x7, immediate cash/asset settlement and availability, long-only, short-disabled, and margin-free. Instrument status remains independent from session openness. Fee rates are required quoted Decimals in composition config and carry `CONFIGURED_BASELINE` provenance; no account-actual Binance commission is claimed.

## Verification evidence

Local PASS:

- Binance determinism/reference/store/product tests: `16 passed`.
- Existing Market Product contract/discovery/architecture tests: `34 passed`.
- Current Binance public online contract: `1 passed` (`ping`, `time`, BTCUSDT/ETHUSDT `exchangeInfo` and `executionRules`).
- Ruff check/format and strict Mypy for changed Core API plus both packages: PASS.
- Both new workspace source/wheel builds: PASS.
- Workspace version graph (`0.9.8`): PASS.
- `git diff --check`: PASS.
- Budgeted local verification: 10 static gates PASS; manifest `test-results/verification/local-budget/20260828T083712Z-504430db7346-48998/manifest.json`.

CI REQUIRED:

- The impact plan is fail-closed because `scripts/verify.py`, shared architecture tests, package metadata, and a Core public API changed.
- 31 deferred gates remain recorded in the manifest, including Web gates, canonical Core/Research/Recovery/A-share/MiniQMT lanes, all-package build, and version sync.
- Exit code `3` is not PASS and no CI result exists yet.

CI PASS: NOT EXECUTED.

## Bounded follow-ups

- P9.2 owns historical/realtime market data and DataSource registration.
- P9.3 owns WAL and production PostgreSQL/ClickHouse authority.
- P9.4 owns private account commission authority, signing, submission, reconciliation, and user streams.
- No project-state transition is made until the CI-required impact proof closes.

## Definition of Done status

Provider, identity, Market Product, rule classification, crypto policy, immutable store, targeted tests, package builds, architecture and live public contract requirements are implemented and locally evidenced. Repository progression remains unchanged because the mandatory impact plan is not yet closed by CI.
