# ADR 0016: 标准 Historical Bar Parquet Cache

- Status: Accepted
- Date: 2026-07-19

## Context

Historical DataSource 需要共享确定性的本地缓存语义，同时保持核心不依赖供应商 SDK。仅判断文件存在无法证明
Schema、身份、覆盖或内容完整性；供应商插件各自实现缓存也会造成行为分叉。

## Decision

OnlyAlpha 核心拥有 UTC 半开区间、Coverage、Policy、Key、Manifest、质量验证、指纹、Parquet Store 与编排服务。
Coverage 分为决定完整性的 `resolved_ranges` 和描述实际 Bar 的 `observed_ranges`；缓存身份使用通用复权类型及可选复权参考锚点。
Store 位于标准 `user_data/cache/market_data`，保存标准化 `OnlyBar`，采用按年分区、SHA-256、staging 原子替换和 quarantine。
DataSource SPI 接收核心构造的缓存服务。MiniQMT 与 Tushare 各自只实现 Provider 和供应商时间/字段解释，核心不实现二者之间的兼容逻辑。

## Consequences

首次获取也必须从 Parquet 回读后 Replay；有效 `CACHE_ONLY` 回放不加载 SDK。未来供应商可复用相同边界。
第一版按年分区且 Manifest 使用单 Key 目录；分钟级大数据可在保持接口不变的前提下增加按月策略。
