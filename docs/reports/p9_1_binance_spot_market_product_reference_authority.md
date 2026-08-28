# P9.1 Binance Spot Market Product & Reference Authority

- Task base: `0364b423e98d44ed2919db68c3e86a51284c4aec`
- Closure candidate HEAD: pending final CI-backed commit
- Scope: Binance Spot public reference, BTCUSDT and ETHUSDT, offline Market Product composition
- Status: C1-C8 IMPLEMENTED; targeted/local evidence PASS; required broad proof CI REQUIRED

## Capture and semantic identity model

P9.1 now separates five identities:

```text
Raw response identity
→ SHA256(exact endpoint response bytes)

Capture identity
→ environment + endpoint/request + capture time + parser contract + exact raw hashes

Semantic reference identity
→ canonical per-instrument economic and legality semantics

Reference authority identity
→ canonical exchange rules + sorted instrument semantic identities

Market Product composition identity
→ exact Reference Authority + Policy Compiler + Fee Pack + effective config
```

`OnlyBinanceSpotReferenceCapture` owns capture provenance and two endpoint-specific raw evidence objects. The capture fingerprint uses the formal `only_identity_fingerprint(...)` primitive. Capture time, environment, raw byte ordering and `serverTime` can change the capture fingerprint without changing semantic identity.

## Immutable storage and replay

The store layout is:

```text
captures/<capture_fingerprint>/
├── manifest.json
├── exchangeInfo.json
└── executionRules.json

references/<authority_fingerprint>/
├── manifest.json
└── reference.json
```

Capture publication and semantic publication are independent immutable operations. Exact duplicates reuse existing artifacts; corrupt or conflicting targets fail closed and are never repaired or overwritten. Multiple captures can point to one semantic authority while every capture remains retained.

`load_capture_verified()` verifies provenance, endpoint requests, raw byte hashes, capture identity and its semantic linkage. `load_reference_verified()` reads the explicit versioned canonical semantic schema, reconstructs typed references, recalculates all identities and never invokes the current normalizer. Decimal values are quoted canonical text, collections have stable order and observation time is canonical UTC metadata outside economic identity.

## Provenance contract

Every capture proves:

- provider `BINANCE` and product `SPOT`;
- environment `LIVE` or `SPOT_TESTNET`;
- exact `/api/v3/exchangeInfo` and `/api/v3/executionRules` requests;
- canonical requested symbol set;
- UTC capture time and provider `serverTime` when present;
- parser contract version;
- exact per-endpoint raw SHA-256;
- resulting semantic authority fingerprint.

Provenance does not become Market Product economic identity.

## Exchange and symbol rule authority

`exchangeFilters` is now a required parsed field on the authority. Empty exchange filters are valid. Official exchange capacity filters are typed and fingerprinted; any unknown exchange-level discriminator makes the authority incompatible and composition resolution fails closed.

Symbol rules retain distinct authorities for `LOT_SIZE` and `MARKET_LOT_SIZE`. `MIN_NOTIONAL` and `NOTIONAL` are parsed by their exact provider field contracts and normalized into one unambiguous notional policy; conflicting simultaneous filters fail closed. Dynamic `PERCENT_PRICE`, `PERCENT_PRICE_BY_SIDE` and `PRICE_RANGE` rules compile to explicit market-neutral requirements rather than static price bands.

The dynamic reference contract follows the current official Binance Spot semantics: percent filters use a venue reference price when present and otherwise the configured previous-trade average window; `PRICE_RANGE` requires the venue reference-price authority. P9.1 declares these realtime requirements but does not implement their P9.2 market-data authority.

## Canonical Market-Legality IR

Core gained only market-neutral values:

- optional MARKET-specific quantity bounds/increment on the existing quantity authority;
- `OnlyCompiledNotionalPolicy`;
- `OnlyCompiledDynamicPriceRequirement`;
- optional exact `as_of` on compilation/reference resolution.

All new policy values enter `policy_payload()` and `policy_fingerprint`. Generic T0 and CN A-share retain explicit `None`/empty defaults. Runtime LIMIT pre-trade evaluation now includes deterministic `NOTIONAL_MINIMUM` and `NOTIONAL_MAXIMUM` checks using `price × quantity × contract_multiplier`.

## Temporal applicability and cache correctness

Binance references use `observed_at` only as the earliest boundary proven by the published semantic artifact; it is not provider `effective_from` and is never back-projected. An aware timestamp before observation fails with `BINANCE_SPOT_REFERENCE_HISTORICAL_COVERAGE_UNPROVEN`; the exact observation timestamp and later timestamps resolve.

The Runtime compiles exact applicability before cache lookup and caches by `(instrument, trading_day, reference_fingerprint)`. A successful later same-day query therefore cannot make an earlier unproven query reuse the cached reference. Day-based Generic T0 and CN A-share authorities accept but do not invent intraday revision semantics.

## Permission and capability boundary

The reference separately retains:

- public venue support (`isSpotTradingAllowed`, order/TIF/STP/order-group features);
- OnlyAlpha Market Product support (the compiler's current LIMIT/cash/long-only contract);
- provider `permissionSets` with outer-AND/inner-OR grouping preserved.

Public `permissionSets` are requirements an account would need to satisfy; they are not evidence that any private account is eligible. Private account eligibility remains P9.4. Venue OCO/OTO/OPO support likewise does not claim OnlyAlpha Broker support.

## Bounded public HTTP

Public acquisition validates a JSON-compatible media type, rejects an oversized known `Content-Length`, and always reads at most `max_response_bytes + 1` so absent or incorrect length cannot bypass the bound. `application/json; charset=utf-8` is accepted. The stable oversize error is `BINANCE_PUBLIC_RESPONSE_TOO_LARGE`; no retry loop or credential surface was added.

## Verification evidence

Local PASS:

- Binance offline HTTP/reference/store/determinism tests: `30 passed`, `1 external deselected`.
- Binance public online contract: `1 passed` against current public `ping`, `time`, BTCUSDT/ETHUSDT `exchangeInfo` and `executionRules`.
- Binance/Generic/CN Market Product, Core contract, Runtime rule and architecture tests: `104 passed`.
- Targeted and impact-budget Ruff/format/Mypy: PASS.
- Strict affected Core plus provider/market package Mypy: PASS (`48 source files`).
- Binance provider and Market Product source/wheel builds: PASS.
- Workspace release graph `0.9.8`: PASS.
- `git diff --check`: PASS.
- Budgeted local verification: 10 static gates PASS; manifest `test-results/verification/local-budget/20260828T123220Z-0364b423e98d-85079/manifest.json`.

CI REQUIRED:

- The fail-closed impact plan contains 31 deferred gates, including Web, Core/Research/Recovery/A-share/MiniQMT lanes and all-package build.
- `scripts/local_verify.py run` returned `LOCAL_PASS_CI_REQUIRED` / exit code `3`; this is not PASS.
- GitHub CI has not yet closed this evidence because the local `gh` authentication token is invalid and no in-app browser session is available.

CI PASS: NOT EXECUTED for this closure candidate.

## Deferred scope

- P9.2 owns historical/realtime Binance Spot DataSource and the realtime reference-price evaluation authority.
- P9.3 owns WAL and production PostgreSQL/ClickHouse authority.
- P9.4 owns private account eligibility, actual commission, signing, submission, reconciliation and user streams.

No Historical Kline/WebSocket/DataSource, database/WAL, private API, Broker, Runtime, Futures or SDK dependency was added.

## Closure state

C1-C8 are implemented and locally evidenced. P9.1 remains **NOT VERIFIED** until all required CI gates pass on the final closure SHA. `project-state.toml` therefore remains unchanged and P9.2 is not yet authorized.
