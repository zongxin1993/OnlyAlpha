# Legacy PAPER Streaming Implementation / Sim Migration Source

本文只记录当前源码 spelling `PAPER` 的 streaming 实现事实。它是未来 Sim Runtime 的迁移来源，不是目标 Runtime 或
长期兼容合同；目标 taxonomy 只有 `RESEARCH/BACKTEST/SIM/LIVE`。当前 Profile 下的 PR5.1 current scope 已通过真实
MiniQMT 验收，但 Production streaming product 仍未闭环。

当前 legacy 实现的启动顺序为：

```text
INITIALIZING
→ SUBSCRIBING（实时 Callback 进入有界 Inbound Queue）
→ BOOTSTRAP
→ REQUIRED Historical Warmup
→ validated Historical Bars
→ MarketData Pipeline / Indicator / Factor / Strategy
→ Historical Watermark
→ CATCH_UP（按 Watermark 删除历史重叠）
→ LIVE
→ RUNNING
```

MiniQMT Historical Warmup 必须经过独立 Worker 进程，不能使用 `subscribe_quote(count=...)` 作为历史权威旁路。Runtime 先以 SDK 要求的 `count=-1` 建立分钟 K 线订阅，用回调携带的当日 Tail 封闭历史查询期间的丢数窗口；Callback 只写入有界队列，随后必须按 Historical Watermark 去重，不能取代 Required Warmup。Warmup 失败仍会取消订阅并 Fail Closed。Worker 成功后，Bar 按稳定顺序进入正式 MarketData Processor，再处理 Catch-up Buffer。

Runtime 生命周期与市场 Session 已分离。PRE_OPEN、BREAK、POST_CLOSE 和 CLOSED_DAY 均允许装配和启动；Historical 截止由 Calendar-aware Completed Bar Boundary 决定。Historical Bootstrap 与 Catch-up 会重建 Indicator、Factor 和 Strategy 状态，但订单副作用在进入 Risk/Order 前被明确抑制；只有 streaming `LIVE` phase 保留当前 `PAPER` 内部的 Shadow execution suppression。这一 phase 名称不是 Live Runtime 产品，也不表示 standalone Shadow Runtime。

最新完成节点统一写入 `OnlyLatestObservationStore`，Console、JSONL、CLI `snapshot` 和未来只读查询端只消费同一不可变 Read Model。每根实时 1 分钟 Bar 在下一周期边界正式闭合并通过 Pipeline 后发布一次 Observation，其中包含当前 Bar、Indicator 和 Factor Snapshot。Health 将非 OPEN 无数据表达为 IDLE，只有 OPEN 且超过下一预期 Bar 加宽限时才表达为 STALE。实时 Gap Recovery、重连、streaming checkpoint/recovery、DEGRADED 状态机以及产品级真实环境验收仍未完成。

P6 必须保留有用的 bootstrap、handoff、watermark、aggregation、observation 与 lifecycle 边界，以 Virtual Broker 和完整
Trading Kernel 替换 Shadow execution，形成目标 Sim Runtime；随后删除 `PAPER` spelling/implementation，不保留 alias、
deprecated spelling 或 wrapper。Standalone `SHADOW` 不是目标 Runtime。

状态必须区分：

```text
Legacy PAPER source runtime : PARTIAL
Realtime Data Path          : PARTIAL PASS
Internal Shadow capability  : PASS
Historical Isolation        : IMPLEMENTED
Any-Time Assembly           : PASS（自动化）
Observation Infrastructure : PASS（自动化）
Historical Compatibility    : PARTIAL（000001.SZ 通过；部分沪市查询仍 native abort）
Current Profile PR5.1 Scope  : PASS（真实 MiniQMT）
Production completeness      : PARTIAL
Target SIM Runtime          : NOT IMPLEMENTED
```
