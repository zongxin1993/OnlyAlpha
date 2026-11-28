# Runtime 恢复与提交事实

本页描述当前恢复契约，落实 [ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)；值接口见
[有限作业契约](job-execution-contract.md) 和 [Rust Runtime 状态、持久化与恢复](rust-runtime-persistence.md)。原
Participant Registry、Checkpoint envelope schema v3、`runtime.sqlite3`、文件 journal、durable Outbox 和逐 Bar checkpoint
恢复均已退役，不保留兼容读取或回退。

恢复只有两种，按 runtime 类型区分，不互相替代：

| runtime | 权威来源 | 进程丢失后的语义 |
| --- | --- | --- |
| Research / Backtest（有限作业） | 冻结输入与原 Run | 丢弃内存工作，按同一冻结输入确定性重算 |
| SIM / LIVE（连续交易） | PostgreSQL 正式交易事实 | 恢复 typed owner，外部对账后继续 |

## 有限作业：按冻结输入重算

有限作业在内存中运行，不保存逐 Bar checkpoint，也不存在继续读取持久前缀的生产入口。原 Run、精确程序与参数、初始配置、
Kernel 工件、Market Data 切片和 Result Plan 在准入时冻结；发布前的工作可以丢失。

恢复顺序：

1. 先观察原发布事务和未知提交，确认没有已发布的正式结果；
2. 取得新的有效 Claim 后，在同一 Run 下新建 Attempt；
3. 按冻结输入从头重算，得到与原执行一致的结果和指纹；
4. 通过正式原子发布提交终态结果。

重算不是“回滚”：原 Attempt 的事实保留，发布只发生一次。内存会话 API 仅提供 `Session::new`、`apply`、`acknowledge`、
`state` 等当前会话操作，不提供 `open` 原持久状态并续接 Bar 的接口。

## SIM / LIVE：从正式事实恢复

### 绑定

`TradingBinding` 由 `RunConfiguration` 与 Kernel 工件指纹构成，要求 `runtime_kind` 为 `SIM` 或 `LIVE`：

- `key` 绑定 engine、runtime、generation；
- `fingerprint` 绑定 stream key、完整配置指纹和 Kernel 工件指纹。

绑定是事实身份的一部分。backend 适配器 `TradingFactRepository` 实现 `onlyalpha_runtime::durability::DurableFactPort`：
`commit(&PreparedTradingFacts)` 原子写入事实与必要索引并返回 `DurableCommitReceipt`，`load_recovery(&TradingBinding)`
在同一快照内读出绑定、水位与全部记录。

同身份同 payload 幂等；同身份不同 authority 或前驱不符拒绝。receipt 只证明该次提交的读回结果，不是派单权限。

### 提交、投影与可见性

```text
prepare → commit（committed / unready）→ 投影 → ready → 业务查询可见
```

- 已提交未投影的记录只能继续原计划投影，不得重新规划或对外派单；
- Projection Ready 是业务查询与继续派单的门禁，`records()` 只用于 Admin/Recovery 读取；
- 投影失败保留已完成前缀，由 Coordinator 前向恢复，不跨 Manager 回滚。

### 恢复校验（fail closed）

`RecoveryFacts::from_records(binding, stored_binding, expected_head, records)` 要求仓储在同一快照内读出全部内容，逐项校验：

| 条件 | 结果 |
| --- | --- |
| 绑定指纹不符，或 `expected_head` 与记录数不一致 | `TRADING_HISTORY_INCOMPLETE` |
| 记录的 Prepared 计划与重新推导结果不一致；或未 Ready 的行不是最后一行 | `TRADING_HISTORY_CONFLICT` |
| 整体对账状态不是 `MATCHED` | `TRADING_RECONCILIATION_MISMATCH` |
| 存在未投影尾行时继续 prepare | `TRADING_PROJECTION_PENDING` |
| 同一 `input_id` 的输入体不同 | `TRADING_INPUT_CONFLICT` |
| 提交读回的计划与绑定不符 | `TRADING_COMMIT_CONFLICT` |
| 绑定本身不合法 | `TRADING_BINDING_INVALID` |
| 持久源不可读 | `TRADING_FACTS_UNAVAILABLE` |
| 提交状态未知 | `TRADING_COMMIT_UNKNOWN` |

只允许一个未投影尾行；它之后的因果事实必须仍可从该行推导。校验期间使用的 `Replay` 是只读证明重放，不能提交新权威，
也不能发布外部事件。

### SIM 恢复入口

产品宿主恢复 SIM 时须先校验绑定为 `SIM`，再读取原事实。原服务入口已退役。

- 尾行已 Ready：直接返回恢复结果；
- 尾行未 Ready：在原前缀上重新安装投影、重新读回，要求同一 Prepared 行变为 Ready 且前缀不变，否则
  `SIM_RECOVERY_PROJECTION_CONFLICT`。

提交状态未知时换连接按同一绑定重新观察原场所事实，不盲目重试外部指令；持久源不可用时停止工作、保留观察和恢复能力，
不增加风险。

## 状态机与投影契约

`docs/execution_projection_contract.md` 描述的 Projection Ready 门禁仍然有效：committed 事实按原方向、原 scope 投影到
Manager，Ready 后才进入业务查询和继续派单。恢复不重新选择成本或经济结论——Attributed Close 的结论已冻结在
Projection Before/After、Committed Fact、authority hash 与 payload hash 中，恢复只验证数量、精确累计成本聚合和关联 scope，
不重跑 Fee、Settlement 或 Margin 计算。

## Forward Recovery 边界

- committed 事实不删除、不跨 Manager 回滚、不按当前规则重算；
- 失败投影不跳过；
- schema、身份、配置或指纹不兼容时 fail closed，不做静默迁移或内存回退；
- Outbox、exactly-once 投递、分布式 checkpoint 和远程 Store 都不在当前实现内；外部成交事实归属交易场所，OnlyAlpha
  负责意图、风控、对账和可恢复状态。

## 验证

库单元测试按[工程指南](../AGENTS.md)在 Mac 主机运行。SIM 正式恢复、PostgreSQL 发布、结果读回与吞吐仍须由实际产品宿主分别验证。原组合基准与 OpenAPI 服务测试现已退役。
