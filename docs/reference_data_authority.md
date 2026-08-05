# CN A-Share Reference Data Authority

The canonical chain is:

```text
Config / frozen Provider fixture
→ Provider adapter
→ OnlyAshareInstrumentReference
→ OnlyAshareReferenceRegistry
→ resolve(OnlyInstrumentId, OnlyTradingDay)
→ resolved record projection
→ OnlyMarketRuleEngine
```

Records use `[effective_from, effective_to)` date ranges. `effective_to: null` is open-ended. The first supported
security type is `COMMON_STOCK`; exchanges are explicitly `SSE` or `SZSE`; canonical boards are `SSE_MAIN`,
`SZSE_MAIN`, `CHINEXT`, and `STAR`. Legacy `MAIN` and venue aliases are normalized only at the canonical adapter
boundary.

Required quoted Decimal fields are `lot_size`, `price_tick`, and `previous_close`. `st_status` and `suspended` must be
explicit booleans. No default can enter `CN_A_SHARE_CASH`. The previous close is the raw official rule base for that
trading day, not the last Bar close and not an adjusted price.

The Registry rejects overlapping ranges and conflicting identities. Its order-independent fingerprint participates
in Runtime grouping, output manifests, and checkpoint validation. Runtime output includes
`runtimes/<runtime_id>/reference_snapshot.json`, with a stable zero-record schema for non-A-share profiles. Compiled
rule diagnostics carry the selected record fingerprint.

The offline fixture at `tests/fixtures/reference/cn_a_share_v1/` covers SSE/SZSE main boards, ST, ChiNext, STAR,
suspension, and previous close. Its manifest verifies file SHA-256 before use.

This authority does not claim A-share durable execution, full T+1 settlement, fee closure, corporate-action
adjustment, or A-share matching.
