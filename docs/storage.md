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

## 3. Trading Runtime Persistence

```text
OnlyRuntimePersistenceStorePort
├── immutable Prepared / Committed Runtime Transactions
├── stable transaction indexes
├── Projection Ready progress
├── durable at-least-once Outbox intents
└── complete Runtime Checkpoint headers / components
```

Transaction Store 是成交 durable authority。Applied Projection Ledger 只记录 Projection 幂等进度，可由 committed
transaction 重建，不是第二份成交真值。Order、Position、Allocation、Account、Strategy Ledger 等 Manager Repository
保存各自 projection state；它们不得替代逐笔 committed fact，也不得通过最终 Snapshot 反推交易历史。

该边界只属于 Trading Runtime。Research Runtime 保存 Dataset、Calculation、Research Result 与 Artifact state，不为结构
对称创建 Order、Position、Account、Broker 或 Trading Transaction Store。

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

## 5. 当前实现

当前提供：

- 内存 Cache；
- Memory Runtime Persistence Store（不可 restart，checkpoint 必须关闭）；
- SQLite Runtime Persistence Store schema v5；
- Runtime Checkpoint schema v3；
- 不兼容 schema 显式拒绝，不做静默迁移或 Memory fallback；
- 不在 Domain 层写 SQL。

## 6. 恢复

正式恢复顺序是：

1. 打开 Store，验证 Runtime identity、Persistence schema 与配置/Participant fingerprint；
2. 读取并验证 latest complete Runtime checkpoint；
3. 按稳定 Participant Registry 顺序恢复各自 authority；
4. 分析 checkpoint 后连续的 committed transaction tail；
5. 在精确 MarketData/Broker 因果边界恢复 ordered Projection，并重建 Applied Projection Ledger；
6. 验证 Transaction、Projection、Manager、Broker、Outbox 与聚合 authority；
7. 原子写入并读回 post-recovery checkpoint；
8. Runtime Open 后才投递 continuation Outbox 并恢复 workload。

OnlyAlpha 只做 Forward Recovery：commit 后不跨 Manager rollback，不删除或改写历史 transaction，也不跳过失败 Projection。
完整协议见 `execution_runtime_recovery.md`。

## 6.1 Research Calculation Result Storage

Research Calculation Result Store 是 Storage，不是 Cache。它把 P7.2 deterministic execution 提升为 immutable durable research
fact，正式 authority key 是 `calculation_fingerprint`：

```text
<result-root>/sha256/<prefix>/<calculation_fingerprint>/
├── manifest.json
└── data/p-<index>.parquet
```

Calculation fingerprint 继续只回答“应计算什么”。Result Content fingerprint 基于 canonical logical partitions、exact Arrow
logical schema、timestamp axis 与 values；Calculation Result fingerprint 再绑定 Result schema version、Calculation fingerprint 与
Result Content fingerprint。Parquet `byte_sha256` 只检测 physical corruption，root、compression、row-group 和 `created_at` 不进入
semantic identity。

`created_at` 必须来自显式注入且经过 UTC 校验的 audit-time authority；Store 不直接读取系统时间。

Commit 先重新验证 Dataset Snapshot、Calculation Graph 与完整 execution linkage，在 sibling stage 写入每个
`(node_fingerprint, instrument_id)` partition，回读验证 logical round-trip，写 exact/versioned manifest，完整验证 stage 后才
atomic rename。相同 Calculation/Result 重复提交幂等；相同 Calculation 的不同 Result 是 deterministic conflict；existing
corrupt target 不 overwrite、repair 或 fallback。公开读取只有 verified path，会重算 Dataset/Graph/Calculation、partition
completeness、byte/semantic hashes、schema、row count、timestamp 与全局 Result identities，不返回 partial result。

该 Store 不提供 update、delete、overwrite、invalidate、refresh、TTL、LRU 或 cache-miss recomputation，也不复用 Trading
Transaction Store。P7.4 Research Job 只编排 verified reuse-or-execute，不成为新的 durable authority。Research Result 是 exact
Statistics composition authority，portable Research Artifact 是 immutable materialized read view；P7.10 Query/API 只从 Artifact
`load_verified()` 产生 ephemeral projection，不写入 Store、不创建 Query authority。finite Research Runtime 只编排既有 immutable
authority，不创建新的 storage/recovery authority。

## 7. 时间持久化协议

绝对时间只能存为 UTC ISO 8601 `Z`，或字段名明确单位的 Unix 整数（`*_ns/*_us/*_ms`）。
禁止无 offset 文本和无单位 `timestamp`。Domain serializer 会拒绝 naive/非 UTC datetime；
`OnlyTimestamp.unix_nanos` 可保存纳秒真值。IANA timezone、TradingDay、Calendar ID、
Calendar version 和 SessionType 必须作为独立业务字段保留。

P7.12 HTTP v2 只在 transport 边界把纳秒整数编码为 canonical decimal string；Web admission 后直接保存为 `bigint`。这不改变
Artifact/Query 的整数语义，也不创建 Web 时间 authority。Decimal 同样以 fixed decimal string 保持 exact；只有单向 chart projection
允许显式转换为有限 `number`，投影结果不得持久化或反向写回。

旧 naive 数据迁移必须提供来源 IANA 时区与迁移来源；DST 重复时间提供 fold，未知来源
或不存在时间失败。迁移批次应保留原值、转换值与回滚映射。Runtime Persistence Store 使用 canonical payload、显式
schema version 与内容 hash；时间字段必须继续服从上述协议。

## 8. Historical Bar Cache

标准接口位于 `onlyalpha.cache.historical`。`OnlyTimeRange` 使用 UTC 半开区间 `[start,end)`；
`OnlyHistoricalCacheService` 组合供应商无关 Provider 与 `OnlyParquetHistoricalCacheStore`。
默认产品链把 Store 根目录注入为 `<user_data>/cache/market_data`，插件不得从当前工作目录推断缓存位置。

缓存身份包含 source、dataset、Instrument、Bar Type、通用 `OnlyAdjustmentType`、可选复权参考锚点、Schema 与时间语义版本。
前复权供应商可把请求终点作为复权参考锚点，禁止不同终点错误复用同一缓存身份。
Manifest 的审计时间和绝对路径不进入内容指纹。Parquet 保存标准 `OnlyBar` 的无损确定性 JSON 与纳秒事件时间，
按事件年份分区；写入使用 staging、回读验证和原子替换。Manifest、Hash 或 Parquet 损坏会进入 quarantine，
不会进入 Replay。`CACHE_ONLY` 禁止 Provider；`PREFER_CACHE` 只请求缺口；`FORCE_REFRESH` 请求整个范围。

MiniQMT 负责供应商字段验证、symbol/exchange 映射和 Asia/Shanghai→UTC 解释；核心不导入 MiniQMT。

Manifest 分开记录 `resolved_ranges` 与 `observed_ranges`。前者表示供应商成功确认的完整查询区间，允许包含周末、节假日、停牌或合法空区间，并作为 Cache 完整性判定依据；后者仅表示实际 Bar 的 Session 区间，不得代替 resolved coverage。Tushare 等插件只返回这两类通用语义，不在核心引入供应商 SDK、代码映射或复权字符串。

## 9. Research Operational PostgreSQL

P8 operational PostgreSQL 通过 checksummed forward-only migration 管理 `research_run`、`research_run_attempt` 与
`research_run_submission`。0004 的 submission 表只保存 UUID4 retry key、canonical command fingerprint 与唯一 Run FK；Run recent
index 只服务 `(queued_at DESC, run_id DESC)` read projection。数据库仍不保存 Dataset/Calculation/Statistics/Result/Artifact content，
应用启动只检查 schema compatibility，不自动迁移。
