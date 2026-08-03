# Paper Runtime

Paper Runtime 当前是部分完成状态，不是已验收产品。

正式启动顺序为：

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

Runtime 生命周期与市场 Session 已分离。PRE_OPEN、BREAK、POST_CLOSE 和 CLOSED_DAY 均允许装配和启动；Historical 截止由 Calendar-aware Completed Bar Boundary 决定。Historical Bootstrap 与 Catch-up 会重建 Indicator、Factor 和 Strategy 状态，但订单副作用在进入 Risk/Order 前被明确抑制；只有 LIVE 阶段保留 Paper Shadow Execution 语义。

最新完成节点统一写入 `OnlyLatestObservationStore`，Console、JSONL、CLI `snapshot` 和未来 Web 只消费同一不可变 Read Model。每根实时 1 分钟 Bar 在下一周期边界正式闭合并通过 Pipeline 后发布一次 Observation，其中包含当前 Bar、Indicator 和 Factor Snapshot。Health 将非 OPEN 无数据表达为 IDLE，只有 OPEN 且超过下一预期 Bar 加宽限时才表达为 STALE。实时 Gap Recovery、重连、Paper checkpoint/recovery、DEGRADED 状态机以及产品级真实环境验收仍未完成。

状态必须区分：

```text
Paper Runtime              : PARTIAL
Live Data Path             : PARTIAL PASS
Shadow Execution           : PASS
Historical Isolation       : IMPLEMENTED
Any-Time Assembly          : PASS（自动化）
Observation Infrastructure: PASS（自动化）
Historical Compatibility   : PARTIAL（000001.SZ 通过；部分沪市查询仍 native abort）
Paper Product Acceptance   : FAILED
```
