# PR5.1.3b Open-Market Bootstrap and Live Handoff Acceptance

执行日期：2026-08-04（Asia/Shanghai）

## 原始失败根因

失败 Artifact `paper-acceptance-20260804T013617Z-90b86b3a7b1e` 中，Worker 成功返回 53 根 Bar，但第 46 个
Pipeline Update 对应 2026-08-04 09:29–09:30 的开盘前 Bar。它不属于 Calendar Session，故 Pipeline 以
`source Bar is outside its Calendar session` 失败。旧实现已在 Replay 前用 Provider 尾部建立 Watermark，随后 Replay
中断；因此 Pipeline 仅处理 45 根，Historical Observation 尚未发布，Live Collection 从未开始。

修复后 Runtime 在 Replay 前按 Calendar 拒绝该 Bar并记录明确原因，继续处理合法 Bar；只有成功 Replay 的 Bar 才能建立
Watermark，Historical Observation 只能在 Watermark 和 Indicator/Factor 状态完成后发布。

## Historical Boundary

最终真实 Live Gate Artifact：`paper-acceptance-20260804T025200Z-94403bce08bb`

```text
bootstrap_observed_at          : 2026-08-04T02:46:46.680496Z
requested_end                 : 2026-08-04T02:46:00Z
provider_raw_bar_count        : 63
accepted_bar_count            : 53
replay_attempted              : 52
replay_processed              : 52
replay_rejected               : 0
provider_raw_last_bar_end     : 2026-08-04T02:46:00Z
accepted_last_bar_end         : 2026-08-04T02:46:00Z
processed_last_bar_end        : 2026-08-04T02:46:00Z
watermark_last_bar_end        : 2026-08-04T02:46:00Z
```

`bootstrap_observed_at` 与 `requested_end` 由 Runtime/Completed Boundary Resolver 冻结；Raw/Accepted 来自隔离 Worker；
最终运行的 53 根 Accepted 中有 1 根仅用于建立 3m 对齐起点，故 Replay 52 根且全部成功；Processed 来自正式
Pipeline，Watermark 只消费 Processed Authority。开盘初期真实运行和自动化回归另行覆盖 09:29–09:30 的 Session 外
Bar，明确记录 `HISTORICAL_BAR_OUTSIDE_CALENDAR_SESSION` 后继续合法 Replay。

## Live Timing 和真实结果

```text
旧 Live 等待               : 70s
新 Live Collection Timeout : 430s
Required Session Window     : 505s
实际 Collection Elapsed     : 308s

Live closed external 1m     : 6
Live derived internal 3m    : 2
Live observations           : 6
Live strategy intents       : 1
Shadow suppressed           : 1
Reservation created/released: 1 / 1
External order / fill       : 0 / 0
Position / fee / settlement : 0 / 0 / 0
Observation drop            : 0
Final Runtime               : CLOSED
```

最终真实 OPEN Historical Snapshot Artifact：`paper-acceptance-20260804T025228Z-a28f31c7da3a`，Verdict `PASS`。
最终真实 Open-Market Live Handoff Artifact：`paper-acceptance-20260804T025200Z-94403bce08bb`，Verdict `PASS`。

## 产品状态

```text
Paper Closed-Market Historical Path : PASS
Paper Open-Market Historical Path   : PASS
Paper Real Live Handoff             : PASS
PR5.1 Current Scope                 : PASS
Production Paper Runtime            : PARTIAL
```

Reconnect、Gap Recovery、Streaming Checkpoint/Recovery、真实 Broker、账户/仓位同步仍不在本次范围，不能据此声明
Production Paper Runtime 完成。
