# Risk 组件

Risk Evaluation Context 接入只读 Strategy Ledger Risk View。Ledger 不是 ACTIVE（包括 RECONCILING、ERROR、SUSPENDED、
CLOSED）时默认 Fail Closed；View 提供 Equity、Cash Available/Reserved、Net/Daily PnL 和 Drawdown。

## 1. 职责与边界

每个 Trading Runtime 独占一个 `OnlyRiskService`。它拥有 Rule Pipeline、Cluster Risk Profile 绑定、Risk State、
不可变 Snapshot、Reservation、Kill Switch 状态和审计记录。Cluster 只得到 `ctx.risk` 的只读 Snapshot View，
订单仍只能经 `ctx.orders.submit()` 提交。

Research Runtime 不拥有交易 Risk 或 Reservation authority；研究过滤与统计约束不得冒充 Pre-Trade Risk。

本阶段不实现账户、持仓、撮合、强平、自动撤单、真实券商 Risk 或策略 `on_risk_xxx` 回调。Account 和 Position
仅提供只读 Port 与明确的 unavailable 占位，绝不伪造无限资金或充足持仓。

## 2. 三阶段模型

1. Pre-Decision State Update：每次 `on_bar` 前，Runtime 用已完成的 MarketData Snapshot 同步刷新只读
   `OnlyRiskSnapshot`；它不是最终下单审批。
2. Pre-Trade Evaluation：每次 submit 都同步执行最终 Pipeline，发生在创建 `OnlyOrder` 和调用 Execution 前。
3. Post-Order Reservation：ACCEPT 后立即创建 Order 和 Risk Reservation，随后才发布 Order Created 并调用
   Execution；同一回调内的下一笔订单会看到最新预占。

REJECT 与 ERROR 都不创建 Order、不创建 Reservation、不调用 Execution。ERROR 表示规则执行或必需数据读取
异常，默认 Fail Closed；REJECT 表示规则正常执行并判定不允许。

## 3. Rule、Scope、Mode 与 Pipeline

`OnlyRiskRule` 接收 immutable `OnlyOrderRequest` 和只读 `OnlyRiskEvaluationContext`，返回
`OnlyRiskDecision`。Scope 固定为 SYSTEM、RUNTIME、ACCOUNT、INSTRUMENT、CLUSTER；Pipeline 先按该层级排序，
同层再按显式 `order` 和稳定 `rule_id` 排序。业务顺序不依赖注册顺序或 EventBus priority。

ENFORCING 的首个拒绝立即停止。OBSERVING 拒绝转换成 Observation 并继续；任何规则异常转换成结构化 ERROR
并停止。Rule 无权修改 Order、Cache、Position、Account、Reservation 或调用 Gateway。

## 4. Profile 与 Mandatory Rules

Cluster 通过配置绑定 `OnlyRiskProfile`。内建 factory/registry 只接受显式注册且以 `Only` 开头的规则类型；
重复 RuleId、非法配置、替换或禁用 Mandatory Rule 都会在 Cluster 启动前失败。

Mandatory System Rules 始终为 ENFORCING：Runtime Scope、Cluster Scope、Instrument 存在、Instrument 可交易、
OrderType、基础 Price、基础 Quantity 和 Kill Switch。Cluster 不能删除、替换或降级它们。默认 Instrument Rules
校验 tick、step、最小/最大数量、最小名义金额、交易时段和涨跌停；可配置规则覆盖最大活动订单数、单笔数量、
单笔/累计预占名义金额以及 Cluster 的 Account/Instrument 权限。

配置示例：

```python
OnlyClusterConfig(
    "cluster-a",
    values={
        "risk_profile": {
            "profile_id": "conservative",
            "rules": [{
                "type": "OnlyMaxOrderNotionalRiskRule",
                "order": 100,
                "config": {
                    "maximum": {"amount": "50000.00", "currency": "CNY", "precision": 2}
                },
            }],
        },
        "allowed_instrument_ids": ["600000.XSHG"],
    },
)
```

## 5. Decision、Context、Snapshot 与 Reservation

Decision 只有 ACCEPT、REJECT、ERROR，包含已执行 RuleId、结构化 rejection/error 和 observations。Risk Context
携带 Runtime/Cluster/Account Scope、业务时间和只读 Instrument、MarketRule、Order、Reservation、Permission、
Account、Position Port。跨 Runtime Context 被拒绝。

Risk Context 还可携带当前 submit cycle 的 transient `order_planning_price` 及 execution-reference identity。价格优先级固定为 request
price、explicit planning price、最后才是 legacy non-reference Bar fallback。启用 realtime reference 的 risk-increasing MARKET 请求在
reference admission 成功后必须使用 explicit planning price；price-dependent rejection 的既有 details 同时保留 planning price、snapshot
fingerprint、market update id 与 Execution Profile fingerprint，且不把 realtime Trade 复制成第二份 Risk state。

Snapshot 是带版本、时间、Scope、活动订单数、预占金额/数量、剩余额度、拒绝计数、Kill Switch 和数据质量标记
的 frozen 值。`ctx.risk` 不暴露 evaluate、reserve、release、disable rule、Cache 或 Gateway 能力。

Reservation 由 Trading Runtime 单写管理，ID 和遍历顺序确定；创建按 OrderId 幂等，释放校验 Runtime/Cluster Scope 且
幂等。订单 Cancelled、Rejected、Failed、Expired、Execution 拒收或 Cluster 停止时释放。有效 Fill 按数量和实际
名义金额分段消费，只有 Order 判定的最终 Fill 才进入 `CONSUMED` 并减少 Active Order Count。

买单现金 Reservation 的 estimated fee 来自与成交共用的 Runtime `OnlyFeeResolver`；Risk 不读取 Schedule、不实现费用公式。
无法解释且超过阈值的外部费用差异必须进入 Reconciliation/Trading Block 状态，不能用零费用或 `OTHER` 项目强行抹平。

## 6. Kill Switch、Event 与审计

Kill Switch 是 Trading Runtime 管理能力，可作用于 Runtime、Cluster 或 Account；Cluster 只看到 Snapshot 中的布尔值。
Risk Accepted/Rejected/RuleFailed、Reservation Created/Released 和 State Updated 都是判定或状态成功变化后的事实。
Event 只用于审计、监控和未来扩展，不驱动 Rule 执行，也没有策略 Risk 回调。

每次新的 intent 判定记录 Scope、Profile、Decision 和纳秒时间。相同 RequestId 与相同 intent 返回缓存判定；
相同 RequestId 对应不同 intent 被拒绝，保证重放稳定。

## 7. 隔离、Demo 与限制

Risk State、Profile、Permission、Reservation、Kill Switch、审计和序列均按 Trading Runtime 隔离；Cluster 之间的 Profile、
Snapshot 和权限也隔离。对应 tests 覆盖 ACCEPT、非法 tick、额度拒绝、不同 Profile、连续预占、
Fail Closed 和 Snapshot。

已知限制：当前正式 Backtest 已接入 Position/Allocation/Account 只读数据源，并把 Risk Reservation 纳入 checkpoint 与
forward recovery。Market Order 在需要名义金额规则且缺少可靠价格时仍 Fail Closed；目标 Sim/Live 的完整 realtime
装配、Live Runtime 外部回报串行化及真实券商适配尚未实现。未来若增加策略风险通知，
只能订阅已经生成的 Risk Fact，并在独立 ADR 中定义；不得让回调参与当前订单判定或反向修改 Risk State。

## 8. Position Risk View

卖出审批同时读取账户真实 Position 与当前 Cluster Allocation 的只读 Snapshot：请求数量必须不超过两者有效可用量的
较小值。Position Reservation 与名义金额 Risk Reservation 分离；前者预占可卖仓位，后者服务资金/名义金额约束。
Position 处于 RECONCILING 时可用量为零，关键券商冲突必须阻断相关 Instrument。

完整成交终态由 Runtime 在 Position、Allocation 和 Ledger 全部成功后把 Risk Order Reservation 从 ACTIVE 推进为既有
`CONSUMED` 状态。部分成交保持 ACTIVE，但 remaining quantity/notional 按当前 Fill 减少；取消、拒绝、失败和过期继续
使用 RELEASED 生命周期。`remaining_order_notional` 表示扣除实际 Fill 名义金额后的订单预算，价格改善时可在数量归零后
保留预算余量；它不等于活动订单数量。

ExecutionProcessor 现按每个有效 Fill 部分消费 Risk Reservation 的 quantity/notional exposure；Reservation 保留原始值与累计
consumed 值，Risk Snapshot 只统计 remaining exposure。完全成交才进入 CONSUMED，Rejected/Cancelled 只释放剩余 exposure。

Generic T0 Cash multi-fill Long Close 在每个 Prepared Transaction 中分段消费 Position Reservation 与 Risk Reservation，且只
在 Order Final Fill 后减少 Active Order Count。Close 不复用现金 Reservation；Position/Allocation、Reservation 与 Risk 的
before/after version、consumed/released/remaining quantity 与 notional 由经济不变量交叉校验。部分成交后的
Cancel/Reject/Expire 通过 durable Terminal Transaction 释放 remaining，并且 Active Order Count 只减少一次。
## Account Risk View

Risk 通过 `OnlyAccountManagerRiskView` 读取 immutable Account Snapshot。BUY 使用 Limit Price 或当前 MarketData Snapshot
参考价检查可用现金；Account 非 ACTIVE、币种余额缺失或快照不可用时 Fail Closed。Risk Reservation 与 Account/Strategy
Reservation 状态独立，Trading Runtime 负责同一命令内的确定顺序。

## Rust component ownership and recovery boundary

`crates/onlyalpha-kernel/risk/` is an independently buildable non-deployed semantic library. It owns immutable decision/audit records, explicit Cluster profiles, canonical comparison rules, Risk-only exposure holds and Kill Switches. Domain is its sole local dependency; no Account/Position/Ledger/Order Manager, gateway, clock, database or market implementation is imported. Formal Runtime remains Python; component parity is not activation, LIVE permission, durable execution closure or product acceptance.

The component receives closed schema1 values binding engine/runtime/account/generation, Cluster/Strategy Revision, Instrument, explicit time/sequence, and immutable owning-family source/version/as-of/data evidence. Market verdicts bind the complete normalized Request digest. Missing/unavailable evidence produces ERROR; complete valid policy failure produces REJECT; no admission creates an Order or hold. Mandatory gates cannot be replaced or downgraded to observing. Profile comparisons order by SYSTEM/RUNTIME/ACCOUNT/INSTRUMENT/CLUSTER, explicit order and stable ID. Supported configurable comparisons are maximum active orders, single quantity, single notional and cumulative remaining notional; their scopes are explicit. Market sessions, tick/lot restrictions and fee formulas remain plugin inputs.

Cash requirement is an explicit externally resolved envelope, distinct from notional; Risk does not assume every market requires full notional cash or calculate margin. OPEN compares Account and Cluster cash capacity against the resolved requirement plus nonnegative fee estimate and all applicable pending Risk holds. Capacity envelopes explicitly represent available capacity before these same Risk holds; raw already-net owning snapshots are not interchangeable. The full cash/fee envelope is conservatively retained until terminal; quantity/notional risk exposure consumes incrementally. Post-economic views must cover the component economic Runtime-sequence watermark. CLOSE requires matching side/Position direction/mode and both Account Position and Cluster Allocation capacity, subtracting pending close holds; it remains possible under Kill Switch/unavailable cash-ledger views when required safety and market proofs are complete. Observation, Fill, cancel-pending and terminal handling remain available under a risk-increasing block.

ACCEPT records an admission epoch. RESERVE binds one exact Request to one Order and requires the unchanged epoch, except that identical already-applied reservation facts are idempotent. Execution integration must atomically capture admissible owning views, evaluate, create Order and reserve before publishing/sending. This component does not authenticate producers or prove cross-owner freshness simply by receiving hashes. The adapter/admission layer must construct these capacity envelopes from exact admitted owners and preserve source evidence; composing this with Account/Position/Ledger holds requires a separately designed owning transaction.

Reservations preserve original/consumed/released/remaining quantities and notional. UNKNOWN/cancel-pending keep holds; SENT cannot prove NOT_SENT. Exact partial fills retain active count; only a consistent Order final-fill fact consumes the final hold. Price-improvement notional remainder is released. Cancelled/rejected/failed/expired terminal facts release only remaining exposure, once. Oversized or contradictory fills return an atomic error instead of silently clipping: Execution must durably retain/reconcile venue facts, never discard them because a component refused an inconsistent projection. This is an explicit correction to the Python reference, whose ID-only create dedup, capped fill accumulation and incremental checkpoint mutation are not copied.

The public `Manager` provides `new`, `apply`, immutable `state`/Cluster `snapshot`, `checkpoint` and `restore`. Complete normalized receipts, source aliases, Request-to-Order relations, controls, decisions and audit are replayed from canonical complete schema1 journal/config into a fresh candidate; external SHA256 and complete reconstructed-state equality precede one replacement. No historical data is converted. Real service restart, deployed upgrade, source authentication and whole Runtime transaction recovery remain integration obligations. Shared independent vectors in `test-data/risk/` compare actual Python Pipeline/Reservation behavior with native Rust in debug/release for the valid common subset, alongside strict Rust conflict/conservation/fault tests.

Risk capacity is immutable configuration (`admission_limits`: positive commands/journal_bytes/checkpoint_bytes/reservations, ceilings 4096/8MiB/32MiB/1024). It applies to the prospective complete candidate for new OPEN decision/reservation admission, not to already-accepted exposure or safety control. Exceeding any budget blocks new risk atomically; exact duplicate acknowledgments, controls, observation stages, fills, terminal processing and proved CLOSE continue retaining full journal/receipts. Component checkpoint encoding/reading accepts this complete safety continuation beyond admission thresholds, including fresh restore and subsequent events. History is never discarded to meet a budget. These are backpressure thresholds rather than physical resource caps; durable Execution storage/rotation/resource-pressure orchestration remains a separate integration obligation and must preserve the same safety continuity.

Financial admission bounds apply to the stored plain-normalized coefficient, including zeros expanded from scientific notation. Normalizing an admitted config/command must never make it unreadable by a fresh component reader.
