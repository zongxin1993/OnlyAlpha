# Committed Execution Journal 实施报告

- 状态：功能实现完成；最终门禁受限项按真实环境记录，不降低验收口径
- 日期：2026-07-22
- 设计决策：ADR 0033
- 修改前审计：`docs/reports/committed_execution_pre_implementation_audit.md`

## 1. 修改前问题

旧 `OnlyAppliedTradeFact` 主要复制 Broker Fill，只保存 Runtime/Gateway/Account/Order/Trade/Update 身份、source
sequence 和原始 Fill。它没有固化本地事务实际接受的 Position Scope、费用、合约乘数、结算、保证金、归属和
Manager 增量，因而只能证明“收到并处理了外部回报”，不能证明“Runtime 已完整提交了什么”。Collector 还需查询
最终 Order 状态并填入错误的零佣金、零费用、零滑点，且用 `price * quantity` 遗漏合约乘数。这些行为使 Result、
Analytics 和 Artifact 不是本地成交权威的确定性投影。

## 2. 新架构

```text
Broker Update
→ ExecutionProcessor 本地事务
→ invariant 与 Event commit
→ OnlyCommittedExecutionBuilder
→ Runtime-owned OnlyCommittedExecutionJournal
→ Result Projection
→ Analytics / Artifact / Report / Scenario / Conformance
```

每个 Runtime 独占一个 Journal。Processor 是生产代码中的唯一写入者；插件只能发布标准 Broker Update，不能构造
或写入本地提交事实。Collector 直接投影 Journal，不调用 Broker `query_trades()`，也不查询可变 Manager 来解释某笔
成交。Analytics 和 Artifact 只消费标准 Result，不重新运行 Fee Resolver 或 Market Rule Engine。

## 3. 领域模型与字段权威来源

`OnlyCommittedExecutionFact` 是 `frozen=True, slots=True, kw_only=True` 的 `OnlyDomainModel`，schema version 为 2。
下表完整列出字段；同一行字段拥有相同权威来源。

| 字段 | 权威来源 |
| --- | --- |
| `execution_id` | Runtime/Gateway/Account/Trade/Venue Trade 复合身份的稳定哈希 |
| `execution_sequence` | Journal 在成功 append 时分配的 Runtime 内连续序号 |
| `trade_id`, `venue_trade_id` | 标准 Broker Fill |
| `order_id`, `client_order_id`, `request_id` | 本次 `OnlyOrderMutationResult.snapshot` |
| `broker_update_id`, `runtime_id`, `gateway_id`, `account_id` | 标准 `OnlyBrokerTradeUpdate` |
| `cluster_id` | 提交后的 Order snapshot；在提交时固化 |
| `strategy_id` | Runtime 注入的 Cluster→Strategy 归属解析；在提交时固化 |
| `instrument_id` | 提交后的 Order snapshot |
| `venue_id` | 本次已解析 `OnlyTradeApplicationInstruction.compiled_identity` |
| `source_sequence` | Broker Update |
| `processing_sequence` | ExecutionProcessor 本次处理序号 |
| `correlation_id`, `causation_id` | Broker Update 因果信息 |
| `external_event_id` | Broker Fill 外部事件身份 |
| `ts_event`, `ts_init` | Broker Update/Fill 标准 UTC 时间 |
| `ts_committed` | Runtime Clock 在事实构造时读取的 UTC 提交时间 |
| `trading_day` | 本次已解析 Market Rule/Calendar 交易日，不由 UTC date 推导 |
| `order_side`, `order_type`, `offset` | 提交后的 Order snapshot |
| `position_side`, `position_effect`, `position_mode` | Processor 本次已解析 `OnlyExecutionPositionScope` |
| `liquidity_side` | Broker Fill |
| `fill_quantity`, `fill_price` | Broker Fill |
| `cumulative_filled_quantity`, `remaining_quantity`, `order_status_after` | 本次 Order mutation 后 snapshot |
| `currency` | 本次权威 `OnlyFeeInstruction/OnlyFeeBreakdown` |
| `contract_multiplier` | 本次已应用 `OnlyPositionTrade` |
| `gross_notional` | `fill_price * fill_quantity * contract_multiplier`，按币种精度量化 |
| `settled_notional` | 已应用 Trade cash instruction 是否结算 notional 的结果 |
| `authoritative_fee_total` | Runtime 唯一 Fee Resolver 产生的 `OnlyFeeBreakdown.total` |
| `market_fee`, `broker_fee` | 权威 Fee components 按 authority 分类求和 |
| `tax`, `commission`, `other_fee` | 权威 Fee components 按 fee type 分类；other 为未分类余额 |
| `reported_broker_fee`, `fee_reporting_mode` | Broker Fill 原始报告；与 Runtime 权威费用分离 |
| `reference_price` | Broker/Matching 边界提供的原始成交参考价；缺失时保持 `None` |
| `slippage` | 参考价存在时按方向、数量、乘数计算的精确金额；未知时为 `None` |
| `realized_pnl_delta` | 本次 Position mutation 的已实现 PnL 增量 |
| `cash_delta` | 本次已应用 Account mutation 的 cash 增量 |
| `fee_instruction_id`, `fee_authority`, `fee_status` | 本次已执行 `OnlyFeeInstruction` 与 components |
| `market_fee_schedule_ids`, `market_fee_schedule_versions` | 非 Broker 权威 Fee components 中固化的 schedule 身份 |
| `broker_fee_schedule_ids`, `broker_fee_schedule_versions` | Broker 权威 Fee components 中固化的 schedule 身份 |
| `fee_breakdown` | Runtime 唯一 Fee Resolver 本次产生的完整不可变 breakdown |
| `market_profile_id`, `market_profile_version` | 本次已应用 compiled market identity |
| `compiled_rule_fingerprint`, `reference_fingerprint` | 本次已应用 compiled/reference identity |
| `trade_instruction_id` | 本次已应用 Trade instruction 的稳定身份 |
| `settlement_instruction_id` | 本次已应用 Settlement instruction 的稳定身份 |
| `settlement_status` | 本次 Settlement instruction/record 的实际状态 |
| `asset_available_on`, `cash_available_on`, `legal_settlement_date` | 本次已应用 Settlement instruction |
| `margin_instruction_id` | 本次 Margin instruction 的稳定身份；无保证金指令时为 `None` |
| `margin_action`, `margin_currency`, `margin_amount` | 本次已应用 Margin instruction；不适用时为 `None` |
| `reserved_margin_delta`, `occupied_margin_delta`, `released_margin_delta` | 本次 Margin record 和事务前 occupied 值计算的实际增量 |
| `maintenance_margin_after` | 本次 Margin record 的维护保证金后值 |
| `position_quantity_delta`, `position_realized_pnl_delta` | 本次 Position mutation before/after |
| `allocation_quantity_delta` | 本次 Allocation before/after |
| `account_cash_delta`, `account_fee_delta`, `account_realized_pnl_delta` | 本次 Account mutation before/after |
| `ledger_cash_delta`, `ledger_fee_delta`, `ledger_realized_pnl_delta` | 本次 Strategy Ledger mutation |

Fact 只包含本次提交事实及其增量，不保存 Manager、Resolver、Rule Engine、Profile 对象或完整可变状态快照。

## 4. 事务边界与失败策略

准确顺序是：应用 Order/Position/Allocation/Settlement/Margin/Fee/Account/Ledger/Reservation/Risk 状态，检查不变量，
提交事件，由 builder 使用事务局部结果构造 Fact，append Journal，最后才返回 `APPLIED`。重复 Update 或 Trade 由
Runtime/Gateway 作用域幂等键拒绝，且不推进 execution sequence。

Event commit 失败不产生 Fact。Fact 构造或 Journal append 失败不得返回 `APPLIED`；Processor 记录 dependency
failure，标记受影响 scope 进入 reconciliation，并发布失败/协调审计。当前内存架构无法回滚 event commit 后的所有
Manager mutation，因此该晚期失败是明确的 partial-mutation reconciliation 边界，绝不吞错或伪装原子成功。

## 5. 删除内容

- 删除 `OnlyAppliedTradeFact` 与 `OnlyAppliedTradeJournal` 实现和公共导出。
- 删除 `OnlyRuntime.applied_trade_journal`、Runtime services 旧字段和所有旧构造参数。
- 删除旧测试 `tests/execution/test_applied_trade_journal.py`。
- 删除 Collector 的 Order 查询补数路径、零费用/零滑点兼容值和不含 multiplier 的 turnover 计算。
- 不保留 Alias、Wrapper、deprecated re-export、双写、schema 兼容分支或旧 fingerprint 适配。
- ADR 0032 的旧名仅作为明确标记的 Historical 事实保留；修改前审计同样只记录历史基线。

## 6. 调用方迁移

- 生产：ExecutionProcessor、Runtime services、Backtest Runtime/Run Plan/Result、Engine cluster projection、Collector、
  Result records、Analytics、Artifact Writer、Position/Reservation/Risk scope，以及 Virtual Broker reference price 边界。
- 测试：Journal 单元/序列化/幂等/隔离、Processor 完整事务与失败、LONG/SHORT scope、费用组合与一致性、Analytics、
  Artifact、架构 AST 门禁、partial fill integration demo 和 Generic Futures 产品场景。
- 示例：新增 `examples/committed_execution_report.py`，只使用 OnlyEngine/公开配置/标准 Result。
- 文档：README、AGENTS、HANDOFF、NEXT、architecture、runtime、execution processor、results framework、virtual broker、
  roadmap、Virtual Broker plugin README、ADR 0032 historical 标记、ADR 0033 和两份实施报告。

## 7. 验证结果

以下结果均为本工作树实际执行结果：

- Core：`uv run pytest tests -q` → **420 passed**。
- Integration：定向集 → **72 passed**；Scenario/Conformance 定向集 → **46 passed**；integration demo → **35 PASS**。
- 插件离线测试：Virtual Broker **11 passed**；Tushare **16 passed, 1 external skipped**；MiniQMT
  **10 passed, 1 local-QMT skipped**。
- Ruff：`ruff check src tests examples packages scripts` 通过；format check → **661 files already formatted**。
- Mypy strict：Core **355 source files**、Virtual Broker **11**、Tushare **15**、MiniQMT **25**，均通过。
- 版本/锁：`version_sync.py check` 通过（0.2.7）；`uv lock --check` 通过。
- Git：旧 API 全仓搜索在生产/测试/示例为零；`git diff --check` 通过。
- Build：SHORT 修复后的 Core、Virtual Broker、Tushare、MiniQMT 四个最终 distribution 的 wheel/sdist 均成功，产物位于
  `user_data/committed-execution-final-build/`。
- Metadata：四个 distribution 的 Twine check 通过；Tushare/MiniQMT 保留既有 missing long description warning。
- Install：SHORT 修复前，独立 Python 3.12 环境完成 Core-only wheel 安装与 console entry point smoke；另一干净环境
  完成四 wheel 安装、模块导入和全部要求 entry point 加载。最终 SHORT 修复后的 wheel 已重新 build 和 Twine check；
  新建最终 smoke 环境时 uv cache 仍受沙箱写权限限制，因此不把旧安装证据描述为“最终 wheel 已重新安装”。
- Pre-commit：SHORT 根因修复前，对本任务文件执行 scoped hooks 完整通过。修复后再次运行 scoped hooks 时，所需
  uv cache 沙箱授权未获批准；直接调用本地 pre-commit 又因用户目录 cache 数据库只读而未能启动。因此最终状态不记为
  “pre-commit 已通过”。修复后的等价 Ruff、format、四范围 Mypy、version sync、Core/插件测试与 `git diff --check`
  均已独立通过。`--all-files` 曾因仓库既有 CRLF checkout 与 hook 强制 LF 的全仓基线冲突改写无关文件；已恢复全部
  825 个无关改写，未把该次首轮结果伪报为通过。

未执行：需要真实 Token/网络的 Tushare external test、需要本地 Windows QMT 的真实 MiniQMT test，以及
Linux/macOS CI。它们不计为通过。

## 8. 剩余问题

### 本任务已完成的问题

Committed Fact/Journal 权威边界、唯一写入者、幂等与序列、完整 Result 投影、LONG/SHORT 与 OPEN/CLOSE scope、
multiplier-aware notional、单笔 authoritative fee、unknown slippage、结算/保证金证据、事务增量、失败协调、
Artifact schema v2、公开示例和无兼容删除均已实现并验证。

最低佣金的**跨部分成交累计**尚未实现；当前单笔/单次 fill minimum 正确，跨 fill 不能伪称通过。这是已明确记录的
剩余费用聚合缺口。Generic Futures 产品纵切面现已同时覆盖 `BUY OPEN LONG → SELL CLOSE_TODAY LONG` 与
`SELL OPEN SHORT → BUY CLOSE_TODAY SHORT`，包括 Margin `OCCUPY → RELEASE`。该场景还修复了 Strategy Ledger 将
所有 BUY 错当成开仓现金 Reservation 的根因。

### 后续 Equity Timeline 问题

本次只提供成交级增量与现有结果投影，没有重建逐时权益估值、Corporate Action 或完整估值时间线。

### Multi-Cluster Aggregate 问题

Fact 已固化 Cluster/Strategy 归属，Engine 可按 Cluster 投影；跨 Cluster 组合聚合、归因与冲突策略仍是后续能力。

### Futures Daily MTM 问题

本次实现逐成交 multiplier、margin action 和 realized PnL 事实；期货逐日盯市、结算价重估与日终权益迁移未实现。

### Live Fee Reconciliation 问题

Broker reported fee 与 Runtime authoritative fee 已分离保存，但迟到 statement、Adjustment 对 Account/Ledger/Fee
facts 的事务应用及结果时间线尚未产品化。

### Paper / Live Runtime 问题

Committed Execution 的领域与 Journal 边界可复用，但本次只验证 Backtest 产品纵切面；Paper/Live 生命周期、恢复、
持久化和外部同步不在本任务内，也未宣称完成。
