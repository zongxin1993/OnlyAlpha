# Risk 组件

## 1. 职责与边界

每个 Runtime 独占一个 `OnlyRiskService`。它拥有 Rule Pipeline、Cluster Risk Profile 绑定、Risk State、
不可变 Snapshot、Reservation、Kill Switch 状态和审计记录。Cluster 只得到 `ctx.risk` 的只读 Snapshot View，
订单仍只能经 `ctx.orders.submit()` 提交。

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

Snapshot 是带版本、时间、Scope、活动订单数、预占金额/数量、剩余额度、拒绝计数、Kill Switch 和数据质量标记
的 frozen 值。`ctx.risk` 不暴露 evaluate、reserve、release、disable rule、Cache 或 Gateway 能力。

Reservation 由 Runtime 单写管理，ID 和遍历顺序确定；创建按 OrderId 幂等，释放校验 Runtime/Cluster Scope 且
幂等。订单 Cancelled、Rejected、Failed、Expired、Execution 拒收或 Cluster 停止时释放。首版不实现部分成交
消耗和 Position 转换。

## 6. Kill Switch、Event 与审计

Kill Switch 是 Runtime 管理能力，可作用于 Runtime、Cluster 或 Account；Cluster 只看到 Snapshot 中的布尔值。
Risk Accepted/Rejected/RuleFailed、Reservation Created/Released 和 State Updated 都是判定或状态成功变化后的事实。
Event 只用于审计、监控和未来扩展，不驱动 Rule 执行，也没有策略 Risk 回调。

每次新的 intent 判定记录 Scope、Profile、Decision 和纳秒时间。相同 RequestId 与相同 intent 返回缓存判定；
相同 RequestId 对应不同 intent 被拒绝，保证重放稳定。

## 7. 隔离、Demo 与限制

Risk State、Profile、Permission、Reservation、Kill Switch、审计和序列均按 Runtime 隔离；Cluster 之间的 Profile、
Snapshot 和权限也隔离。`examples/risk_demo` 覆盖 ACCEPT、非法 tick、额度拒绝、不同 Profile、连续预占、
Fail Closed 和 Snapshot。

已知限制：账户和持仓数据源尚不可用；Market Order 在需要名义金额规则时因缺少可靠价格而 Fail Closed；尚未实现
Reservation 的部分成交消耗、持久化恢复、Live Runtime 外部回报串行化及真实券商适配。未来若增加策略风险通知，
只能订阅已经生成的 Risk Fact，并在独立 ADR 中定义；不得让回调参与当前订单判定或反向修改 Risk State。
