# OnlyAlpha：修复 PR #58 跨平台 Core Tests，并消除 Execution Event 双发布路径

## 任务目标

以当前 OnlyAlpha `master` 为事实源，修复 PR #58 引入的跨平台 Core Tests 失败，并彻底消除以下错误事件链：

```text
Trade Events 写入 Durable Outbox
同时
OnlyExecutionEventPublisher.commit() 直接发布同一批 Events
```

当前 Trade 成功路径大致为：

```text
Manager Mutations
→ Build Committed Fact
→ Journal Append(Fact + Outbox Events)
→ EventPublisher.commit()
→ EventBus 直接发布
```

这会导致：

* Outbox 中的 Event 仍保持 Pending；
* 同一 Event 已经直接进入 EventBus；
* 将来调用 Outbox Publisher 时可能再次发布；
* Outbox 不是唯一交付路径；
* Event 发布失败状态不可可靠审计；
* PR #58 的 Core Tests 在 Linux、Windows、macOS 均失败。

本任务必须切实完成：

```text
1. 定位并修复跨平台 Core Tests 的真实失败根因
2. 已提交 Trade Event 只允许通过 Outbox 发布
3. 非 Trade Update 的直接发布语义保持清晰
4. 不伪称实现 exactly-once
5. 不扩展到完整 Execution Prepared Transaction 重构
```

不考虑历史兼容，不为旧测试或旧接口保留错误结构。

---

# 一、修改前审计

开始修改前执行：

```bash
git status
git log -n 10 --oneline

rg "OnlyExecutionEventPublisher"
rg "\.commit\(\)"
rg "\.pending\(\)"
rg "OnlyExecutionOutboxPublisher"
rg "pending_outbox"
rg "mark_outbox_published"
rg "append_transaction"
rg "OnlyDurableExecutionCommit"
rg "OnlyCommittedExecutionJournalPort"
rg "EXECUTION_UPDATE_APPLIED"
rg "EXECUTION_PROCESSING_FAILED"
```

同时检查 PR #58 对应的 CI：

* Core / Ubuntu；
* Core / Windows；
* Core / macOS。

必须先形成简短审计结论：

1. 三个平台失败的是哪些测试；
2. 是否为同一根因；
3. 是否与 SQLite、路径、序列化、时间、Event 顺序或旧测试预期有关；
4. Product/Integration 为什么能通过而完整 Core Tests 失败；
5. 当前哪些 Trade Events 同时进入 Outbox 和 EventBus；
6. 当前 Outbox Publisher 是否被 Runtime 调用；
7. 当前 `execution_outbox` 的 `published`、`attempt_count`、`last_error` 是否真实维护；
8. 非 Trade Update 当前如何发布 Event。

不得根据测试名称猜测问题，必须阅读失败日志并本地复现。

---

# 二、第一性原则

## 2.1 一个 Event 只能有一个主动发布路径

对于已经进入 Committed Execution Journal 的 Trade Event：

```text
Durable Outbox
→ Event Publisher
→ EventBus
```

是唯一合法路径。

禁止：

```text
Durable Outbox
+
直接 EventBus Commit
```

## 2.2 Journal 是成交提交权威

Trade Fact 已写入 Journal 后：

* Trade 已提交；
* Event 发布失败不能回滚 Trade；
* Event 必须保留在 Outbox 中等待重试；
* Processor 不得因为 EventBus 临时失败将 Trade 返回为未提交。

## 2.3 Event 交付语义是 at-least-once

当前单进程 EventBus 与 SQLite 之间无法天然提供 exactly-once。

本任务必须明确采用：

```text
Durable Outbox
+ Stable Event Identity
+ Idempotent Consumer Boundary
= At-Least-Once Delivery
```

不得声称：

```text
Event 永远只会被调用一次
```

本任务要消除的是确定性的双发布路径，不是假装解决所有崩溃窗口。

## 2.4 非 Trade Update 不应被强行写入 Trade Journal

Accepted、Rejected、Cancelled、Account、Position 和 Connection Update 当前没有对应的 Committed Execution Fact。

本任务不要为了统一外观，强行把所有 Update 塞进 Trade Journal。

应明确区分：

```text
Committed Trade Events
→ Durable Outbox

Non-Trade Execution Update Events
→ 成功处理后直接发布一次
```

---

# 三、重构 Event Buffer 边界

当前 `OnlyExecutionEventPublisher.commit()` 同时承担：

```text
结束 Buffer
清空 Buffer
直接发布 EventBus
```

职责混乱。

将其重构为明确的 Event Buffer，例如：

```python
class OnlyExecutionEventBuffer:
    def begin(self) -> None:
        ...

    def add(self, event: OnlyEvent) -> None:
        ...

    def add_many(self, events: tuple[OnlyEvent, ...]) -> None:
        ...

    def snapshot(self) -> tuple[OnlyEvent, ...]:
        ...

    def drain(self) -> tuple[OnlyEvent, ...]:
        """返回并清空，不发布。"""
        ...

    def discard(self) -> tuple[OnlyEvent, ...]:
        ...
```

也可以保留现有类名，但 API 必须表达相同语义。

禁止保留含义模糊的：

```python
commit()
```

因为它无法说明是：

* 提交内存 Buffer；
* 提交 Journal；
* 发布 EventBus；
* 结束事务。

不保留旧方法 Alias。

---

# 四、Trade 成功路径

Trade 成功路径应调整为：

```text
1. Begin Event Buffer
2. 执行当前 Trade 业务处理
3. 检查 Invariant
4. 构建 Committed Execution Fact
5. 获取 Buffered Events
6. Journal Append(Fact + Outbox Events)
7. 清空本地 Event Buffer
8. 调用 Outbox Publisher 尝试发布 Pending Events
9. 返回 APPLIED
```

示意：

```python
events = self._event_buffer.snapshot()

append_result = self._journal.append_transaction(
    OnlyDurableExecutionCommit(
        transaction_id=fact.execution_id,
        fact=fact,
        outbox_events=events,
    )
)

self._event_buffer.drain()

publish_result = self._outbox_publisher.publish_pending(
    self.config.runtime_id,
)
```

要求：

* Journal Append 前不得直接发布 Trade Event；
* Journal Append 失败时丢弃 Buffer；
* Journal Append 成功后不得调用直接 EventBus flush；
* Outbox 发布失败时 Trade 保持 `APPLIED`；
* Outbox 发布失败应进入 Audit/Quality Flag，而不是执行 Reconciliation；
* 重试不得重新执行 Manager Mutation；
* Result 仍只读取 Committed Journal。

---

# 五、Non-Trade Update 路径

对于没有 Committed Execution Fact 的 Update：

```text
Accepted
Rejected
Cancelled
Position
Account
Connection
```

处理成功后可以直接发布一次。

建立明确方法，例如：

```python
events = self._event_buffer.drain()
self._event_bus.publish_many(events)
```

或由独立边界负责：

```python
class OnlyDirectExecutionEventPublisher:
    def publish(self, events: tuple[OnlyEvent, ...]) -> None:
        ...
```

必须保证：

* Non-Trade Event 不进入 Trade Outbox；
* 不发布两次；
* 失败语义保持当前可审计行为；
* Trade 与 Non-Trade 分支在代码中显式可读；
* 不使用隐藏的 `isinstance` 分散在多个辅助函数中。

建议由 Processor 的单一提交分支决定：

```text
Trade APPLIED
→ Journal + Outbox

其他成功 Update
→ Direct Publish
```

---

# 六、Outbox Publisher 完整化

当前 Outbox 表已有：

```text
published
published_at
attempt_count
last_error
```

但没有完整维护。

扩展 Journal Port：

```python
def mark_outbox_published(
    self,
    runtime_id: OnlyRuntimeId,
    execution_sequence: int,
    event_sequence: int,
    *,
    published_at: OnlyTimestamp,
) -> None:
    ...

def mark_outbox_failed(
    self,
    runtime_id: OnlyRuntimeId,
    execution_sequence: int,
    event_sequence: int,
    *,
    error: str,
    attempted_at: OnlyTimestamp,
) -> None:
    ...
```

Memory 与 SQLite 实现必须保持相同 Contract。

成功时更新：

```text
published = true
published_at = authoritative Runtime timestamp
attempt_count += 1
last_error = null
```

失败时更新：

```text
published = false
attempt_count += 1
last_error = normalized error text
```

要求：

* Publisher 不吞掉失败证据；
* 一次失败后停止还是继续，由明确策略决定；
* 默认建议按顺序停止，防止后续 Event 越过失败 Event；
* Pending 查询必须稳定按：
  `execution_sequence, event_sequence` 排序；
* 不允许并发 Publisher 重复抢占同一行而无审计；
* 当前阶段单 Runtime 单 Publisher 即可，不构建分布式队列框架。

---

# 七、Event Identity

检查 `OnlyEvent` 是否已有稳定 Event ID。

如果已有，必须持久化并保持重启后不变。

如果没有，新增确定性身份，例如：

```text
runtime_id
+ execution_sequence
+ event_sequence
+ event_type
```

生成：

```text
event_id
```

要求：

* 同一 Outbox Row 重试时 Event ID 不变；
* Event Consumer 可以按 Event ID 幂等；
* 不使用随机 UUID；
* 不在每次重试时重新构建新 Event；
* Event ID 不依赖 Python `hash()`。

不要把 EventBus 自身升级为持久数据库。

---

# 八、Runtime 接入

将 `OnlyExecutionOutboxPublisher` 正式注入 Runtime Services。

建议：

```python
@dataclass(...)
class OnlyRuntimeServices:
    committed_execution_journal: OnlyCommittedExecutionJournalPort
    execution_event_buffer: OnlyExecutionEventBuffer
    execution_outbox_publisher: OnlyExecutionOutboxPublisher
```

Composition Root 负责构造：

```text
Journal
EventBus
Event Buffer
Outbox Publisher
ExecutionProcessor
```

Processor 只依赖抽象边界，不实例化具体实现。

Backtest 使用 In-Memory Journal 时，也必须走同一 Outbox 发布路径：

```text
Memory Journal Outbox
→ Outbox Publisher
→ EventBus
```

不得因为是 Backtest 就保留直接发布分支。

---

# 九、异常语义

必须明确以下结果。

## Journal Append 失败

```text
Fact 未提交
Outbox 未提交
Trade 不返回 APPLIED
Event 不发布
进入现有失败/Reconciliation 路径
```

注意：当前 Manager 已经原地修改的问题不在本任务中彻底解决，但不得让 Event 可见性进一步恶化。

## Outbox Publish 失败

```text
Fact 已提交
Trade 保持 APPLIED
Event 保持 Pending
记录 attempt_count 和 last_error
后续可以重试
不得进入 Trade Reconciliation
```

## Outbox Mark Published 失败

此时 Event 可能已经被 EventBus 接收，但 Outbox 仍为 Pending。

必须明确这是 at-least-once 崩溃窗口：

* 后续可能重复发布；
* Event ID 必须稳定；
* Consumer 应支持幂等；
* 不得删除 Outbox Row 猜测成功；
* 不得伪称 exactly-once。

---

# 十、修复跨平台 Core Tests

先复现，再修复。

至少执行：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples
uv run ruff format --check src tests examples
uv run mypy src/onlyalpha

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

必须重点检查：

* Windows Path 和 SQLite 文件关闭；
* Windows 下临时文件删除和连接锁；
* macOS/Linux 下时间和排序差异；
* Event 序列和 Fingerprint 变化；
* 旧测试是否仍假设直接 Event commit；
* SQLite Journal 是否缺失显式 `close()`；
* Event serialization 是否跨平台稳定；
* `str(Enum)` 与 `.value` 的序列化差异；
* 换行、路径分隔符、时间戳精度；
* 测试之间共享 EventBus 或数据库状态。

修复真实根因。

禁止：

* `pytest.skip()`；
* `xfail`；
* 按平台跳过；
* 放宽断言；
* 删除失败测试；
* 仅在 CI 中重跑；
* 增加 sleep；
* 捕获所有异常后继续；
* 用环境变量绕过功能。

---

# 十一、测试要求

## 11.1 Event 单路径测试

Trade 成功后验证：

```text
Journal 有 1 个 Fact
Outbox 有对应 Events
EventBus 每个 Event 只收到一次直接交付
Outbox 成功后无 Pending
```

测试必须证明 Processor 没有绕过 Outbox 直接调用 EventBus。

## 11.2 EventBus 失败测试

注入 EventBus 发布失败：

```text
Trade Status = APPLIED
Journal Fact 存在
Outbox Row 保持 Pending
attempt_count = 1
last_error 非空
Manager 不重复应用
```

第二次发布成功后：

```text
published = true
published_at 非空
attempt_count = 2
last_error = null
```

## 11.3 非 Trade Update 测试

分别覆盖：

```text
Accepted
Rejected
Cancelled
Position
Account
Connection
```

验证：

* Event 直接发布一次；
* 不创建 Committed Trade Fact；
* 不创建 Trade Outbox Row；
* Event Buffer 最终为空。

## 11.4 重试测试

同一 Pending Outbox 重试：

* Event ID 保持不变；
* 不新增 Fact；
* 不重新执行 Trade；
* 不推进 Execution Sequence；
* 不重新收费；
* 不重复修改 Account/Ledger/Position。

## 11.5 Memory/SQLite Contract

同一套测试覆盖：

```text
OnlyInMemoryCommittedExecutionJournal
OnlySqliteCommittedExecutionJournal
```

验证：

* Pending 顺序；
* Published 标记；
* Failed 记录；
* Attempt Count；
* Last Error；
* Published At；
* 重启后 Pending 保留；
* 重启后 Event Payload 和 Event ID 不变。

## 11.6 架构门禁

增加 AST 或等价门禁：

* Trade Journal Append 后不得调用 Event Buffer 的直接发布方法；
* ExecutionProcessor 不直接访问具体 SQLite；
* Outbox Publisher 是 Trade Event 的唯一 EventBus 调用方；
* Broker Plugin 不访问 Journal 或 Outbox；
* Result Collector 不读取 Outbox 发布状态；
* Non-Trade Direct Publisher 不接受 Committed Trade Event。

---

# 十二、代码清理

完成后删除：

* `OnlyExecutionEventPublisher.commit()`；
* Trade 成功路径中的直接 `EventBus.publish_many()`；
* Outbox 与直接发布双写；
* 旧测试中依赖双路径的断言；
* 无调用方的兼容 Wrapper；
* 为旧 API 保留的 Alias；
* 测试专用生产分支。

更新命名，使以下概念明确：

```text
Buffer
Drain
Direct Publish
Durable Outbox Publish
```

不要继续使用含义不清的“commit event transaction”。

---

# 十三、不在本任务范围内

本任务不实现：

```text
Prepared Execution Transaction
Manager Prepare/Apply
Manager Rollback
完整 Execution 原子事务
Runtime Checkpoint Replay
Manager Projection Recovery
Paper Runtime
Live Runtime
Futures Daily MTM
Valuation Barrier
Fee Adjustment
```

但不得让本任务的设计阻碍这些后续工作。

当前 Manager 先修改、Journal 后写入的缺口，应在文档中继续明确记录，不能因 Event 路径修复而声称 Execution 已完全原子化。

---

# 十四、实施顺序

按以下顺序完成：

```text
1. 定位跨平台 Core Tests 失败根因
2. 修复测试基线到本地可通过
3. 重构 Event Publisher 为纯 Buffer
4. 明确 Trade 与 Non-Trade Event 提交分支
5. 让 Trade Event 只进入 Durable Outbox
6. 将 Outbox Publisher 注入 Runtime
7. 完成 Outbox 成功/失败审计字段
8. 增加稳定 Event Identity
9. 补齐 Memory/SQLite Contract Tests
10. 增加 Event 单路径和失败重试测试
11. 增加架构门禁
12. 更新文档
13. 执行完整 CI 等价门禁
```

---

# 十五、验收标准

任务只有满足以下条件才算完成。

## Core Tests

* Ubuntu Core tests 通过；
* Windows Core tests 通过；
* macOS Core tests 通过；
* Product/Integration/Scenario/Conformance 保持通过；
* 不存在 skip、xfail 或平台绕过。

## Event 路径

* Trade Event 在 Journal Commit 前不可见；
* Trade Event 只通过 Outbox Publisher 进入 EventBus；
* Processor 不再直接发布已持久化 Trade Event；
* Non-Trade Event 只直接发布一次；
* Outbox 失败不改变 Trade Commit 状态；
* Outbox 重试不重新执行业务 Mutation；
* 没有 Outbox 与 Event Commit 双发布。

## Outbox

* 成功维护 `published_at`；
* 每次尝试维护 `attempt_count`；
* 失败维护 `last_error`；
* Pending 顺序稳定；
* Memory 和 SQLite 行为一致；
* 重启后 Pending Event 可继续发布；
* Event ID 重试时保持稳定。

## 架构

* Event Buffer 不知道 Journal；
* Journal 不知道 EventBus；
* Outbox Publisher 不修改业务 Manager；
* ExecutionProcessor 只编排；
* Broker Plugin 不接触 Outbox；
* Result 不依赖 Event 是否已经发布；
* 不保留新旧 Event 发布双轨。

---

# 十六、工程门禁

至少执行并记录真实结果：

```text
ruff check .
ruff format --check .

mypy src/onlyalpha
mypy Virtual Broker
mypy Tushare
mypy MiniQMT

Core tests
Virtual Broker tests
Tushare offline tests
MiniQMT offline tests
Integration tests
Scenario tests
Conformance tests
Integration demo tests

Wheel / sdist build
Twine check
Clean install
Entry Point smoke
```

无法执行的真实 Tushare、真实 MiniQMT 或特定平台测试必须明确说明，不得伪造通过。

PR 合并前必须确认 GitHub Actions 中三个 Core Matrix Job 均为绿色。

---

# 十七、最终交付报告

完成后输出：

## 1. Core Tests 根因

列出每个平台的失败测试、根因和修复方式。

## 2. 修改前双发布路径

说明 Event 如何同时进入 Outbox 和 EventBus。

## 3. 新事件模型

说明：

```text
Trade
→ Durable Outbox
→ EventBus

Non-Trade
→ Direct Publisher
→ EventBus
```

## 4. Outbox 交付语义

明确说明采用 at-least-once，以及 Event ID 的幂等职责。

## 5. 删除内容

列出删除的旧方法、双写逻辑、兼容接口和错误测试。

## 6. 测试结果

提供真实命令、通过数量和 CI Matrix 状态。

## 7. 剩余问题

明确记录：

```text
Manager 仍在 Journal 前原地修改
完整 Prepared Transaction 尚未实现
Checkpoint/Replay 尚未实现
```

不得将本任务描述为完成了全部 Execution 原子事务。

---

# 最终目标

完成后，Trade Event 路径必须严格为：

```text
Trade Processing
→ Committed Fact
→ Journal Append(Fact + Outbox)
→ Outbox Publisher
→ EventBus
```

非 Trade Event 路径必须严格为：

```text
Non-Trade Processing
→ Event Buffer Drain
→ Direct Event Publisher
→ EventBus
```

保证一个 Event 只有一条主动发布路径，恢复跨平台绿色测试基线，并为后续 Prepared Transaction 和 Runtime Recovery 保留清晰边界。
