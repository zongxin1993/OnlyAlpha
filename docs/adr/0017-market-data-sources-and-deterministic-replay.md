# ADR 0017: Market data sources and deterministic replay

- Status: Accepted
- Date: 2026-07-15
- Modules: data, runtime, market_data, clock, cluster, broker

## Context

实时行情、历史数据、参考数据和券商交易可能来自不同供应商。此前 Backtest Runtime 直接推进 Clock 并调用 Pipeline，输入缺少
Source/Version/Quality，Live/Paper 也没有独立行情 Queue。

## Decision

- MarketDataGateway 与 BrokerGateway、MarketData Queue 与 Broker Queue 分离；
- 实时订阅、历史查询和 Reference Data 使用不同窄 Port，但输出统一 Domain；
- Update Envelope 保存 Source、Sequence、Version、UTC 双时间与 Quality；
- 所有标准 Update 经过 Runtime-owned `OnlyMarketDataProcessor`；
- 实时数据经有界 Queue，历史数据经 `OnlyHistoricalReplayService`，且只有 ReplayService 数据驱动 Backtest Clock；
- Replay 使用稳定全序，重复数据幂等，Gap 理解 TradingCalendar/Session；
- 正式回测默认使用版本化本地 Parquet，在线源不作为主循环隐式依赖；
- Cluster 只读取 immutable Snapshot，不知道 Source 实现。

## Rejected alternatives

拒绝把行情放入 BrokerGateway、Runtime 直接读 CSV/Parquet、DataSource 直接调用 Cluster、回测自行排序 DataFrame、在线 API 即时
驱动正式回测、文件顺序作为业务顺序、丢弃 Source/Version/Quality、历史与实时定义不同 Bar、Processor 或 DataSource 推进 Clock。

## Consequences

Backtest/Paper/Live 获得同一标准入口，Broker 回报不会被行情背压淹没。代价是 Runtime 增加数据平面资源；pyarrow 成为正式
Parquet 依赖。第一版仍为同步单写入者，不做商业 Adapter、多源融合、自动主备或分布式服务。

## Validation

Data 专项测试、33 个统一 Integration 场景、完整历史测试、100 次 Replay、七个 Demo、Ruff 和 Mypy 验证本决策。
