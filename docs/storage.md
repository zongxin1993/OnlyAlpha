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
