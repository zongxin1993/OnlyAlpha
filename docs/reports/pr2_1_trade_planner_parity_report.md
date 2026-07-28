# PR2.1 Generic T0 Cash Pure Planner 真实性与等价性报告

## 结论范围

本报告只证明 `GENERIC_T0_CASH / LIMIT BUY OPEN LONG NETTING / 单 Account、Cluster、Currency / 无 Margin / 整单成交`
的纯规划 Contract 已收口，可作为 PR3 Real Manager Projection Targets 的输入。它不声称 Projection Target、Commit Coordinator、
ExecutionProcessor 切换、Runtime Replay 或生产主链的 Manager-before-Journal 问题已经完成。

## 修改前真实基线审计

Parity harness 使用两个独立的真实 Runtime，并实际使用 `OnlyOrderManager`/`OnlyOrderUpdateProcessor`、
`OnlyPositionManager`、`OnlyPositionAllocationManager`、`OnlySettlementManager`、`OnlyFeeManager`、`OnlyAccountManager` 及其
cash reservation manager、`OnlyStrategyLedgerManager` 及其 cash reservation manager、`OnlyRiskService` 及 risk reservation
manager，以及正式 `OnlyExecutionProcessor`。输入是正式 Broker Trade Update、Market Trade Instruction、Fee Instruction 和真实
Manager Snapshot；Planner Context 由 converter 正向构造，没有从 Projection fixture 反推 before authority。

Legacy 调用顺序为：

```text
Order → Position → Allocation → Settlement → Fee → Account cash flow
→ Account valuation → Strategy Ledger accounting → Ledger valuation
→ Account/Strategy reservation consume + release → Risk consume
→ invariant → event commit → committed fact journal
```

Planner 调用顺序为：

```text
validate → planned trade → Order → Position → Allocation → Settlement → Fee
→ Account → Strategy Ledger → Account cash reservation
→ Strategy cash reservation → Risk reservation → Risk → Valuation
→ fact draft → projection finalize → precondition → durable event
→ prepared-transaction invariant
```

Legacy 路径还写入 order/position/allocation/account/ledger/risk 的内部索引与 event sequence、Settlement/Fee record sequence、
broker dedup/source sequence、committed journal 和 event buffer；失败时可能写 reconciliation。Planner 对这些对象均无引用。

## 完整状态等价

以下四个场景逐字段比较 12 项 after authority，均要求完整对象相等，而非字段白名单：

1. 新 Position/Allocation，零费用；
2. 新 Position/Allocation，非零费用；
3. fill price 低于 limit price，存在超额 Cash Reservation；
4. 已有 Position/Allocation 后再次增仓，且 fill price 与 valuation mark 不同。

比较覆盖 Order、Position、Allocation、Settlement、Fee、Account、Strategy Ledger、Account/Strategy Cash Reservation、Risk
Reservation、Risk 与 Valuation 的所有正式字段，包括 ID/cycle、Decimal 金额数量、状态、版本、时间、record、cash/fee entry、
quality flag 和 sequence。已有实体场景同时证明估值使用 Closed Bar mark，不错误使用 fill price。

## Version、Timestamp、Cycle 与 Sequence

| Authority | 最终版本语义 | 时间语义 |
| --- | --- | --- |
| Order | `+1` | `updated_at=ts_init`，`filled_at=ts_event` |
| Position / Allocation | 新建 `1`，已有 `+1` | 新建/open 与 trade authority 使用 `ts_event` |
| Settlement / Fee | 新建 `1`，已有 `+1` | record 使用成交时间；ID 使用冻结 head `+1` |
| Account | `+4` | trade/处理时间为 `ts_init`，valuation time 为 `ts_init` |
| Strategy Ledger | `+4` | `updated_at=ts_init`，valuation time 为 `ts_event` |
| Account Cash Reservation | `+2` | `updated_at=ts_init` |
| Strategy Cash Reservation | `+2` | `updated_at=ts_init` |
| Risk Reservation / Risk | `+1` | `updated_at`/`ts_init=trade.ts_init`，风险事实 `ts_event=trade.ts_event` |
| Valuation | `+1` | valuation time 为 `ts_init` |

Position/Allocation 新 ID 由 Manager-owned next cycle 冻结到 creation authority；Reducer 不分配 ID。Settlement 和 Fee record
使用各自 Manager 全局 record sequence head 加一，已有记录场景不会退回局部长度推导。

## Reservation、Risk 与 Account/Ledger 语义

整单成交时 Account 与 Strategy Cash Reservation 都先消费实际 notional 加权威 fee，再释放 limit 预留的剩余部分；即使剩余为
零也保留 release mutation，最终状态/阶段均为 `RELEASED`。Risk Reservation 消费成交数量和 gross notional，完整成交后为
`CONSUMED`。

`OnlyRiskExecutionState` 是 Runtime/Cluster/Account 聚合风险快照：成交完成减少 active order count、cluster active order count、
reserved quantity/notional，并相应恢复 remaining order notional；它不是持仓风险或单订单剩余风险。单订单权威属于 Risk
Reservation。Account 与 Strategy Ledger 的 equity 相等只在本 Planner 的单 Cluster 业务范围内验证，没有固化到通用 Contract。

## Legacy Event 与 Durable Event 映射

| Legacy | Durable | 说明 |
| --- | --- | --- |
| `ORDER_FILLED` | `ORDER_FILLED` | Order scope/terminal payload |
| `POSITION_OPENED/INCREASED` | 同名 | Position scope/terminal payload |
| 无独立事件 | `SETTLEMENT_UPDATED` | 显式 durable settlement state fact |
| 无独立事件 | `FEE_RECORDED`（非零费用） | 显式 durable fee fact |
| `ACCOUNT_TRADE_APPLIED` / `ACCOUNT_VALUED` | 同名 | 原中间事件映射到原子事务 terminal authority |
| `STRATEGY_TRADE_APPLIED` / `STRATEGY_VALUATION_UPDATED` | 同名 | Cluster/ledger scope |
| `ACCOUNT_RESERVATION_CONSUMED/RELEASED` | `ACCOUNT_CASH_RESERVATION_CONSUMED/RELEASED` | 规范命名 |
| `STRATEGY_CASH_RESERVATION_CONSUMED/RELEASED` | 同名 | consume/release 顺序保留 |
| 无独立事件 | `RISK_STATE_UPDATED` | 显式 durable aggregate risk fact |
| `EXECUTION_UPDATE_APPLIED` | Prepared Transaction + committed fact envelope | 处理完成标记，不重复为业务 Event |

映射测试逐场景比较 Event type、Runtime/Cluster scope、Broker Update metadata、`ts_event`、terminal payload 和业务顺序。
Settlement/Fee/Risk 是新增的单一显式事实，不重复既有业务语义。Legacy 随机 Event ID 不参与相等比较；Planner 的 ID、count、
sequence 与 payload 对同一 Context 完全确定。

## 修复的真实差异

- Cash Reservation 原 reducer 只在有余量时 release，现与 Manager 一致为整单成交后总是 consume + release，版本 `+2`。
- Account/Strategy Ledger 原 reducer 低估一次成交中的多步版本推进，现最终版本均与 Manager `+4` 一致。
- Risk State 原 contract 混入订单/品种风险字段，现与正式 Cluster aggregate `OnlyRiskSnapshot` 对齐；订单风险留在 Reservation。
- 估值原使用 fill price，现由 Context 明确注入 valuation mark，已有仓位且价格不同的场景与 Manager 一致。
- Durable Reservation Event 原按 Projection component 排序，现保留 Legacy 的跨组件 consume/release 业务顺序。
- Legacy ExecutionProcessor processing event 原只设置 `ts_init_ns` 而遗漏对应 `ts_init`，在双时间不同时违反 Event envelope；现显式安装两者。
- 测试 Context 原来自 Prepared fixture，现全部由真实 Manager Snapshot 和 converter 正向建立。

## 故障矩阵与无副作用证据

18 个 `OnlyTradeExecutionPlanningErrorCode` 均有精确 code 测试。故障注入覆盖 19 个阶段：Context validation、planned trade、12 个
Reducer、fact draft、projection finalization、precondition、event construction、prepared-transaction invariant。每个失败都验证：

```text
No Prepared Transaction
No partial Projection/Event escape
No Manager/Repository mutation
No Store/Journal write
No EventBus/Event buffer publish
No dedup/sequence/audit/reconciliation mutation
```

真实 authority digest 在 Planner 前后比较所有 Manager snapshot、reservation、cycle/index、repository、record、dedup、source/event
sequence、journal/outbox、event buffer/bus、audit 和 reconciliation，并使用稳定排序。四个正常场景以及所有 error/fault case 均保持一致。

每个 Reducer 还独立验证 Projection identity、expected/result version、state/payload hash、event intent、domain delta、输入不可变、
失败原子性和 100 次 fresh-instance 字节级确定性。Planner 的 100 次压力测试额外覆盖 Mapping 插入顺序和 `prepared_at` 语义。

## 当前不支持与 PR3 readiness

仍不支持 SELL、CLOSE、Partial Fill、多 Fill/最低佣金累计、Short、Hedging、Margin、Futures、Daily MTM、Margin Call、多 Account、
多 Cluster 共用 Account、多 Currency、FX 和 Corporate Action。这些边界继续 fail closed。

在上述有限范围内，PR3 所需的每项 Projection 已具有完整 before/after、entity key、expected/result version、expected/result state
hash、payload hash、稳定 sequence 与 Precondition；成交公式、Reservation、Risk、Version、时间和 Event 语义无需在 PR3 重释。
是否标记 `GO` 仍以本变更最终质量门禁与构建/安装 smoke 全部通过为条件。

## 最终验收记录

最终源码上的结果如下：

- `uv lock --check`、`uv sync --frozen --all-packages --all-groups`、版本同步检查、`git diff --check`：通过；
- Ruff check/format（`src tests examples packages scripts`）：通过，714 files formatted；
- Core mypy strict：380 source files 无错误；Tushare 15、MiniQMT 25 source files 无错误；
- Prompt 八组定向测试：分别 2、2、3、12、1、37、16、1 项通过；
- execution 152、architecture 25、integration 74、scenario 10 项通过；
- 当前仓库不存在 Prompt 写出的 `tests/conformance`，原命令按要求实际执行并以 path not found 退出；事实目录
  `tests/domain_conformance` 16 项和 `tests/market/test_conformance_runtime.py` 1 项全部通过，因此该路径命名差异不阻塞；
- Core non-external 总回归：585 项通过；
- Virtual Broker 11 项通过；Tushare 16 项通过、1 项外部测试按 marker 排除；MiniQMT 10 项通过、1 项既有 skip；
- 四个正式 distribution 的 wheel/sdist 构建完成，Twine 全部返回 PASSED；
- 全新 Python 3.12.12 环境从最终 wheel 安装四个 distribution，四个模块和七个正式 Entry Point 全部加载成功；
- 干净环境运行 Generic T0 Scenario，`FILLED` 与 `PROFILE_RECORDED` 两项断言均为 `PASSED`。

Twine 对 Tushare/MiniQMT 的空 README 产生 `long_description`/`long_description_content_type` warning，但检查退出码为 0，wheel
安装、模块导入和 Entry Point 加载均成功；这是既有插件 metadata 文档缺口，不降低或改写为“无 warning”。uv 还报告本机 managed
Python registry 中名为 `data` 的 malformed entry warning，实际选用 CPython 3.12.12 并成功建环境，不影响仓库制品。

按用户指示没有执行 pre-commit。真实网络、Tushare Token 和本地 QMT 外部测试未执行；它们不属于本 PR2.1 纯 Planner 的默认验收，
也未被声称通过。最终可进入 Real Manager Projection Targets：`GO`。
