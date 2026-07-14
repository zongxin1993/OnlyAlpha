# Runtime 设计

## 1. Runtime 类型

```text
OnlyRuntime
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
```

## 2. 统一上下文

Cluster 通过 `OnlyRuntimeContext` 获取：

- Clock；
- Market Data；
- Order Service；
- Account/Position Query；
- Cache；
- Logger；
- Timer；
- Factor/Indicator；
- Instrument Registry；
- Risk Service。

Cluster 不接触具体 Gateway 或撮合器。

## 3. 隔离要求

每个 Runtime 必须有独立：

- runtime_id；
- Clock；
- Event Stream；
- Account Context；
- Position Context；
- Order Namespace；
- Cache Namespace；
- Metrics；
- 日志上下文。

## 4. Live

实盘 Runtime 使用真实行情和真实交易 Gateway。

默认禁止在测试环境下启动真实交易。

## 5. Paper

实时行情 + 模拟成交。

用于策略验证和 Web 操作演示。

## 6. Backtest

历史数据驱动虚拟时钟。

必须可配置：

- 撮合模型；
- 手续费模型；
- 滑点模型；
- 延迟模型；
- 交易日历；
- 初始资金；
- Instrument 历史版本；
- 数据缺失策略。

## 7. Research

只做数据、因子、统计和绘图，不产生真实交易状态。

## 8. 同时运行

同一 Engine 可同时存在多个 Runtime，但任意事件必须明确归属 runtime_id。

## 9. Runtime 时间约束

所有 Runtime Clock 返回 UTC。`OnlyBacktestClock` 拒绝 naive 和非 UTC 时间，并只能
单调推进。Backtest/Paper/Live 必须通过同一 `OnlyTradingCalendar` 判断 Session、午休、
夜盘与 TradingDay；不得从 UTC date、本地自然 date 或 Runtime 自建规则推导。
Backtest 数据按历史 Calendar 与 Instrument 版本解析。当前仍未实现完整历史驱动、Bar
聚合与撮合，这些后续能力必须遵守 `docs/time_model.md`。

每个 Runtime 独占并在停止时关闭自己的 `OnlyClock`。Cluster Context 只接收
`OnlyClockView`，可读取和注册/取消 Timer，但没有 `advance_to`、`advance_by`、`set_time`
或 `close`。只有 Backtest Runtime 的历史事件驱动器可持有 `OnlyBacktestClock` 控制接口。

## 10. MarketData 隔离

每个 Runtime 必须独占 EventBus、`OnlyMarketDataPipeline`、`OnlyMarketDataCache`、
`OnlyBarAggregationManager`、`OnlyIndicatorPipeline` 和 Dispatcher。一个 Runtime 内多个 Cluster
共享确定的派生 Bar/标准 Indicator；Live 与 Backtest 使用同一数据准备顺序。当前组件已实现这些独立
对象，但尚未把它们扩展为完整 Runtime 构造参数，装配方案进入后续 RuntimeContext 阶段。
