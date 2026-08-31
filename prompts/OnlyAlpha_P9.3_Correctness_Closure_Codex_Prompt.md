# OnlyAlpha P9.3 Correctness Closure — Codex Implementation Prompt

## 0. 任务性质

你正在维护仓库：

- Repository: `zongxin1993/OnlyAlpha`
- Default branch: `master`
- 当前工作阶段：**P9.3 Correctness Closure**
- 上一阶段目标：P9.3 Durable Market Data Platform / Production Data Foundation
- 下一阶段：P9.4 Binance Spot Real Broker

本任务不是重新设计 P9.3，不是继续开放式审计，也不是进行泛化重构。

本任务的唯一目标是：

> **关闭当前已知的 P9.3 正确性缺口，使 Market Data 从 Provider Event 到 Immutable Dataset Snapshot 的 Authority 转移具备唯一性、确定性、可恢复性和可证明性。**

完成本任务后，若 Stop Condition 满足，应立即停止 P9.3，不再继续寻找新的“优化项”，直接进入 P9.4。

---

# 1. 第一性原理

P9.3 不是“把 Binance 数据写进 ClickHouse”。

P9.3 要回答的是：

1. Provider 实际发送了什么？
2. OnlyAlpha 如何解释了这些 Provider 事实？
3. 哪些事实已经被 OnlyAlpha durable 接管？
4. 哪些长期存储内容已被精确验证？
5. 哪个历史范围可以被证明完整？
6. 哪一个 MarketDataRevision 是不可变、可重现的？
7. Research / Backtest 实际使用了哪个 exact Revision？
8. 相同 Revision + 相同 Materialization Request 是否永远得到相同 Dataset 内容身份？
9. 任意 crash/restart 后，系统是否只依赖 durable state 就能得到唯一恢复结果？

核心原则：

```text
Same Durable Evidence
+
Same Schema
+
Same Normalizer
+
Same Rules
=
Same Canonical Facts
=
Same Coverage Result
=
Same Revision
=
Same Dataset Content Identity
```

任何需要依赖“旧进程还记得什么”“operator 猜一下”“latest 当时大概是什么”的方案都不符合本任务。

---

# 2. 永久架构原则

必须遵循 OnlyAlpha 现有架构与工程原则。

## 2.1 唯一性原则

任何事实只能有一个 Authority。

| 问题 | 唯一 Authority |
|---|---|
| Provider 原始发送内容 | Raw Provider Evidence |
| 已被接管但尚未提交长期存储的事实 | WAL |
| 高频 Raw / Canonical 物理事实 | ClickHouse |
| Segment / Coverage / Revision / Seal 生命周期元数据 | PostgreSQL Catalog |
| Historical Completeness | Coverage Manifest |
| Historical Version Identity | MarketDataRevision |
| Revision 是否允许正式消费 | Seal |
| Research 数据内容身份 | DatasetSnapshot |
| Revision → Dataset 的来源关系 | DatasetMaterialization |
| Cache / latest projection | 非 Authority，只是 convenience / accelerator |

禁止建立第二套 Authority。

---

## 2.2 确定性原则

必须满足：

```text
same durable state
→ same recovery action
```

```text
same semantic provider event
→ same canonical identity
```

```text
same sealed revision + same request
→ same DatasetSnapshot content identity
```

```text
same revision binding + same request + same materializer version
→ same DatasetMaterialization identity
```

禁止随机 UUID 成为语义身份。

---

## 2.3 Fail-Closed

无法证明的事实必须保留：

```text
UNKNOWN
UNPROVABLE
INCOMPLETE
CONFLICT
CORRUPT
```

不得把“不知道”猜成 `COMPLETE`。

---

## 2.4 Append-Only

禁止：

```text
UPDATE historical fact
DELETE historical fact
overwrite sealed revision
silent correction
```

Correction / Backfill 必须创建：

```text
new Segment
→ new Coverage Manifest
→ new MarketDataRevision
→ new Seal
```

旧 Revision 永远可重现。

---

## 2.5 Provider 边界

Provider plugin 只负责：

```text
Provider protocol
Provider payload
Provider sequence/id
Provider reconnect/backfill
Provider-specific normalization
```

Provider package 不得 import：

```text
onlyalpha.persistence.clickhouse
onlyalpha.persistence.postgres
```

Binance 不得知道：

```text
ClickHouse table
PostgreSQL schema
Revision
Seal
DatasetSnapshot
```

Provider 与 Durable Platform 之间通过 provider-neutral SPI 交互。

---

# 3. 当前已知的五个根本问题

本任务只关闭这些已知问题及其直接影响范围。

---

## Problem A — Production Durable Recording 仍可被绕过

当前 DataSource creation path 允许：

```python
provider_evidence_sink = None
```

而 Binance 在 sink 不存在时可以继续运行。

这造成：

```text
Runtime Truth
!=
Durable Historical Truth
```

可能出现：

```text
Runtime 看到了 T100
但 WAL / ClickHouse / PostgreSQL 从未接管 T100
```

### 根因

把：

```text
Dependency Optional
```

错误等同于：

```text
Authority Optional
```

### 目标结果

底层 SPI 可以保持 optional，以支持 isolated unit tests。

但：

```text
Production Market Data Composition
```

必须强制：

```text
Durable Recorder exists
and is healthy enough to accept durable ownership
```

否则 production durable mode 必须 fail closed。

---

## Problem B — Recovery 依赖 transient scope map

当前 recovery 需要类似：

```python
recover_all(scopes: dict[str, OnlyMarketDataScope])
```

这意味着 crash 后的新进程还需要外部重新提供旧进程的 semantic scope。

### 根因

Segment 的 durable metadata 不能独立重建完整 semantic recovery intent。

### 目标结果

最终：

```python
recover_all()
```

必须只依赖：

```text
WAL
ClickHouse
PostgreSQL
static schema/config
```

禁止依赖旧进程 memory。

---

## Problem C — WAL 自身存在 crash atomicity hole

当前 segment 创建等流程跨多个 filesystem operation。

例如：

```text
create .open.wal
→ write .open.json
→ fsync directory
```

如果 crash 发生在中间，可能形成 orphan / ambiguous filesystem state。

### 根因

Logical state transition：

```text
ABSENT → OPEN
```

被多个 filesystem operation 表达，但中间状态没有唯一 restart 解释。

### 目标结果

必须保证：

```text
every observable filesystem state
→ exactly one deterministic interpretation/action
```

重点关闭：

```text
open creation
frame append/torn tail
seal
GC eligibility
GC deletion
```

的 crash windows。

---

## Problem D — MARKET_REFERENCE 存在 false completeness

当前 BAR 和 TRADE 有真实 coverage proof，但 fallback logic 可能把任意其他 data kind 用：

```python
complete = bool(in_scope)
```

处理。

这会把：

```text
“有数据”
```

错误等同于：

```text
“可证明完整”
```

### 目标结果

明确 Coverage capability。

至少：

```text
BAR              → COMPLETE / INCOMPLETE 可证明
TRADE            → COMPLETE / INCOMPLETE 可证明
MARKET_REFERENCE → UNPROVABLE（当前阶段）
```

MARKET_REFERENCE 可以 durable persist / realtime consume，但不能因为有记录就 Seal historical revision。

---

## Problem E — Dataset Content Identity 与 Revision Lineage 混合

当前 DatasetSnapshot 为 content-addressed 是正确方向。

但若：

```text
R1 → D1
R2 → D1
```

且 R1/R2 最终 canonical content 相同，Store 复用 D1 时可能丢失“此次 materialization 来自 R2”的 exact lineage。

### 根因

一个 Artifact 同时承担：

```text
Content Identity
```

和：

```text
Materialization Relationship
```

两个不同 Authority。

### 目标结果

保留：

```text
DatasetSnapshot = content identity
```

新增或完善：

```text
DatasetMaterialization = exact lineage
```

允许：

```text
R1 ─┐
    ├→ D1
R2 ─┘
```

同时有两个不可变 Materialization Record。

---

# 4. 最终 Authority Transfer 模型

实现完成后，应形成唯一生产链：

```text
Provider
   │
   ▼
Raw Provider Observation
   │
   ▼
Normalization
   │
   ▼
DurableMarketDataRecorder
   │
   ▼
WAL append + fsync
   │
   ├──────────────► Realtime Runtime
   │
   ▼
SEALED WAL
   │
   ▼
Durable Drain / Recovery Coordinator
   │
   ▼
ClickHouse Raw + Canonical Facts
   │
   ▼
Exact Verification
   │
   ▼
Coverage Proof
   │
   ▼
PostgreSQL Revision + Manifest + Seal
   │
   ▼
WAL GC Eligible
   │
   ▼
Exact Revision Query
   │
   ▼
DatasetMaterialization
   │
   ▼
Immutable DatasetSnapshot
```

---

# 5. Authority 时间边界

必须在代码和测试中体现。

## T0 — Provider event 尚未到达

OnlyAlpha 没有事实。

## T1 — Event 已收到但 WAL 未 durable

OnlyAlpha 不能声称拥有 durable ownership。

## T2 — WAL fsync 成功

从这一刻开始：

```text
WAL = uncommitted fact authority
```

后续数据库 down / timeout 不得导致 silent loss。

## T3 — ClickHouse write 已发送但结果未知

状态是：

```text
UNKNOWN
```

不得盲目 retry。

必须 inspect。

## T4 — ClickHouse exact verify 完成

表示 physical fact store 已验证，但还没有 historical authority。

## T5 — PostgreSQL Revision + Coverage Manifest + Seal commit

从这一刻：

```text
Historical Authority =
ClickHouse exact facts
+
PostgreSQL exact Revision/Manifest/Seal
```

## T6 — WAL GC

只有在 committed authority 已成立后，WAL 才能被安全清理。

---

# 6. Workstream A — Production Durable Composition

## 6.1 目标

Production data path 不得 silent bypass Durable Recorder。

## 6.2 设计

优先在现有 provider-neutral composition/bootstrap/factory 中实现。

不要把数据库逻辑放入 Binance。

可新增或收口现有组件为：

```python
OnlyDurableMarketDataRecorder
```

职责只包括：

```text
Raw Observation
+
Canonical Updates
→ encode durable record
→ append WAL
→ fsync
→ return durability receipt
```

禁止 Recorder 同步负责：

```text
ClickHouse network I/O
PostgreSQL transaction
Coverage
Revision
Dataset
```

---

## 6.3 Receipt

建议返回类似 provider-neutral immutable receipt：

```python
@dataclass(frozen=True)
class OnlyDurableRecordReceipt:
    segment_id: str
    ordinal: int
    durability_state: OnlyDurabilityState
```

`WAL_DURABLE` 只能在 WAL/fsync 成功后返回。

---

## 6.4 Production Enforcement

允许底层 Request SPI 继续 optional：

```python
provider_evidence_sink: OnlyProviderEvidenceSink | None
```

但 Production Composition 必须：

```text
production durable market data mode
+
missing recorder
→ fail closed
```

例如使用现有项目异常体系表达：

```text
DURABLE_MARKET_DATA_RECORDER_REQUIRED
```

不要改变 isolated unit test 的方便性。

---

## 6.5 Raw Evidence 与 Normalization Failure

必须支持：

```text
Raw Provider Evidence exists
Canonical Updates = zero
```

因为 normalization failure 不能抹掉 Provider 原始证据。

禁止：

```text
normalization failed
→ discard raw evidence
```

---

## 6.6 Health

不要让 Binance connectivity health 代替 durable health。

至少区分：

```text
Provider Connectivity Health
Durable Recording Health
```

例如：

```text
provider = HEALTHY
durable = DEGRADED
```

不得总体报告为完全健康而隐藏 WAL full / recorder unavailable。

复用现有 health / recovery / WAL observability 模型，不创建第二套 monitoring framework。

---

## 6.7 WAL Full

必须：

```text
WAL FULL
→ durable recording cannot accept new ownership
→ explicit failure/degraded state
```

禁止：

```text
warning
→ silently continue dropping durable evidence
```

Live Runtime 是否继续处理已有风险由更高层 P9.5 决定，本任务只保证 P9.3 不 silent drop。

---

# 7. Workstream B — Self-contained Recovery

## 7.1 目标

删除 recovery 对 transient `scope dict` 的业务依赖。

最终：

```python
recover_all()
```

fresh process 可以从 durable state 自举。

---

## 7.2 Segment Semantic Scope

扩展现有 immutable segment metadata，使它足以唯一重建 recovery scope。

至少评估并纳入：

```text
segment_id
capture_session_id
source_id

instrument_id
data_kind

start_ns
end_ns

first_sequence
last_sequence

market
stream
provider
venue
provenance

provider_schema
payload_codec

record_count
canonical_fact_count
content_hash

created_at
sealed_at
```

只增加真正恢复所需字段，不要为了未来泛化扩张 schema。

---

## 7.3 单 Segment Scope 原则

一个 segment 不得混合多个不相容 semantic scope。

第一版至少保证同一个 Segment 内：

```text
same source
same instrument
same data_kind
same provider stream/provenance family
```

禁止把：

```text
BTC BAR
BTC TRADE
ETH BAR
```

放进同一个 Segment。

---

## 7.4 Metadata 来源

能从 durable Segment 内容唯一计算的字段，应优先从内容计算。

例如：

```text
BAR:
start_ns = min(ts)
end_ns   = max(ts)
```

```text
TRADE:
start_ns       = min(ts)
end_ns         = max(ts)
first_sequence = min(provider_sequence)
last_sequence  = max(provider_sequence)
```

禁止 external caller 和 segment payload 各自维护两份相互独立事实。

---

## 7.5 Recovery 流程

最终 recovery 应类似：

```text
1. scan OPEN WAL
2. resolve legal intermediate states
3. repair/quarantine torn open tails
4. seal recoverable OPEN segments
5. scan SEALED non-GC segments
6. load immutable metadata
7. reconstruct/group exact semantic scope
8. inspect ClickHouse
9. write only when ABSENT
10. verify EXACT
11. prove Coverage
12. commit Revision/Manifest/Seal
13. mark WAL GC eligible
14. retry idempotent GC
```

---

## 7.6 Normal Path 与 Recovery Path 合一

不要维护：

```text
normal_writer.py 一套 state machine
recovery.py 一套 state machine
```

优先复用现有 `OnlyMarketDataRecoveryCoordinator`，把它收口成正常 drain 与 restart recovery 共用的唯一 orchestration core。

推荐逻辑：

```text
Normal:
seal
→ commit_segment_set()

Recovery:
scan
→ commit_segment_set()
```

同一 Segment Set 必须产生同一结果。

---

# 8. Workstream C — WAL Crash-State Closure

## 8.1 WAL 状态

冻结：

```text
ABSENT
→ OPEN
→ SEALED
→ GC_ELIGIBLE
→ DELETED
```

不要把 ClickHouse/PostgreSQL 的：

```text
STORE_WRITTEN
VERIFIED
COMMITTED
```

复制成第二套 WAL Authority。

这些由 coordinator/catalog 管理。

---

## 8.2 Filesystem State 必须唯一解释

必须定义实际磁盘组合与唯一 restart 行为，例如：

| Filesystem State | Required Interpretation |
|---|---|
| no files | ABSENT |
| empty `.open.wal` only | creation orphan → safely abandon |
| non-empty `.open.wal` without metadata | never silently discard; reconstruct if provable, else fail-closed/quarantine |
| `.open.wal` + valid open metadata | OPEN |
| `.open.wal` + corrupt metadata | CORRUPT / quarantine |
| `.sealed.wal` + valid immutable segment metadata | SEALED |
| sealed WAL only | deterministic reconstruct if possible, else fail-closed |
| metadata only | CORRUPT |
| GC marker + sealed files | GC_ELIGIBLE |
| unexpected combination | `WAL_STATE_CORRUPT` |

不要依赖 operator 手工猜。

---

## 8.3 Segment Creation

可以调整实际顺序，但必须保证每个中间状态可恢复。

推荐方向：

```text
1. generate deterministic/valid segment id
2. prepare metadata.tmp
3. fsync metadata.tmp
4. create/open WAL
5. fsync WAL
6. atomic publish metadata
7. fsync directory
8. expose OPEN state
```

重点不是“消灭所有中间态”，而是为每个中间态定义唯一 restart rule。

---

## 8.4 WAL Append

必须覆盖：

```text
partial frame
bad length
bad checksum
torn tail
valid prefix + corrupt suffix
```

允许：

```text
recover exact valid prefix
+
quarantine corrupt tail
```

不得 silently reinterpret bytes。

---

## 8.5 Seal

SEALED 后必须满足：

```text
WAL bytes immutable
segment metadata immutable
content_hash immutable
```

禁止：

```text
append sealed WAL
truncate sealed WAL
repair sealed WAL in place
rewrite semantic metadata
```

需要 correction 时创建新 segment。

---

## 8.6 GC

GC 必须 idempotent。

正确路径：

```text
PG committed
→ mark_gc_eligible
→ durable GC intent/marker
→ delete WAL
→ delete auxiliary metadata
→ finish
```

Crash 在任意一步：

```text
restart
→ inspect durable committed state
→ continue same GC
```

不得把“WAL 文件还存在”误解为 historical commit 未完成。

---

# 9. Workstream D — Coverage Correctness

## 9.1 禁止 fallback completeness

删除类似：

```python
else:
    complete = bool(in_scope)
```

任何新/未知 data kind 默认必须：

```text
UNPROVABLE / UNSUPPORTED
```

---

## 9.2 Coverage 状态

优先实现明确三态或等价强类型语义：

```python
class OnlyCoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNPROVABLE = "UNPROVABLE"
```

语义：

```text
COMPLETE
= 系统能够证明完整

INCOMPLETE
= 系统能够证明存在 gap/invalid fact

UNPROVABLE
= 当前 provider-neutral contract 无法判定
```

如果当前模型无法安全增加枚举，可采用等价 typed result，但不得继续依赖模糊 bool。

---

## 9.3 BAR

保持/强化现有严格验证：

```text
correct instrument
correct source
closed external 1m bar semantics
exact temporal grid
no missing required bar
no conflicting same identity / different content
```

如果 scope identity 需要 `bar_type` / interval 才能唯一，必须纳入 identity。

---

## 9.4 TRADE

Coverage 只能建立在真实 Provider continuity contract 上。

如果使用 Provider Trade ID / sequence：

```text
必须确认该字段确实具有当前 provider family 所需的 continuity 语义
```

不得把 runtime arrival counter 作为 provider historical completeness proof。

---

## 9.5 MARKET_REFERENCE

本阶段冻结：

```text
Raw durable             YES
Canonical durable       YES
Realtime consume        YES

Historical COMPLETE     NO
Historical Seal         NO
Dataset Materialization NO
```

它的 historical coverage result 必须是：

```text
UNPROVABLE
```

直到未来有独立冻结的 provider-neutral completeness contract。

---

## 9.6 Seal

唯一规则：

```text
CoverageStatus == COMPLETE
→ may seal
```

其余：

```text
INCOMPLETE
UNPROVABLE
CONFLICT
CORRUPT
```

全部禁止 Seal。

---

# 10. Workstream E — Dataset Identity / Lineage Separation

## 10.1 保持 DatasetSnapshot content-addressed

不要把 `revision_id` 加入 Dataset fingerprint，仅仅为了保留 provenance。

DatasetSnapshot 回答：

```text
WHAT content is this?
```

Fingerprint 继续由：

```text
DatasetDefinition
DatasetSchema
Canonical Content
```

等现有 frozen semantic input 决定。

---

## 10.2 新增/完善 DatasetMaterialization

DatasetMaterialization 回答：

```text
WHERE did this exact dataset materialization come from?
```

建议 immutable model：

```python
@dataclass(frozen=True)
class OnlyDatasetMaterialization:
    materialization_id: str
    dataset_snapshot_fingerprint: str
    market_data_revision_bindings: tuple[OnlyMarketDataRevisionBinding, ...]
    materializer_id: str
    materializer_version: str
    request_fingerprint: str
    created_at: datetime
```

Binding 至少：

```python
@dataclass(frozen=True)
class OnlyMarketDataRevisionBinding:
    source_id: str
    instrument_id: str
    data_kind: str
    revision_id: str
    revision_fingerprint: str
```

请适配当前项目现有 naming conventions，不要机械复制命名。

---

## 10.3 Materialization Identity

必须 deterministic。

例如：

```text
materialization_id =
hash(
    exact revision bindings
    + exact materialization request
    + materializer identity/version
    + resulting dataset fingerprint
)
```

禁止随机 UUID 成为语义身份。

---

## 10.4 Required Semantics

必须满足：

### Case A

```text
R1 + Q → D1
R1 + Q → D1
```

重复执行：

```text
same DatasetSnapshot
same Materialization identity
```

### Case B

```text
R1 content == R2 content
```

则：

```text
R1 + Q → D1
R2 + Q → D1
```

但：

```text
Materialization(R1 → D1)
!=
Materialization(R2 → D1)
```

### Case C

R2 修正了实际内容：

```text
R1 + Q → D1
R2 + Q → D2
D1 != D2
```

并且：

```text
R1 永远仍可得到 D1
```

---

## 10.5 Storage Authority

优先让 immutable DatasetMaterialization record 属于现有 Immutable Semantic Store / Dataset artifact体系。

PostgreSQL 可以保留 query projection/index，但不要让 mutable catalog row 成为唯一 semantic lineage authority。

复用现有 storage abstractions，不新建大型 artifact framework。

---

# 11. Exact Historical Query 约束

允许：

```text
resolve_latest(scope)
```

作为 convenience resolver。

但必须立即转换成：

```text
exact revision_id
```

随后 Research Definition / Backtest Definition 只能保存 exact revision。

禁止持久化：

```text
revision = "latest"
```

作为 semantic input。

正确：

```text
latest
→ resolve R17
→ persist R17
→ all future work binds R17
```

---

# 12. ClickHouse Correctness Contract

不要依赖：

```text
ReplacingMergeTree background merge
FINAL
eventual dedup
```

作为 semantic uniqueness authority。

Semantic correctness 必须继续由：

```text
deterministic canonical_fact_id
canonical_payload_hash
segment identity/content hash
exact inspection
exact verification
PostgreSQL Revision Manifest
```

保证。

---

## 12.1 UNKNOWN Write Outcome

如果：

```text
INSERT sent
→ connection timeout
```

状态必须是：

```text
UNKNOWN
```

不得直接 blind retry。

先：

```text
inspect_segment(segment)
```

返回三态：

### EXACT

```text
expected content exactly exists
→ do not rewrite
→ continue verification
```

### ABSENT

```text
expected content does not exist
→ safe to write
```

### CONFLICT / PARTIAL

```text
partial rows
same identity different payload
unexpected physical state
→ fail closed
```

不要用“再插一次试试”解决不确定性。

---

# 13. PostgreSQL Commit Contract

一次 Historical Revision Commit 应保持原子语义。

至少确保相关：

```text
segment catalog state
coverage manifest
market_data_revision
revision ↔ segment bindings
seal
```

不会形成相互矛盾的部分提交。

优先复用现有 PostgreSQL transaction / migration authority。

禁止创建第二套 P9.3 migration framework。

---

# 14. Correction / Backfill Contract

例如：

```text
R1 = S1 + S2 + S3
```

发现 S2 有错误：

禁止：

```text
UPDATE S2
```

必须：

```text
new correction segment S4
```

得到：

```text
R2 = S1 + S4 + S3
R2.parent = R1
reason = CORRECTION
```

R1 永远不变。

---

# 15. Crash / Fault Matrix

必须新增或完善 deterministic fault tests。

不能使用 `sleep()` 猜时序。

优先使用：

```text
explicit barrier
fake clock
fault injection
deterministic hook
```

---

## 15.1 WAL Internal

至少覆盖：

```text
W0 before segment creation
W1 after WAL created before metadata publish
W2 after metadata prepared before directory fsync
W3 during frame write
W4 after frame write before fsync
W5 after fsync
W6 during seal metadata creation
W7 after WAL rename before sealed metadata publish
W8 after seal complete
W9 after GC eligibility mark before file delete
W10 after WAL delete before auxiliary cleanup
```

具体编号可适配现有 `OnlyMarketDataCrashBoundary`，不要为了编号另建体系。

---

## 15.2 Durable Store

必须覆盖：

```text
C1 before ClickHouse raw write
C2 raw written, canonical absent
C3 write result UNKNOWN
C4 raw + canonical exact written, verify not completed
C5 after verify before PG commit
C6 during PG commit
C7 after PG commit before WAL GC
```

注意：

如果当前 `C4_RAW_BEFORE_CANONICAL` 已定义但真实 coordinator/store path 无法触发，必须修正 fault-injection seam，使该边界能在 real write orchestration 中被确定性测试，而不是只靠手工伪造内存状态。

不要因此大规模拆 ClickHouse abstraction。

---

# 16. Test Requirements

## 16.1 Production Composition Tests

必须证明：

```text
production durable mode
+
missing recorder
→ fail closed
```

并证明：

```text
isolated unit fixture
→ 可显式不配置 recorder
```

---

## 16.2 Semantic Identity Tests

必须证明：

```text
same provider semantic event
via WS
via REST/backfill
via WAL replay
→ same canonical fact identity
```

Arrival time 差异不能改变 semantic identity。

---

## 16.3 WAL Tests

至少：

```text
append/read
checksum
torn frame
bad length
valid prefix + corrupt tail
empty orphan open WAL
non-empty orphan open WAL
missing metadata
corrupt metadata
seal interruption
sealed immutability
capacity full
GC restart/idempotence
```

---

## 16.4 Fresh-Process Recovery Test

必须真正：

```text
construct process-like objects A
→ create durable filesystem/DB state
→ destroy A
→ construct fresh objects B
→ recover_all()
```

不得复用旧 scope dict。

不得依赖旧 Python object。

---

## 16.5 Real ClickHouse Integration

真实 ephemeral/test ClickHouse 至少验证：

```text
schema migration/validation
Decimal exact roundtrip
timestamp exact roundtrip
raw/canonical linkage
segment write
segment inspect
UNKNOWN/duplicate handling
partial/conflict state
exact verification
logical identity after HOT/COLD movement if current P9.3 supports it
```

不要全部 mock。

---

## 16.6 Real PostgreSQL Integration

真实 ephemeral/test PostgreSQL 至少验证：

```text
forward migration
transactional commit
append-only revision
append-only seal
duplicate deterministic commit
same identity / different content reject
revision-segment bindings
backup/restore of critical catalog truth if existing test infra supports it
```

---

## 16.7 Coverage Tests

### BAR

```text
exact 1m grid → COMPLETE
one missing bar → INCOMPLETE
wrong closed/external semantics → invalid/incomplete
same semantic id same content → deterministic duplicate handling
same semantic id different content → CONFLICT
```

### TRADE

```text
continuous provider sequence → COMPLETE
sequence gap → INCOMPLETE
```

### MARKET_REFERENCE

无论 1 条还是 10000 条：

```text
→ UNPROVABLE
→ cannot Seal
```

这是永久 regression test。

---

## 16.8 Dataset Tests

必须覆盖前述：

```text
R1 → D1
R1 repeat → D1

R2 same content → D1
but distinct immutable lineage binding

R2 changed content → D2

R1 remains reproducible forever
```

---

# 17. Architecture Tests

在现有 architecture test framework 上补充/修正，不建立第二套规则。

至少确保：

```text
Provider package
不得 import ClickHouse/PostgreSQL persistence implementation
```

```text
Research
不得直接把 mutable latest ClickHouse query 当 semantic truth
```

```text
Production DataSource composition
不得 silent bypass durable recorder
```

```text
Sealed Revision
不得 UPDATE/DELETE
```

```text
Dataset Snapshot identity
不得依赖 mutable "latest" pointer
```

---

# 18. 当前已知 CI / Governance 一致性问题

本 Closure 需要顺手关闭**已知且直接阻塞本阶段验收**的问题，但不得借此恢复废弃 Authority。

当前已知类型包括：

1. `scripts/verify.py` formatting
2. `tests/architecture/test_task_acceptance_policy.py` formatting
3. `tests/architecture/test_agent_verification.py` 与当前 verification API 不一致
4. `tests/architecture/test_p9_k0_authority_ownership.py` 仍期待已删除的旧 report artifact
5. 大规模 recovery lane 曾出现 pytest-xdist worker internal error

处理原则：

### Verification API

以当前 repository truth / `AGENTS.md` / current verification implementation 为准。

修测试适配当前唯一 API。

不要为了让旧测试通过，把旧 `VerificationChangeSet` API / `LOG_ROOT` / obsolete call shape 重新引入。

### Deprecated Report

不要恢复：

```text
docs/reports/p9_k0_product_surface_inventory.md
```

如果该文件已被架构决策删除作为进度/完成 Authority，则应修测试，让它验证“没有第二进度 Authority”，而不是把文件找回来。

### xdist

不要把一次 `pytest-xdist` internal error 误判成 3341 个业务测试失败。

为 P9.3 建立/使用**有界、确定性的 targeted recovery lane**。

如果需要验证大范围 suite，可以降低并发或采用更稳定执行方式，但不要因此重新设计 pytest infrastructure。

---

# 19. 允许修改范围

先阅读当前仓库实际结构，再使用现有 owner。

优先影响范围：

```text
src/onlyalpha/market_data/durable/*
src/onlyalpha/plugin/data_source.py             # only if contract enforcement requires
src/onlyalpha/... production composition owner  # inspect current repository first
src/onlyalpha/provider/binance/...              # only minimal evidence sink wiring/health effects
src/onlyalpha/persistence/clickhouse/*
src/onlyalpha/persistence/postgres/*
src/onlyalpha/research/dataset/*
database/clickhouse/migrations/*
database/postgres/migrations/*
scripts/verify.py
tests/market_data_durable/*
tests/integration/... relevant postgres/clickhouse
tests/architecture/... affected tests only
```

不要机械按此列表新建文件。

必须先识别当前唯一 owner，优先修改已有 owner。

---

# 20. 明确 Out of Scope

本任务禁止扩展为：

```text
P9.4 Binance Broker
private account/order/fill APIs
LIVE account reconciliation
Binance Futures
USD-M Futures
QMT
CTP
Depth/L2
Funding
Open Interest
Liquidation
Options
Kafka
Redis Streams
NATS
Flink
Spark
Iceberg
Delta Lake
distributed WAL
multi-node consensus
generic event sourcing platform
new migration framework
new progress/completion report framework
```

也不要顺手重构与本 Closure 无直接关系的大量模块。

---

# 21. 禁止事项

## 21.1 禁止恢复第二 Authority

不要创建：

```text
p9_3_status.md
completion_report.md
closure_report.md
new truth registry
```

作为第二完成/质量 Authority。

最终状态以：

```text
current source
tests
executable behavior
ADR / Architecture / Contract
```

为准。

---

## 21.2 禁止把 Provider 和 DB 耦合

禁止：

```python
from onlyalpha.persistence.clickhouse import ...
```

出现在 Binance provider 实现中。

---

## 21.3 禁止用 latest 作为 Research identity

禁止：

```text
dataset revision = latest
```

持久化成为 semantic definition。

---

## 21.4 禁止为 provenance 修改 Dataset content identity

不要简单：

```text
dataset_fingerprint += revision_id
```

来解决 lineage。

必须拆 Materialization record。

---

## 21.5 禁止 silent fallback

禁止：

```python
except:
    continue
```

掩盖 durability / coverage / conflict / corrupt。

---

## 21.6 禁止 sleep correctness

不得通过：

```python
time.sleep(...)
```

证明 crash/recovery/async correctness。

---

# 22. 实现顺序

严格按照依赖顺序。

## Step 0 — Read Repository Truth

先阅读：

```text
AGENTS.md
P9 architecture docs
ADR 0099
现有 P9.3 durable implementation
现有 recovery/revision/dataset tests
```

确认当前唯一 owner。

不要创建第二套抽象。

---

## Step 1 — Freeze Tests for Known Invariants

优先添加/修正能表达以下 invariant 的测试：

```text
Production durable path mandatory
Recovery self-contained
WAL intermediate states deterministic
Unsupported coverage fail closed
Dataset identity != lineage
```

不要先大规模改 SQL。

---

## Step 2 — Segment Semantic Scope

补足 immutable Segment metadata。

同步更新：

```text
model
codec
WAL metadata
hash/identity
tests
migration/catalog if required
```

---

## Step 3 — WAL Crash State Closure

关闭：

```text
open creation
frame append
seal
GC
```

中间态。

加 deterministic fault tests。

---

## Step 4 — Self-contained Recovery

把：

```python
recover_all(scopes)
```

收口成：

```python
recover_all()
```

或等价不依赖 transient external scope 的 API。

fresh process test 必须通过。

---

## Step 5 — Production Durable Composition

建立/收口：

```text
Durable Recorder
+
Durable Drain/Recovery Coordinator
```

Production Binance data path 不得绕过。

---

## Step 6 — Coverage Status / Provers

移除 fallback completeness。

实现：

```text
BAR proof
TRADE proof
MARKET_REFERENCE → UNPROVABLE
```

Seal 只接受 COMPLETE。

---

## Step 7 — DatasetMaterialization

保持 Snapshot content identity。

新增 exact immutable lineage relation。

---

## Step 8 — Real DB Integration

运行 real PostgreSQL + ClickHouse targeted integration。

---

## Step 9 — Repair Affected CI / Architecture Consistency

只修已知 impact scope。

不要恢复 deprecated report authority。

---

## Step 10 — Bounded Independent Review

只审：

```text
本次 diff
+
直接 authority / recovery / persistence / dataset impact
```

Review 只把：

```text
Critical
High
```

作为阻塞项。

允许最多一次有界 remediation pass，然后重跑 impacted acceptance tests。

不得开启无限审计循环。

---

# 23. Required Acceptance Tests

最终至少需要给出以下证据。

## A — Production Durable Path

```text
production durable mode + no recorder
→ deterministic fail closed
```

```text
production durable mode + recorder
→ event obtains WAL durable ownership before durable path can be considered healthy
```

---

## B — Restart Self-bootstrap

```text
sealed/open WAL + durable DB state
+
fresh process
+
no previous scope map
→ recover_all()
→ same final committed state
```

---

## C — WAL Crash Atomicity

至少证明：

```text
crash after open WAL creation before metadata
→ deterministic outcome
```

```text
non-empty orphan WAL
→ never silently discarded
```

```text
crash during seal
→ deterministic restart
```

```text
crash during GC
→ idempotent restart
```

---

## D — Store Unknown Outcomes

```text
CH write timeout after actual success
→ inspect EXACT
→ no blind duplicate write
```

```text
CH ABSENT
→ safe retry
```

```text
CH PARTIAL/CONFLICT
→ fail closed
```

---

## E — Coverage

```text
BAR missing point
→ INCOMPLETE
```

```text
TRADE sequence gap
→ INCOMPLETE
```

```text
MARKET_REFERENCE with data
→ UNPROVABLE
→ Seal rejected
```

---

## F — Revision Immutability

```text
R1 sealed
→ correction creates R2
→ R1 unchanged and still reproducible
```

---

## G — Dataset Determinism + Lineage

```text
R1 + Q → D1
R1 + Q → D1
```

```text
R2 same content → D1
but separate immutable R2→D1 Materialization
```

```text
R2 changed content → D2
```

---

## H — Real PostgreSQL

```text
migration PASS
transactional commit PASS
append-only enforcement PASS
duplicate deterministic behavior PASS
```

---

## I — Real ClickHouse

```text
migration/schema validation PASS
Decimal/timestamp roundtrip PASS
segment write/inspect/verify PASS
raw/canonical linkage PASS
```

---

## J — Architecture / Static

```text
ruff check PASS
ruff format --check PASS
affected architecture tests PASS
no deprecated report restored
provider/persistence boundary PASS
```

---

# 24. Independent Review Contract

本阶段 persistence/authority/recovery 属于高风险变更。

实现完成后执行一次 Independent Review。

Review 只回答：

```text
是否仍存在 Critical / High correctness blocker？
```

重点：

```text
authority split
crash recovery
silent bypass
append-only behavior
coverage proof
dataset lineage
provider/persistence boundary
```

不要进行风格型开放式审计。

若发现 Critical/High：

```text
修复
→ 仅重跑 impacted tests
→ 一次 final review
```

若：

```text
Critical = 0
High = 0
```

立即停止。

---

# 25. Stop Condition

只有下面全部满足才允许关闭 P9.3：

```text
Critical = 0
High = 0

P9.3 targeted unit tests = PASS
WAL crash tests = PASS
fresh-process recovery proof = PASS

ClickHouse real integration = PASS
PostgreSQL real integration = PASS

Coverage proof tests = PASS
Dataset determinism/lineage tests = PASS

affected architecture tests = PASS
ruff check = PASS
ruff format --check = PASS

Production durable path cannot silently bypass recorder

No deprecated progress/completion authority restored
No new competing authority introduced
```

达到以上条件：

> **STOP P9.3.**

不要继续：

```text
再审计
再优化
再抽象
再重构
```

直接声明：

```text
P9.3 Correctness Closure COMPLETE
Ready for P9.4 Binance Spot Real Broker
```

---

# 26. 最终 Codex 输出要求

完成任务后，只在最终回复中报告：

## 26.1 Repository State

```text
base SHA
final SHA / working tree state
```

如果执行前发现 HEAD 已变化：

- 不要假设旧 SHA 仍是基线；
- 以当前 `master` repository truth 为准；
- 重新定位相同五个根本问题是否仍存在；
- 只执行仍然成立的 closure；
- 不要重放已经被新代码解决的 patch。

---

## 26.2 Changed Files

列出实际修改文件及每个文件的职责。

---

## 26.3 Implemented Closure

明确说明五个根因分别如何被关闭：

```text
A Production Durable Composition
B Self-contained Recovery
C WAL Crash-State Closure
D Coverage Correctness
E Dataset Identity / Lineage Separation
```

---

## 26.4 Tests

给出实际执行命令和真实结果。

禁止虚构 PASS。

如果某项因环境不可执行：

```text
明确说明未执行原因
+
给出已执行替代证据
```

但不得把“未执行”写成 PASS。

---

## 26.5 Independent Review

报告：

```text
Critical:
High:
```

以及若有修复，简要说明。

---

## 26.6 Final Decision

只能二选一：

```text
GO P9.4
```

或者：

```text
NO-GO P9.4
```

如果 NO-GO，只列仍然存在的 **Critical / High** blocker。

不要重新输出几十条建议项。

---

# 27. 最终工程目标

本任务完成后，对于任意 Provider Market Event `E100`，系统必须能够唯一、确定地回答：

```text
Provider 实际发送了什么？
→ Raw Provider Evidence

OnlyAlpha 如何解释？
→ Canonical Market Fact

OnlyAlpha 何时 durable 接管？
→ WAL Segment + Ordinal

长期物理事实在哪里？
→ ClickHouse exact verified facts

属于哪个历史版本？
→ MarketDataRevision

为什么允许使用这个历史版本？
→ Coverage Manifest + Seal

Research 使用什么？
→ DatasetSnapshot

为什么该 Dataset 来自这个 Revision？
→ DatasetMaterialization
```

并且在以下任意 crash 边界：

```text
WAL creation
WAL append
WAL fsync
WAL seal
ClickHouse raw write
ClickHouse canonical write
ClickHouse timeout/UNKNOWN
verification
PostgreSQL commit
WAL GC
```

重启后：

```text
same durable evidence
→ same deterministic outcome
```

如果无法确定：

```text
UNKNOWN
UNPROVABLE
INCOMPLETE
CONFLICT
CORRUPT
```

必须显式暴露。

绝不允许通过猜测得到：

```text
COMPLETE
SUCCESS
HEALTHY
```

---

# 28. 核心不可违反 Invariants

实现和测试最终应保护以下永久规则：

```text
I1:
Production accepted market fact
⇒ durable ownership must exist

I2:
WAL durable
⇒ restart does not need old-process memory

I3:
Same WAL filesystem state
⇒ same recovery action

I4:
No provable coverage contract
⇒ no COMPLETE

I5:
No COMPLETE
⇒ no Seal

I6:
Same canonical Dataset content
⇒ same DatasetSnapshot identity

I7:
Different source Revision binding
⇒ distinct Materialization lineage

I8:
Sealed Revision
⇒ immutable forever

I9:
Unknown ClickHouse write outcome
⇒ inspect before retry

I10:
Provider package
⇒ no persistence implementation dependency

I11:
"latest"
⇒ convenience resolver only, never persistent semantic identity

I12:
Correction
⇒ new immutable Revision, never overwrite old truth
```

以这些 Invariants 为最终设计约束完成 P9.3 Correctness Closure。
