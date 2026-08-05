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

Reference 只拥有证券事实，不拥有交易制度。`board`、`st_status`、`suspended`、RAW `previous_close`、`price_tick`
和 `lot_size` 在 Compiler 边界与当日有效 Profile 版本共同解析；Rule Engine 的 evaluate 阶段不再读取它们来重新决定制度。

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

缺失、冲突、失效、停牌和非 ACTIVE 状态分别产生稳定诊断，不再合并为 `INSTRUMENT_NOT_TRADABLE`。Checkpoint
恢复同时校验 Registry、Resolved Profile 与 Compiled Rules 指纹；任一权威变化都拒绝恢复。

The offline fixture at `tests/fixtures/reference/cn_a_share_v1/` covers SSE/SZSE main boards, ST, ChiNext, STAR,
suspension, and previous close. Its manifest verifies file SHA-256 before use.

This authority does not claim A-share durable execution, full T+1 settlement, fee closure, corporate-action
adjustment, or A-share matching.
