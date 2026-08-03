# Paper Runtime

Paper Runtime 当前是部分完成状态，不是已验收产品。

正式启动顺序为：

```text
INITIALIZING
→ BOOTSTRAPPING
→ REQUIRED Historical Warmup
→ validated Historical Bars
→ MarketData Pipeline / Indicator / Factor / Strategy
→ Historical Watermark
→ live subscription
→ RUNNING
```

MiniQMT Historical Warmup 必须经过独立 Worker 进程，不能使用 `subscribe_quote(count=...)` 作为历史回放旁路。Worker 成功后，Bar 按稳定顺序进入正式 MarketData Processor，并建立 `last_historical_bar_end`；失败时 Runtime 在订阅实时行情前 Fail Closed。

当前已形成的边界包括只读实时 Bar、Live Bar Finalizer、内部聚合、Indicator/Factor/Strategy、Shadow Execution 和 Historical Worker 隔离。完整 CATCH_UP Buffer、实时 Gap Recovery、重连、Paper checkpoint/recovery、Health/DEGRADED 以及产品级真实环境验收仍未完成。

状态必须区分：

```text
Paper Runtime              : PARTIAL
Live Data Path             : PARTIAL PASS
Shadow Execution           : PASS
Historical Isolation       : IMPLEMENTED
Historical Compatibility   : BLOCKED（本机 13/13 Case native abort）
Paper Product Acceptance   : FAILED
```
