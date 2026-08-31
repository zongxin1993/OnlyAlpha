# OnlyAlpha P9.3 Final Durable Market Data + Real Database Closure — Codex Implementation Prompt

## 0. 任务性质

你正在维护仓库：

- Repository: `zongxin1993/OnlyAlpha`
- Default branch: `master`
- 当前阶段：**P9.3 Final Durable Market Data + Real Database Closure**
- 下一阶段：**P9.4 Binance Spot Real Broker**

本任务不是重新设计 OnlyAlpha，不是开放式全仓审计，不是泛化重构，也不是进入 P9.4。

本任务的唯一目标是：

> **在进入 P9.4 之前，将 OnlyAlpha 的 Durable Market Data Platform、真实 PostgreSQL / ClickHouse 基础设施、Realtime Recording、Historical Backfill、Correction、Recovery、Revision、Coverage、Seal、Backup / Restore、HOT / COLD Maintenance 完整闭环。**

完成后必须能够回答：

```text
一个 Market Fact 从哪里来？
→ 是否已经被 WAL durable 接管？
→ 是否已经被 ClickHouse 精确持久化？
→ PostgreSQL 是否记录了长期 Segment Metadata？
→ WAL 是否已经可以安全回收？
→ Historical Scope 是否 COMPLETE / INCOMPLETE / UNPROVABLE？
→ 缺失数据如何补全？
→ Correction 是否生成新 Revision 而不是覆盖旧数据？
→ 哪一个 Revision 可以被正式消费？
→ Crash / Restart 后如何恢复到唯一状态？
→ 数据如何备份、恢复、冷热迁移和维护？
```

一旦 Stop Condition 满足：

> **STOP P9.3 and proceed to P9.4.**

不得继续以“还能优化”“还能重构”“再审计一次”为理由扩大任务。

---

# 1. 必读 Authority

开始任何实现前，严格按照仓库 `AGENTS.md` 规定阅读并理解：

```text
1. PROJECT_CONSTITUTION.md
2. Relevant Architecture / public Contracts
3. Relevant Accepted ADRs
4. P9 Roadmap / execution plan
5. AGENTS.md
6. Current source + tests + executable behavior
```

必须明确：

```text
PROJECT_CONSTITUTION.md
→ L0 highest normative authority

Architecture / Contract
→ L1

Accepted ADR
→ L2

Roadmap
→ L3

Current Task Contract
→ L4

Current Source + Tests
→ implementation truth
```

普通工程任务不得修改：

```text
PROJECT_CONSTITUTION.md
its pinned fingerprint
```

如果任务实施要求违反 Constitution：

```text
STOP IMPLEMENTATION
REPORT: PLAN_CONFLICT
```

本任务预期：

```text
Constitution Impact = NO
```

---

# 2. OnlyAlpha 永久原则

本任务必须保持：

```text
Uniqueness
Determinism
Market-Agnostic Core
Single Authority
Reproducibility
Fail-Closed
Explicit Boundaries
Recoverability
Traceability
```

必须遵守：

```text
Changing external market world
        ↓
Plugins / Gateways
        ↓
Stable provider-neutral contracts
        ↓
OnlyAlpha
        ↓
Deterministic durable state
```

禁止把：

```text
Binance
QMT
CTP
Exchange rules
Provider protocol
REST/WebSocket quirks
```

写入 Core canonical semantics。

---

# 3. Task Contract

## 3.1 Goal

最终形成一个可以长期运行的 Durable Market Data Authority System：

```text
Realtime / Historical Provider Facts
        ↓
Raw Provider Evidence
        ↓
Canonical Normalization
        ↓
WAL Durable Ownership
        ↓
ClickHouse Exact Physical Facts
        ↓
PostgreSQL Durable Segment Catalog
        ↓
WAL Safe Reclaim
        ↓
Coverage Proof
        ↓
Backfill / Correction
        ↓
Immutable MarketDataRevision
        ↓
Seal
        ↓
Exact Historical Query / Dataset Materialization
```

并在仓库拥有的标准 Docker Compose 数据库部署上验证：

```text
PostgreSQL 18.6
ClickHouse 26.3
shared production topology
production configuration template
isolated test override
persistent PostgreSQL / ClickHouse / HOT / COLD volumes
```

---

## 3.2 Modification Scope

优先允许修改：

```text
.github/workflows/quality.yml
quality-policy.toml
scripts/test_suite.py
scripts/verify.py                       # only if required by real impact
scripts/check_constitution.py

src/onlyalpha/persistence/postgres/*
src/onlyalpha/persistence/clickhouse/*

src/onlyalpha/market_data/durable/*

src/onlyalpha/data/*
src/onlyalpha/plugin/data_source.py

database/postgres/migrations/*
database/clickhouse/migrations/*

tests/market_data_durable/*
tests/research/postgres/*
tests/architecture/*                    # affected tests only

packages/provider/onlyalpha-plugin-binance/*
                                      # only minimal historical/evidence wiring
```

必须优先修改现有 owner。

禁止因为方便新建平行 subsystem。

---

## 3.3 Expected Impact Scope

本任务属于高风险任务。

真实 Impact Scope：

```text
Quality Infrastructure
Persistence
Schema / Migration
Database Compatibility
Secret / Environment Boundary
Market Data Authority
WAL
Crash Recovery
Reconciliation
Historical Coverage
Backfill
Correction
Revision
Seal
Backup / Restore
HOT / COLD Maintenance
Provider / Persistence Boundary
```

---

## 3.4 Out of Scope

禁止扩展到：

```text
P9.4 Binance Broker
private account API
order submission
fill reconciliation
LIVE Runtime
P9.5
Binance Futures
USD-M Futures
QMT
CTP
Depth / L2
Funding
Open Interest
Liquidation
Options
Kafka
NATS
Redis Streams
Flink
Spark
Iceberg
Delta Lake
distributed WAL
multi-node consensus
new generic event-sourcing framework
new global database abstraction framework
new progress/completion report authority
```

---

# 4. 当前必须修复的已知工程事实

## 4.1 PostgreSQL Version Authority Drift

当前主线可能仍存在：

```python
ONLYALPHA_POSTGRES_SERVER_MAJOR = 16
ONLYALPHA_POSTGRES_CLIENT_MAJOR = 16
```

以及 CI：

```text
postgres:16.10
postgresql-client-16
```

但实际 Infrastructure baseline 已冻结：

```text
PostgreSQL = postgres:18.6
```

必须消除这个漂移。

最终唯一兼容基线：

```text
Compose Deployment     postgres:18.6
OnlyAlpha Runtime      PostgreSQL major 18
GitHub Integration CI  postgres:18.6
Client Tools           major 18
```

禁止只改 CI 而不改 runtime guard。

---

## 4.2 ClickHouse Baseline

实际 Infrastructure baseline：

```text
clickhouse/clickhouse-server:26.3
```

需要建立明确的 OnlyAlpha compatibility check。

建议：

```text
Supported family = 26.3.x
```

通过真实：

```sql
SELECT version()
```

检查。

具体部署 image pinning 属于 Infrastructure；
OnlyAlpha 只拥有 application compatibility policy。

---

## 4.3 当前 CI 已知问题

先修当前阻塞项，包括但不限于：

```text
scripts/check_constitution.py Ruff import order
affected architecture tests after AGENTS / Constitution governance change
core-full accidentally collecting PostgreSQL integration tests
```

修复原则：

```text
fix root cause
do not weaken gate
do not skip valid tests
do not add magic text only to satisfy substring tests
do not restore deprecated progress/completion authority
```

---

# 5. 关键架构修正：Durable Ownership 与 Historical Authority 必须分离

这是本任务最重要的设计。

禁止继续隐含：

```text
ClickHouse exact
→ Coverage COMPLETE
→ Revision
→ Seal
→ WAL GC
```

作为唯一 WAL 释放路径。

因为实际长期系统存在：

```text
Raw-only evidence
MARKET_REFERENCE = UNPROVABLE
BAR/TRADE temporarily INCOMPLETE
```

它们可能已经完全 durable，但暂时不能 Seal。

因此必须冻结两层 Authority。

---

# 6. Layer 1 — Durable Fact Ownership

最终链：

```text
Provider Observation
        ↓
WAL append + fsync
        ↓
WAL_DURABLE
        ↓
SEALED Segment
        ↓
ClickHouse write
        ↓
inspect / verify EXACT
        ↓
PostgreSQL Durable Segment Commit
        ↓
DURABLE_SEGMENT_COMMITTED
        ↓
WAL GC_ELIGIBLE
        ↓
WAL reclaim
```

这一层回答：

> **这些具体 Raw / Canonical facts 是否已经被长期存储精确接管？**

它不回答：

> **这个 Historical Scope 是否完整？**

---

# 7. Layer 2 — Historical Authority

多个 durable segments：

```text
Durable Segments
       ↓
Requested Historical Scope
       ↓
Coverage Proof
       ↓
COMPLETE / INCOMPLETE / UNPROVABLE
       ↓
if COMPLETE
       ↓
MarketDataRevision
       ↓
Seal
```

冻结语义：

```text
Durable != Complete
Complete != Sealed
Sealed = Formal Historical Authority
```

只有：

```text
CoverageStatus == COMPLETE
```

才允许 Seal。

---

# 8. 为什么必须这样实现

如果不拆分：

```text
Raw-only
or UNPROVABLE
or temporary INCOMPLETE
→ cannot Seal
→ cannot GC WAL
→ WAL grows forever
```

这不适合长期运行。

拆分后：

```text
Raw-only
→ ClickHouse exact
→ PG durable metadata
→ WAL reclaim
→ no Seal
```

```text
MARKET_REFERENCE
→ durable
→ WAL reclaim
→ UNPROVABLE
→ no Seal
```

```text
BAR incomplete
→ durable
→ WAL reclaim
→ INCOMPLETE
→ later backfill
→ new COMPLETE Revision
```

这同时满足：

```text
Fail-Closed
Durability
Long-running operation
Recoverability
```

---

# 9. PostgreSQL Durable Segment Catalog

必须评估当前 `OnlyPostgresMarketDataCatalog`，优先在现有 owner 上扩展。

建议将现有“Revision Commit”内部隐含的 Segment 注册能力拆成明确的 durable operation，例如等价：

```python
commit_durable_segments(...)
```

职责：

```text
verify ClickHouse exact state already established
→ persist immutable Segment metadata
→ persist durable state event
→ verify exact PostgreSQL state
```

然后独立：

```python
commit_revision(...)
```

负责：

```text
Coverage Manifest
Revision
Revision ↔ Segment bindings
Seal
```

不要创建第二套 Catalog。

---

# 10. PostgreSQL Segment Metadata 必须足以脱离 WAL 长期恢复

当前 `OnlyIngestSegment` 已经或应当具有：

```text
segment_id
capture_session_id
source_id

provider
venue
market
stream
provenance

provider_schema
codec

instrument_id
data_kind
data_version
bar_type

start_ns
end_ns
first_sequence
last_sequence

record_count
raw_count
canonical_count
content_hash

created_at
sealed_at
```

PostgreSQL `market_ingest_segment` 必须保存长期恢复所需字段。

目标：

```text
WAL has been GC'd
+
PostgreSQL segment metadata
+
ClickHouse facts
→ exact Segment reconstruction / inspection possible
```

禁止让 WAL 成为永久 metadata archive。

---

# 11. WAL 角色必须冻结

WAL 是：

> **短期但 durable 的 Authority Transfer Buffer**

它不是：

```text
historical archive
permanent database
Revision authority
Coverage authority
```

状态继续保持类似：

```text
ABSENT
→ OPEN
→ SEALED
→ GC_ELIGIBLE
→ DELETED
```

禁止把：

```text
STORE_WRITTEN
REVISION_COMMITTED
SEALED_REVISION
```

复制成 WAL 自己的第二套业务 Authority。

---

# 12. WAL Safe GC Rule

唯一允许：

```text
ClickHouse EXACT verified
+
PostgreSQL durable Segment metadata committed
→ WAL GC may begin
```

不再要求：

```text
Historical Revision sealed
```

才能 GC。

但：

```text
UNKNOWN
PARTIAL
CONFLICT
CORRUPT
```

必须：

```text
NO GC
```

---

# 13. Unknown ClickHouse Write Outcome

必须继续保持：

```text
INSERT sent
→ connection outcome unknown
→ UNKNOWN
```

禁止：

```text
blind retry
```

必须：

```text
inspect_segment()
```

返回：

```text
EXACT
ABSENT
PARTIAL / CONFLICT
```

规则：

```text
EXACT
→ verify
→ continue

ABSENT
→ safe write

PARTIAL / CONFLICT
→ fail closed
```

---

# 14. Raw-only Evidence

必须支持：

```text
Raw Provider Evidence exists
Canonical Facts = 0
```

例如 normalization failure：

```text
Provider response exists
→ must preserve raw evidence

Normalization failed
→ cannot fabricate canonical fact
```

最终：

```text
Raw exact in ClickHouse
+
PG durable Segment metadata
→ WAL reclaim allowed
```

但是：

```text
Historical Seal = forbidden
```

除非未来由新事实形成可证明 Complete Revision。

---

# 15. Acquisition Intent

Backfill 需要区分：

```text
Requested Scope
```

和：

```text
Observed Scope
```

禁止把实际返回的数据范围反过来当请求范围。

例如：

```text
Requested:
09:30 ─────────── 15:00

Provider returned:
10:00 ─── 14:00
```

必须仍然判断：

```text
09:30 → 15:00 INCOMPLETE
```

而不是：

```text
10:00 → 14:00 COMPLETE
```

因此新增或完善一个极小的 provider-neutral immutable acquisition metadata concept。

概念字段：

```text
acquisition_id
request_fingerprint
source_id
requested_scope
provenance
created_at
```

优先复用现有：

```text
OnlyMarketDataProvenance
REALTIME_STREAM
REST_BACKFILL
REPAIR
REPLAY
```

不要建立大型新 framework。

---

# 16. Historical Backfill 不得新建 Binance 专用 Core API

现有 canonical SPI 已经有：

```python
OnlyHistoricalDataSource.load_bars(...)
OnlyHistoricalDataSource.load_trades(...)
OnlyHistoricalDataSource.load_quotes(...)
```

必须复用。

禁止新增：

```text
OnlyBinanceBackfillService in Core
ClickHouseBackfillAPI
BinanceDatabaseRepairAPI
```

---

# 17. Backfill Coordinator

建议新增或收口一个窄的 provider-neutral orchestration component，例如：

```text
OnlyMarketDataBackfillCoordinator
```

职责：

```text
1. accept exact Requested Scope
2. load existing exact sealed/durable facts
3. compute deterministic Coverage
4. derive typed gaps
5. call OnlyHistoricalDataSource for exact gaps
6. provider response enters existing evidence sink
7. same Durable Recorder
8. same WAL
9. same Durable Segment ownership transfer
10. rebuild Coverage
11. create new Revision only if COMPLETE
```

它不得：

```text
know Binance REST endpoints
know ClickHouse table SQL
know PostgreSQL schema details
```

---

# 18. Realtime / Backfill / Replay 必须在 Durable Boundary 合流

目标：

```text
WebSocket Realtime ───┐
                      │
REST Historical ──────┼─→ Raw Observation
                      │
Recovery Replay ──────┘
                              ↓
                    DurableMarketDataRecorder
                              ↓
                             WAL
                              ↓
                     Durable Segment Commit
                              ↓
                    ClickHouse + PostgreSQL
```

必须保证：

```text
same semantic provider fact
via realtime
via backfill
via WAL replay
→ same canonical fact identity
```

Arrival time 不得成为 semantic identity。

---

# 19. Historical Cache Boundary

当前 Historical Cache 只是：

```text
accelerator
local convenience
fetch optimization
```

它不是 Durable Market Data Authority。

禁止：

```text
cache hit
→ assume formal historical durability
```

正式 Historical Authority 只能来自：

```text
Durable Segment
+
Coverage Manifest
+
MarketDataRevision
+
Seal
```

---

# 20. Coverage Manifest 必须支持 Machine-Readable Gaps

当前：

```text
COMPLETE
INCOMPLETE
UNPROVABLE
```

语义必须继续保持。

为了自动 Backfill，应新增或完善 typed gap representation。

例如：

```text
BAR gap:
start_ns
end_ns
```

```text
TRADE gap:
first_sequence
last_sequence
```

Gaps 必须纳入 Coverage fingerprint。

满足：

```text
same facts
+
same requested scope
→ same status
→ same gaps
→ same manifest fingerprint
```

禁止 Backfill Coordinator 解析错误字符串决定行为。

---

# 21. BAR Coverage

必须继续严格证明：

```text
correct instrument
correct source
exact requested range
closed bar
external aggregation
1-minute semantics
exact temporal grid
no missing required bar
no conflicting canonical identity
```

例：

```text
exact grid
→ COMPLETE
```

```text
one missing bar
→ INCOMPLETE
→ exact typed gap
```

---

# 22. TRADE Coverage

只能依赖真实 provider continuity semantics。

要求：

```text
provider sequence semantics = CONTIGUOUS
exact expected first/last
exact sequence set
```

禁止使用：

```text
arrival index
runtime local counter
wall-clock spacing
```

作为 historical completeness proof。

---

# 23. MARKET_REFERENCE

继续冻结：

```text
Raw durable             YES
Canonical durable       YES
WAL reclaim             YES
Realtime consume        YES

Historical COMPLETE     NO
Historical Seal         NO
Dataset Materialization NO
```

Coverage：

```text
UNPROVABLE
```

直到未来存在独立冻结的 completeness contract。

---

# 24. Backfill Revision Contract

假设：

```text
R1 = S1 + S3
```

存在缺口。

获得：

```text
S2
```

新 Revision：

```text
R2 = S1 + S2 + S3

R2.parent = R1
reason = BACKFILL
```

R1 必须永远不变。

---

# 25. Correction Contract

假设：

```text
R1 = S1 + S_BAD + S3
```

禁止：

```text
UPDATE S_BAD
DELETE S_BAD
overwrite old ClickHouse semantic fact
mutate R1
```

必须：

```text
new correction segment S_FIXED

R2 = S1 + S_FIXED + S3

R2.parent = R1
reason = CORRECTION
```

旧 R1 必须仍然可 exact reproduce。

---

# 26. Revision Construction 必须脱离旧 WAL

当前或未来：

```text
R1 sealed
→ WAL GC
```

随后创建 R2 时：

禁止：

```text
require old WAL files
```

必须从：

```text
Parent Revision Segment Refs
+
PostgreSQL Durable Segment Metadata
+
ClickHouse Exact Facts
+
New Durable Segments
```

构建新 Coverage / Revision。

---

# 27. Dataset Identity / Lineage 不得回退

必须继续保持：

```text
DatasetSnapshot
= content identity
```

```text
DatasetMaterialization
= exact revision lineage
```

禁止：

```text
dataset fingerprint += revision_id
```

仅为了保留 provenance。

要求：

```text
R1 + Q → D1
R1 + Q → D1

R2 same content → D1
but R1→D1 and R2→D1 have distinct immutable lineage

R2 changed content → D2

R1 always reproducible
```

---

# 28. PostgreSQL Runtime / Client Compatibility

修改或确认：

```python
ONLYALPHA_POSTGRES_SERVER_MAJOR = 18
ONLYALPHA_POSTGRES_CLIENT_MAJOR = 18
```

必须测试：

```text
PostgreSQL 18.x accepted
16.x rejected
19.x rejected unless future deliberate decision
```

Client tools：

```text
pg_dump
pg_restore
psql
```

必须是 major 18。

---

# 29. GitHub PostgreSQL CI

`research-postgres`：

```text
postgres:18.6
```

不要使用：

```text
latest
18
16.10
```

安装 client major 18。

CI 应证明：

```text
migration
schema
transaction
market-data catalog
research stores
backup / restore targeted behavior
```

---

# 30. ClickHouse Compatibility Guard

新增或完善：

```text
OnlyClickHouseServerVersion
```

检查：

```sql
SELECT version()
```

预期 family：

```text
26.3.x
```

不允许：

```text
unknown version silently continue
```

不满足：

```text
fail closed
```

---

# 31. GitHub ClickHouse CI Lane

新增独立 lane，例如：

```text
market-data-clickhouse
```

使用：

```text
clickhouse/clickhouse-server:26.3
```

提供最小 test storage policy：

```text
hot
cold
hot_cold
```

执行真实 ClickHouse integration：

```text
migration
schema validation
Decimal exact roundtrip
timestamp exact roundtrip
raw/canonical linkage
segment write
segment inspect
UNKNOWN outcome
EXACT
ABSENT
PARTIAL
verification
backup
restore
HOT → COLD
logical hash/count unchanged
```

加入最终 quality gate。

---

# 32. core-full Test Boundary

`core-full` 不得隐式执行：

```text
postgres
clickhouse
external
requires_network
```

这些真实 integration 测试必须由 dedicated lane 拥有。

修正：

```text
test discovery / lane definition
```

而不是给 `core-full` 再启动数据库。

不要删除测试。

---

# 33. Environment / Secret Contract

新增：

```text
.env.example
```

提交 Git。

真实：

```text
.env
```

不得提交。

当前 `.gitignore` 已忽略 `.env` 时继续保持。

建议变量：

```dotenv
# PostgreSQL production
ONLYALPHA_POSTGRES_DSN=

# PostgreSQL tests
ONLYALPHA_TEST_POSTGRES_DSN=
ONLYALPHA_POSTGRES_RESTORE_TEST_DSN=

# ClickHouse production
ONLYALPHA_CLICKHOUSE_URL=http://onlyalpha-clickhouse:8123
ONLYALPHA_CLICKHOUSE_DATABASE=onlyalpha
ONLYALPHA_CLICKHOUSE_USER=onlyalpha
ONLYALPHA_CLICKHOUSE_PASSWORD=
ONLYALPHA_CLICKHOUSE_STORAGE_POLICY=hot_cold

# ClickHouse tests
ONLYALPHA_TEST_CLICKHOUSE_URL=http://onlyalpha-clickhouse:8123
ONLYALPHA_TEST_CLICKHOUSE_DATABASE=
ONLYALPHA_TEST_CLICKHOUSE_USER=onlyalpha
ONLYALPHA_TEST_CLICKHOUSE_PASSWORD=
ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY=hot_cold
```

---

# 34. `.env` 不是 Authority

必须保持：

```text
Infrastructure Deployment
→ endpoint / credentials
→ explicit environment
→ OnlyAlpha Config
```

禁止 library 自动：

```text
search cwd
load arbitrary .env
```

导致同一程序根据工作目录隐式改变行为。

如果需要开发辅助加载 `.env`：

必须在显式 CLI / dev launcher 层完成。

---

# 35. Secret Safety

所有：

```text
DSN
password
token
credentials
```

不得：

```text
print
repr
log
exception message
test failure dump
```

泄漏。

继续沿用现有：

```text
<redacted>
credentials=<redacted>
```

机制。

---

# 36. Test / Production Database Isolation

必须机械化防误操作。

建议：

```text
PostgreSQL production:
onlyalpha

PostgreSQL integration:
onlyalpha_test

PostgreSQL restore:
onlyalpha_restore_test
```

ClickHouse：

```text
production:
onlyalpha

test:
onlyalpha_test_<run-id>

restore:
onlyalpha_restore_<run-id>
```

任何 destructive test command：

```text
DROP
TRUNCATE
RESET
RESTORE TEST
```

若目标不符合 test naming contract：

```text
REJECT
```

禁止仅靠人工约定。

---

# 37. Standard Docker Compose Database Acceptance

P9.3 的正式数据库部署与验收基线由仓库中的标准 Compose 工程拥有：

```text
PostgreSQL:
postgres:18.6

ClickHouse:
clickhouse/clickhouse-server:26.3

Compose:
shared base
production override
test override
explicit environment templates
```

生产内部 endpoints：

```text
onlyalpha-postgres:5432
onlyalpha-clickhouse:8123
onlyalpha-clickhouse:9000
```

生产配置与测试 override 都不得发布数据库端口。数据库验收必须在 Compose
私有网络中的 acceptance container 内运行，避免宿主机 Python、client tool、
localhost port mapping 成为隐藏的第二套运行环境。

---

# 38. Compose Acceptance Runner

验收 runner 必须显式使用 test environment 和 base + test override：

```text
deploy/compose/compose.yaml
+ deploy/compose/compose.test.yaml
+ deploy/compose/.env.test.example
```

并执行：

```text
research-postgres
market-data-clickhouse
p9-3-real-database
```

测试 acceptance container 与生产应用都通过 Compose network 访问：

```text
onlyalpha-postgres:5432
onlyalpha-clickhouse:8123
```

禁止生产配置发布：

```text
0.0.0.0:5432
0.0.0.0:8123
```

测试 override 不得为方便宿主机测试而发布数据库端口。它只能增加隔离的测试卷、
PostgreSQL 16 upgrade source 与 acceptance runner；PostgreSQL 18、ClickHouse、
storage policy、health model 和 private network 必须继承共享 base。

---

# 39. Compose Acceptance 是数据库 CI 的正式入口

普通非数据库 GitHub CI：

```text
deterministic fixtures
offline-first
```

数据库 GitHub CI、本地验收与部署前验收统一调用 Compose Database Acceptance：

```text
merged production-shaped topology
persistent named volumes
real PostgreSQL / ClickHouse processes
real HOT / COLD storage policy
isolated test/restore databases
real backup/restore
```

普通 CI 与 Compose acceptance 都必须使用固定版本，但 CI service container 不替代生产形态的 Compose 配置验证。

Compose acceptance 不要求在每个 PR 自动运行。Unraid、NAS 或其他宿主平台属于后续 deployment choice，不是 P9.3 completion Gate。

---

# 40. Database Operator Surface

复用现有工具。

PostgreSQL：

```text
status
plan
migrate
initialize-deployment
validate
backup
restore-test
```

ClickHouse：

```text
status
plan
migrate
validate
move-partition-cold
backup-segment
restore-segment
```

禁止建立大型：

```text
UniversalDatabaseManager
```

可以新增一个极薄的 P9.3 acceptance orchestration entrypoint。

---

# 41. HOT / COLD Maintenance

当前 P9.3 不要随意冻结：

```text
7 days
30 days
90 days
```

等未经过设计批准的 retention TTL。

当前只需要：

```text
explicit partition movement
before integrity
move
after integrity
verify same logical content
```

HOT/COLD movement 只能改变 physical placement。

不得改变：

```text
canonical identity
content hash
segment identity
revision
seal
dataset identity
```

---

# 42. Backup / Restore

## PostgreSQL

必须验证：

```text
schema compatible before backup
pg_dump major 18
backup checksum
metadata
repository version/SHA
server version
migration checksums
restore into isolated _restore_test DB
schema verify
market-data catalog integrity
```

---

## ClickHouse

至少验证：

```text
segment backup
checksum
restore into isolated database
exact raw/canonical content
count/hash equality
```

---

# 43. Recovery

Fresh Process Recovery 必须：

```text
Process A
→ create durable WAL / DB state
→ destroy Process A

Process B
→ fresh objects
→ no old in-memory scope map
→ recover_all()
→ same final authoritative state
```

禁止复用旧 Python object。

---

# 44. Crash Matrix

继续使用 deterministic barrier / fault injection。

禁止：

```python
time.sleep(...)
```

证明 correctness。

至少覆盖：

```text
before WAL durable
after WAL durable
during frame write
after fsync
during seal
after WAL rename
before ClickHouse write
UNKNOWN ClickHouse outcome
raw written / canonical partial
after exact verify
before PG durable segment commit
after PG durable commit before WAL GC
during WAL GC
after WAL delete before marker cleanup
during Revision commit
```

---

# 45. Required Test Cases — Durable Ownership

必须证明：

```text
realtime valid fact
→ WAL_DURABLE
→ CH EXACT
→ PG durable segment
→ WAL GC
```

```text
raw-only normalization failure
→ raw evidence CH EXACT
→ PG durable segment
→ WAL GC
→ no Revision Seal
```

```text
MARKET_REFERENCE
→ durable
→ WAL GC
→ UNPROVABLE
→ no Seal
```

```text
BAR INCOMPLETE
→ durable
→ WAL GC
→ no Seal
```

---

# 46. Required Test Cases — Backfill

## BAR

```text
requested scope has one missing interval
→ deterministic typed gap
→ HistoricalDataSource fetch only exact missing range
→ new durable Segment
→ rebuild Coverage
→ COMPLETE
→ new Revision R2
→ Seal
```

R1 不变。

---

## TRADE

```text
provider sequence:
100
101
104
105
```

必须得到：

```text
missing:
102-103
```

Provider-specific adapter 决定如何获取。

Core 不知道 Binance endpoint。

---

# 47. Required Test Cases — Correction

```text
R1 contains wrong segment
→ create correction segment
→ R2 parent=R1
→ R1 unchanged
→ exact query R1 returns old truth
→ exact query R2 returns corrected truth
```

重复执行相同 correction：

```text
deterministic identity
```

---

# 48. Required Test Cases — Database Version

PostgreSQL：

```text
18.6 → PASS
major 18 → supported
major 16 → fail closed
unsupported future major → fail closed
```

ClickHouse：

```text
26.3.x → PASS
other unsupported family → fail closed
```

---

# 49. Required Test Cases — Environment Safety

```text
missing required DSN
→ fail closed
```

```text
repr config
→ secret redacted
```

```text
test command receives production DB name
→ reject
```

```text
restore target is production
→ reject
```

---

# 50. Required Test Cases — Real PostgreSQL 18.6

至少：

```text
server version
client version
forward migration
schema verify
durable Segment commit
transactional Revision commit
append-only revision
append-only seal
same identity same content idempotent
same identity different content reject
backup
restore-test
critical catalog integrity
```

---

# 51. Required Test Cases — Real ClickHouse 26.3

至少：

```text
version
migration
schema validation
Decimal exact roundtrip
timestamp exact roundtrip
Raw/Canonical linkage
segment write
inspect
EXACT
ABSENT
PARTIAL/CONFLICT
UNKNOWN write outcome
exact verification
backup
restore
HOT→COLD movement
logical hash/count unchanged
```

---

# 52. Architecture Tests

基于现有 architecture test framework 增强。

必须确保：

```text
Provider package
does not import PostgreSQL / ClickHouse persistence implementations
```

```text
Core Backfill Coordinator
does not know Binance endpoints
```

```text
Historical Cache
is not formal Historical Authority
```

```text
Production Durable Path
cannot silently bypass recorder
```

```text
Revision
cannot mutate sealed historical truth
```

```text
Dataset identity
does not depend on mutable latest pointer
```

```text
Quality infrastructure
is not weakened to make current diff green
```

---

# 53. Quality Infrastructure Rules

根据 `AGENTS.md`：

业务实现不得为了跑绿修改：

```text
ignore
allowlist
threshold
test discovery
workflow condition
quality gate
```

除非本 Task Contract 明确在修正错误的 quality infrastructure。

当前 CI bug 属于本任务明确授权范围。

但所有修改必须：

```text
fix semantic error
not weaken protection
```

---

# 54. 实现顺序

严格按依赖顺序。

## Step 0 — Read Repository Truth

完整阅读：

```text
PROJECT_CONSTITUTION.md
AGENTS.md
relevant architecture/contracts
P9 execution plan
current P9.3 source
current tests
current CI
```

确认唯一 owner。

---

## Step 1 — Repair Current CI

修：

```text
Ruff
affected architecture tests
core-full DB test contamination
```

先让验证体系本身可信。

---

## Step 2 — PostgreSQL 18.6 Baseline Closure

修改：

```text
server major 18
client major 18
CI postgres:18.6
client 18
tests
```

---

## Step 3 — ClickHouse 26.3 Baseline Closure

实现：

```text
server version inspect
supported compatibility policy
CI clickhouse:26.3 lane
```

---

## Step 4 — Environment / Secret / Test Isolation

实现：

```text
.env.example
secret redaction
production/test guard
restore safety
```

---

## Step 5 — Durable Segment Ownership Separation

重构最小必要路径：

```text
CH exact
→ PG durable Segment
→ WAL reclaim
```

与：

```text
Coverage
→ Revision
→ Seal
```

分离。

这是本任务核心。

---

## Step 6 — Persist Complete Segment Semantic Metadata

补齐 PostgreSQL migration/model/store。

确保：

```text
WAL GC 后仍能 reconstruct Segment meaning
```

---

## Step 7 — Acquisition Intent + Machine Gaps

实现：

```text
Requested Scope
Observed Scope
typed gap
deterministic gap identity
```

---

## Step 8 — Backfill Coordinator

复用：

```text
OnlyHistoricalDataSource
existing provider REST path
existing evidence sink
existing Durable Recorder
```

不建立第二数据路径。

---

## Step 9 — Parent Revision / Correction Composition

确保：

```text
R2 can be built without R1 WAL
```

---

## Step 10 — Persistence Maintenance

完善：

```text
status
migrate
validate
backup
restore
HOT/COLD
reconciliation
```

---

## Step 11 — Standard Docker Compose Database Acceptance

使用仓库 Compose base + test override + explicit test environment 执行完整真实数据库场景。

---

## Step 12 — Bounded Independent Review

仅审：

```text
current diff
+
actual persistence/authority/recovery/backfill impact
+
direct Constitution invariants
```

只处理：

```text
Critical
High
```

最多一次 bounded remediation pass。

---

# 55. Verification Strategy

本任务是高风险任务。

开发阶段按 AGENTS 的 Impact-Aware 原则：

```text
targeted tests
affected Ruff
affected Ruff format
affected mypy
affected canonical lanes
affected architecture
risk-specific DB/recovery tests
```

不要每改一行都跑全仓。

完整 Phase Gate 只在本任务结束时执行一次。

---

# 56. Final Phase Gate

最终至少：

```text
static PASS
architecture PASS
openapi-contract PASS if affected
gateway-protocol PASS if affected
semgrep PASS
dependency-audit PASS
core-full PASS
research-postgres PASS @ PostgreSQL 18.6
market-data-clickhouse PASS @ ClickHouse 26.3
build PASS
web PASS if affected
```

以及 P9.3 specific：

```text
WAL crash tests PASS
fresh-process recovery PASS
durable Segment ownership PASS
raw-only lifecycle PASS
MARKET_REFERENCE UNPROVABLE lifecycle PASS
BAR backfill PASS
TRADE gap handling PASS
Correction PASS
Revision immutability PASS
Dataset identity / lineage PASS
PostgreSQL backup/restore PASS
ClickHouse backup/restore PASS
HOT/COLD PASS
standard Docker Compose database integration PASS
```

---

# 57. Standard Docker Compose Acceptance Scenario

使用 deterministic recorded provider payload。

不要让公网 availability 成为测试随机变量。

完整场景：

```text
1. verify PostgreSQL 18.6
2. verify ClickHouse 26.3

3. migrate both databases
4. validate schemas

5. start fresh WAL

6. ingest deterministic realtime fixture
7. establish WAL durable ownership
8. drain to ClickHouse
9. exact verify
10. commit PG durable segment
11. GC WAL

12. create incomplete historical range
13. prove INCOMPLETE
14. derive typed gap
15. run historical backfill
16. persist new segment
17. rebuild coverage
18. create R2
19. seal R2

20. restart with fresh process objects
21. recover unique state

22. PostgreSQL backup
23. isolated restore-test
24. verify catalog

25. ClickHouse backup segment
26. isolated restore
27. verify exact content

28. HOT → COLD move
29. verify before/after logical identity equal
```

任何一步没有真实证明：

```text
FAIL
```

不能用 mock 替代。

---

# 58. Forbidden Implementations

禁止：

```text
Provider directly INSERT ClickHouse

Provider directly write PostgreSQL

Backfill directly bypass WAL

Historical Cache becomes authority

Revision uses random UUID as semantic identity

Correction UPDATE old canonical fact

WAL GC before durable ownership proof

UNKNOWN write → blind retry

latest stored as semantic revision identity

test DB allowed to point to production name

secrets committed to Git

secret printed in logs

PostgreSQL latest image

ClickHouse latest image

sleep-based correctness tests

skip/xfail current real failures

deleting tests to pass CI

weakening architecture rules

restoring old progress/completion reports

creating P9.3 closure/status report as new Authority
```

---

# 59. Required Final Report in Codex Response

最终回复只需要报告执行事实，不创建仓库状态报告。

格式建议：

```text
P9.3 Final Closure Result

Modified:
- ...

Key behavior:
- ...

Database baseline:
- PostgreSQL 18.6
- ClickHouse 26.3

Validation:
- targeted ...
- postgres ...
- clickhouse ...
- recovery ...
- backfill ...
- architecture ...
- static ...

Docker Compose Database Deployment:
- PASS / NOT EXECUTED / FAIL

Independent Review:
Critical = X
High = X

Stop Condition:
SATISFIED / NOT SATISFIED

Next:
P9.4 allowed / blocked
```

不得把该回复写入仓库作为新的完成 Authority。

---

# 60. Stop Condition

只有以下全部成立才允许关闭 P9.3：

```text
Critical = 0
High = 0

Current CI correctness restored

PostgreSQL runtime baseline = major 18
GitHub PostgreSQL integration = postgres:18.6
PostgreSQL client tools = major 18

ClickHouse compatibility baseline = 26.3.x
GitHub ClickHouse integration = clickhouse/clickhouse-server:26.3

Production/Test/Restore DB isolation proven
Secrets never committed or exposed

Realtime durable path cannot bypass WAL ownership

ClickHouse UNKNOWN write reconciliation deterministic

PostgreSQL Durable Segment Catalog exists and is exact

WAL can be safely reclaimed after durable Segment commit

Raw-only facts are durable without fake historical completeness

MARKET_REFERENCE remains UNPROVABLE but does not leak WAL forever

BAR Coverage deterministic
TRADE Coverage deterministic

Machine-readable gaps deterministic

Historical Backfill uses existing provider-neutral HistoricalDataSource
Backfill uses same durable pipeline

Correction creates new immutable Revision
Old Revision remains reproducible

Revision construction does not depend on old GC'd WAL

Fresh-process recovery PASS

PostgreSQL real integration PASS
PostgreSQL backup/restore PASS

ClickHouse real integration PASS
ClickHouse backup/restore PASS
ClickHouse HOT/COLD integrity PASS

Standard Docker Compose PostgreSQL 18.6 acceptance PASS
Standard Docker Compose ClickHouse 26.3 acceptance PASS
Production Compose config validation PASS
Test Compose config validation PASS

Provider/Persistence architecture boundary PASS

affected static PASS
affected architecture PASS
required canonical lanes PASS

bounded Independent Review complete
```

一旦全部满足：

> **STOP P9.3.**

然后：

> **GO P9.4 — Binance Spot Real Broker.**

禁止继续：

```text
再审计一次
再优化一点
再统一抽象
再清理所有技术债
再做不属于本阶段的重构
```

---

# 61. 最终第一性原则

实现过程中始终使用下面的判断：

```text
Has the fact been durably accepted?
        ↓
If NO → WAL / ownership not complete

If YES:
Has the fact been exactly persisted?
        ↓
If NO / UNKNOWN → reconcile, fail closed

If YES:
Has long-term Segment metadata been committed?
        ↓
If NO → WAL cannot be reclaimed

If YES:
WAL may be reclaimed

Then ask:
Can the requested historical scope be proven complete?
        ↓
NO → INCOMPLETE / UNPROVABLE
     no Seal

YES
        ↓
Immutable Revision
        ↓
Seal
        ↓
Formal Historical Authority
```

这是本任务最重要的正确性边界：

> **Durability、Completeness、Historical Authority 是三个不同阶段。任何实现不得再次把它们混成一个布尔状态。**

OnlyAlpha 的目标不是“把行情写进数据库”。

OnlyAlpha 要建立的是：

> **一个长期运行、单一 Authority、可证明、可补全、可恢复、可维护、市场无关的 Market Data Truth System。**
