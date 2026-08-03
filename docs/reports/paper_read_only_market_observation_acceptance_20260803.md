# Paper Read-Only Market Observation 验收记录（2026-08-03）

## 结论

PR5.1 总验收未通过，不能声明 Paper 产品链完成。

阻断点是默认 MiniQMT 客户端的历史 1m 查询在 XtQuant 原生 BSON 层终止进程：

```text
Assertion failed: u < 1000000
...\libs\thirdparty\bson\src\bsonobj.cpp, line 1388
```

正式 Runtime 已恢复为启动时强制执行 Historical Warmup，不再使用不能回放历史 Bar 的
`subscribe_quote(count=...)` 旁路。因此该错误会 Fail Closed，不能跳过预热后把链路标记为通过。

## 本机环境

```text
MiniQMT path : DEFAULT_USERDATA_MINI_PATH
Resolved path: C:\国金证券QMT交易端\userdata_mini
Client       : XtMiniQmt PID 13044
Service      : 127.0.0.1:58610
Data path    : C:\国金证券QMT交易端\userdata_mini\datadir
Symbol       : 600000.XSHG / 600000.SH
Base Bar     : 1m EXTERNAL
Derived Bar  : 3m INTERNAL
Runtime      : PAPER
Execution    : SHADOW
```

`get_full_tick(["600000.SH"])` 和实时 `subscribe_quote(period="1m")` 均能从默认客户端返回数据，
因此客户端连接和实时订阅本身正常。

## 已取得的真实行情证据

在移除无效历史旁路之前，正式 `OnlyEngine → Paper Runtime → MarketData Pipeline` 纵切面取得：

```text
closed live 1m Bars : 5
derived internal 3m : 2
latest 1m bar_end   : 2026-08-03T02:00:00Z
latest 3m bar_end   : 2026-08-03T02:00:00Z
fills               : 0
positions           : 0
fees                 : 0
settlements          : 0
```

另一次 10:19:49+08:00 启动的运行中，Runtime 收到并正式应用了 10:21 至 10:26 的五根连续闭合
1m Bar，并在 10:24 生成一根 3m Bar。该运行也暴露并修复了 MiniQMT 实时 Bar 固定使用四位价格精度、
与证券两位 `price_precision` 不一致的问题。

这些证据证明默认 MiniQMT 的实时回调、T+1 分钟闭合、单线程处理和 1m→3m 聚合可以工作；它们不能替代
Historical Warmup，也不能据此判定 PR5.1 总验收通过。

## 实现与自动化验证

已验证：

- MiniQMT 未闭合分钟回调由 Runtime Finalizer 在下一分钟只闭合一次；
- 同一分钟重复回调不会重复驱动 Indicator/Factor/Strategy；
- Finalizer 对闭合输出分配连续序号；
- MiniQMT Bar 价格按 Instrument `price_precision` 标准化；
- Paper Factory 禁止启用 Broker，只注入 Shadow Execution；
- Shadow 抑制不会产生 Venue Identity 或 Fill；
- Shadow 抑制后 Risk、Position、Cash、Margin Reservation 全部释放；
- Worker 在等待未来 Bar 时间戳时可以停止，无非守护线程泄漏；
- MiniQMT Callback 只做标准化和入有界队列，不执行 Strategy/Risk/Order/Console/JSONL。

门禁结果：

```text
ruff check                         PASS
ruff format --check                PASS
mypy src/onlyalpha                 PASS (426 source files)
related pytest                     PASS (287 passed, 1 skipped)
strict real Historical Warmup      FAIL (XtQuant native BSON assertion)
```

## 尚未达到 PR5.1 验收标准

- 默认客户端的真实 Historical Warmup 未通过；
- Historical Watermark、BOOTSTRAP/CATCH_UP/LIVE 去重没有取得真实环境验收；
- 修复后的两位价格精度尚未越过 Warmup 阻断取得新的真实 Shadow Order 证据；
- Observation Snapshot、独立有界 Publisher、Console/JSONL Sink 尚未实现；
- Streaming Runtime Health、DEGRADED 与有限重连尚未实现；
- 当前 Streaming Runtime 复用了 Backtest Runtime 的装配实现，尚未完成独立共享内核的架构收口；
- 尚无完整 Paper Integration、停机顺序、Observation 丢弃和 Health 状态验收。

在以上项目完成前，不更新 README、Roadmap 或 AGENTS 中的 Paper 产品完成状态。
