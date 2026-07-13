# Cache 与 Storage 设计

## 1. 区别

Cache：加速访问，可丢失或重建。

Storage：可靠保存，可恢复、可审计。

## 2. Cache

```text
OnlyCache
OnlyCacheKey
OnlyCacheNamespace
OnlyCacheManager
OnlyMemoryCache
OnlyFileCache
OnlySqliteCache
OnlyRedisCache
```

键必须包含必要隔离维度。

## 3. Storage

```text
OnlyStorage
OnlyRepository
OnlyOrderRepository
OnlyTradeRepository
OnlyPositionRepository
OnlyAccountRepository
OnlyClusterStateRepository
OnlyBacktestResultRepository
OnlyInstrumentRepository
```

## 4. 要求

- Schema 版本；
- 原子写入；
- 幂等；
- 数据损坏检测；
- 重启恢复；
- 时区明确；
- 数值精度不丢失；
- Instrument 版本；
- 事务边界；
- 审计字段。

## 5. 初始实现

建议：

- 内存 Cache；
- SQLite Storage；
- 明确迁移脚本；
- 不在 Domain 层写 SQL。

## 6. 恢复

恢复顺序至少考虑：

1. Instrument；
2. Account；
3. Position；
4. Order；
5. Trade；
6. Cluster State；
7. Runtime State。

## 7. 时间持久化协议

绝对时间只能存为 UTC ISO 8601 `Z`，或字段名明确单位的 Unix 整数（`*_ns/*_us/*_ms`）。
禁止无 offset 文本和无单位 `timestamp`。Domain serializer 会拒绝 naive/非 UTC datetime；
`OnlyTimestamp.unix_nanos` 可保存纳秒真值。IANA timezone、TradingDay、Calendar ID、
Calendar version 和 SessionType 必须作为独立业务字段保留。

旧 naive 数据迁移必须提供来源 IANA 时区与迁移来源；DST 重复时间提供 fold，未知来源
或不存在时间失败。迁移批次应保留原值、转换值与回滚映射。当前 SQLite Storage 是
opaque bytes 骨架，尚未引入交易时间表 Schema。
