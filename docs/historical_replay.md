# Historical Replay

`OnlyHistoricalReplayService` 是历史数据驱动 Backtest Clock 的唯一所有者。DataSource 不持有 Clock，Processor 不推进 Clock，
Runtime 旧 `process_bar()` 只保留为单记录版本化 Source/Request 的 Replay facade。

Synthetic product backtest 与 Parquet 使用同一 Replay 路径。Source 不能推进 Clock；Runtime 产品 `run()` 只准备正式
HistoricalDataStream 并调用 ReplayService。确定性指纹包含 Replay update/Clock 顺序和 MarketData Audit。

稳定全序为：

```text
ts_event → DataType(INSTRUMENT_STATUS, QUOTE, TRADE, BAR) → instrument_id → bar_type
→ configured source_priority → source_sequence → stable update_id
```

排序不依赖 dict、文件枚举、Source 返回或线程到达顺序。每条记录执行
`Clock.advance_to(ts_event) → MarketDataProcessor.process(update)`；Clock 回退被拒绝。Cursor 支持 step/run/pause/resume/stop，
Result 和 Audit 统计 applied/duplicate/gap/rejected/failed。

Replay 只在推进到事件时间后处理；Processor 拒绝晚于 Clock 的 Update；Pipeline/Snapshot 只保存已关闭 Bar。Next-Bar Matching
继续在本 Bar Pipeline 完成、策略回调之前撮合上一 Bar 已存在的订单，不读取订单提交前未来信息。正式回测不在主循环请求在线
API，配置、Calendar、Instrument/Rule、Source Version、输入数据与排序策略必须固定。
