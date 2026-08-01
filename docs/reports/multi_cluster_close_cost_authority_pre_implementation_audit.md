# Multi-Cluster Close Cost Authority 预实施审计

- 审计基线：`master` / `0.3.1`
- 起始提交：`5d72aab33bc3c7c135f722b1b13b7ca5afd735d3`
- 审计日期：2026-08-01

## 现状与根因

1. Position Close 在 `OnlyPositionTradeReducer` 中调用 `only_reduce_average_cost_close()`，按账户聚合 Position 的精确累计成本释放成本。
2. Allocation Close 在 `OnlyAllocationTradeReducer` 中再次调用同一函数，但输入是当前 Cluster Allocation 的累计成本。
3. 单 Cluster 时 Position 与 Allocation 的数量、成本相同，两次独立计算偶然得到相同结果，所以问题不暴露。
4. 不同成本 Multi-Cluster 时，账户平均成本与 Cluster 成本不同；A@10、B@12 后平 A，Position 旧路径释放 11，Allocation 释放 10，破坏成本和 PnL 守恒。
5. 两个 reducer 在部分平仓后都保留原平均开仓价；Position 未从归因后的剩余精确成本重派生平均价。
6. Realized PnL 由 Position reducer 计算，Allocation、Account、Strategy Ledger 和 Fact 消费该 delta；但该单一 PnL 的成本输入错误地来自聚合 Position。
7. Account 与 Ledger reducer 没有重新计算 PnL；它们接收 Planner 传入的 delta。应保留此边界。
8. Committed Fact 已包含 Position/Allocation 前后数量、前后精确累计成本、唯一 `released_open_price_quantity`，以及 Position/Allocation/Account/Ledger PnL delta，字段足够承载新权威。
9. Economic Invariant 已校验数量、Fact/Projection 字段和 PnL delta，但缺少 Position released cost = Allocation released cost = Fact released cost、剩余平均价派生和 PnL 公式校验。
10. Runtime recovery 仅校验 Position Quantity = Allocation Quantity，未校验精确累计成本聚合。
11. 当前没有正式 Unallocated Cost Authority；主动平无归属成本不在支持范围，必须 fail closed。
12. Prompt 所述“现有 10 个失败”在当前提交上未复现：指定的三个纵切面文件基线为 7 passed。真正缺陷通过不同成本受控场景稳定复现；同时发现 Multi-Cluster 因 Account 与单 Ledger parity 比较而降级到 legacy mutation。
13. 旧数量断言集中在 analytics/artifact/report/result 场景；当前基线测试已演进，不能机械修改未失败断言。新增纵切面以 ready committed facts 为正式执行数量权威。
14. 应删除 reducer 的独立 close-cost 调用，以及 Allocation reducer 的独立 `realized_pnl_delta` 参数；不保留兼容适配器。
15. Position/Allocation reducer 的 close 分支应只接收同一个 `OnlyAttributedCloseCostAuthority`；Position Reservation 参数仍负责可卖与 hold 校验，具有独立意义。
16. Examples 未直接调用 reducer close-cost 接口；测试 harness 是主要调用面，需要迁移到新的 Planning Context 聚合权威。
17. Persistence schema 无需修改：Authority 已冻结在现有 Projection Before/After、Fact、authority hash 和 payload hash 中。
18. Transaction codec 无需新增字段或升级 schema；现有字段完整表达唯一 released cost。
19. Recovery Phase 无需修改或新增。恢复应用持久化 Projection；但 Multi-Cluster checkpoint timeline 必须按 Runtime 全局 sequence 冻结并完整恢复。
20. 统一方案：Planner 先以当前 Cluster Allocation 计算一次 attributed released cost 和 PnL，再将不可变 Authority 同时交给 Position 与 Allocation reducer；Account、Ledger、Fact 只消费该结论。

## 实施边界

正式范围为 Generic T0 Cash、Long/Netting、LIMIT SELL CLOSE、单币种、无 Margin。Unallocated Close、Cross-Cluster Close、FIFO/LIFO、Short、Hedging、Futures、Margin 和 FX 不在本次实现范围。
