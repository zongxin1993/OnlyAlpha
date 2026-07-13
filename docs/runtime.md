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
