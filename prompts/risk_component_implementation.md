# OnlyAlpha Risk 风险管理组件设计、实现与验证任务

## 1. 任务目标

现在开始单独实现 OnlyAlpha 的 Risk 风险管理组件。

本阶段需要建立一套：

* 确定性；
* 可组合；
* 可配置；
* 可扩展；
* 可测试；
* 可审计；
* 多 Runtime 隔离；
* 多 Cluster 隔离；
* 多账户可扩展；
* 回测与实盘接口一致；

的风险管理体系。

Risk 组件需要接入已经存在的：

```text
OnlyRuntime
OnlyRuntimeContext
OnlyCluster
OnlyOrderService
OnlyOrderManager
OnlyMarketDataSnapshot
OnlyClock
OnlyInstrument
OnlyMarketRule
```

最终订单提交链应调整为：

```text
OnlyCluster
    ↓
ctx.orders.submit(request)
    ↓
OnlyOrderService
    ↓
基础请求校验
    ↓
OnlyRiskService.evaluate_order()
    ├── 系统强制规则
    ├── Runtime 规则
    ├── Account 规则
    └── Cluster Risk Profile 规则
    ↓
ACCEPT
    → 创建 OnlyOrder
    → 创建风险预占
    → 提交 Execution Port

REJECT
    → 不创建正式 OnlyOrder
    → 不调用 Execution Port
    → 返回结构化拒绝结果
    → 发布 Risk Rejected 事实 Event

ERROR
    → Fail Closed
    → 不创建正式 OnlyOrder
    → 不调用 Execution Port
    → 返回结构化错误
    → 发布 Risk Rule Failed 事实 Event
```

本阶段暂不实现策略中的以下回调：

```text
on_risk_rejected
on_risk_limit_triggered
on_risk_state_changed
on_risk_error
```

可以定义对应 Event 和未来扩展说明，但不要修改 `OnlyCluster` 回调 API，也不要由 Runtime 调用这些回调。

---

# 2. 核心架构原则

必须遵循：

```text
Risk Evaluation 使用函数调用
Risk Query 使用函数调用
Risk Result Notification 使用 Event
EventBus 不承担 Risk Rule 执行顺序
RiskService 不直接依赖 Cluster 实例
策略不能关闭或绕过系统强制风控
策略不能决定风控异常后是否继续下单
风控异常默认 Fail Closed
```

Risk 的核心设计采用：

```text
抽象接口
    +
多个可组合 OnlyRiskRule
    +
配置化 OnlyRiskProfile
    +
OnlyRiskService 统一编排
```

不建议主要依赖一个包含所有逻辑的巨大 RiskManager 子类。

推荐：

```text
Polymorphism + Composition + Configuration
```

即：

* 虚函数或 Protocol 定义统一 Rule API；
* 每条 Risk Rule 独立实现；
* Risk Profile 通过配置组合 Rule；
* Runtime 根据 Cluster、Account 和运行模式组合最终 Pipeline。

---

# 3. 本阶段范围

本阶段实现：

```text
OnlyRiskRule
OnlyRiskPipeline
OnlyRiskService
OnlyRiskProfile
OnlyRiskProfileConfig
OnlyRiskProfileFactory
OnlyRiskRuleRegistry
OnlyRiskContext
OnlyRiskEvaluationContext
OnlyRiskSnapshot
OnlyRiskDecision
OnlyRiskRejection
OnlyRiskErrorInfo
OnlyRiskReservation
OnlyRiskReservationManager
OnlyRiskStateStore
OnlyRiskEventPublisher
```

以及第一批确定性 Risk Rule。

本阶段暂不完整实现：

* PositionManager；
* AccountManager；
* 保证金引擎；
* 组合级 VaR；
* 期权 Greeks 风险；
* 实盘账户同步；
* 自动强平；
* 自动撤单；
* Kill Switch 管理 UI；
* 策略 Risk 回调；
* 真实券商风控；
* 分布式 Risk Service。

对于尚未完成的 Account、Position 能力，定义只读抽象 Port 和明确的占位实现，不伪造真实资金与持仓。

---

# 4. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/event.md
docs/market_data_pipeline.md
docs/runtime_context.md
docs/runtime.md
docs/cluster.md
docs/order.md
docs/coding_style.md
docs/testing.md
docs/architecture_principles.md
docs/adr/
```

重点检查当前已有：

```text
OnlyOrderRequest
OnlyOrderService
OnlyOrderManager
OnlyOrderSubmitResult
OnlyOrderSnapshot
OnlyRuntimeContext
OnlyClusterContext
OnlyBarContext
OnlyMarketDataSnapshot
OnlyInstrumentView
OnlyClockView
OnlyOrderQueryView
```

还需要分析：

```text
https://github.com/zongxin1993/MyQuant/blob/master/MyQuant/core/rick.py
```

重点了解：

* 现有风险管理入口；
* 风险规则；
* 订单检查顺序；
* 资金与持仓检查；
* 日亏损限制；
* 订单频率限制；
* 策略自定义 Risk；
* 回测和实盘 Risk 差异；
* Risk 状态保存方式；
* 重复订单和风险额度处理。

只参考行为，以本工程结构为主，不直接复制旧架构。

---

# 5. 先创建差距分析

创建：

```text
docs/risk_component_analysis.md
```

至少包含：

## 5.1 当前 Risk 实现

| 模块 | 当前职责 | 当前问题 | 目标实现 |
| -- | ---- | ---- | ---- |

## 5.2 当前订单风控链路

画出：

```text
策略
→ OrderService
→ Risk
→ OrderManager
→ Execution
```

检查：

* Risk 是否可以被策略绕过；
* Risk 是否直接依赖策略对象；
* Risk 是否通过 EventBus 执行；
* 是否只有一个返回 bool 的接口；
* 是否无法区分拒绝和系统错误；
* 是否存在大类和大量市场判断；
* 是否在 `on_bar` 前检查一次后就不再检查订单；
* 是否忽略未完成订单和预占风险；
* 不同 Cluster 是否错误共享有状态 Risk；
* 回测和实盘是否使用不同风控 API。

## 5.3 当前风险数据来源

列出：

* Instrument；
* MarketRule；
* Clock；
* MarketData；
* Order；
* Position；
* Account；
* Cluster 配置；
* Runtime 配置。

标明哪些已经实现、哪些需要 Port、哪些本阶段暂不支持。

先完成分析，再修改代码。

---

# 6. Risk 的三阶段模型

Risk 不能只在 `on_bar` 前或 `on_bar` 后执行一次。

必须按三个阶段设计。

## 6.1 Pre-Decision Risk State Update

发生在策略 `on_bar` 之前。

目标：

* 更新策略决策时所看到的风险状态；
* 生成只读 `OnlyRiskSnapshot`；
* 不针对某一张具体订单做最终审批。

推荐数据流：

```text
基础 Bar
→ 派生 Bar
→ Indicator
→ MarketData Snapshot
→ Position/Account 估值 Port
→ Risk State 更新
→ Risk Snapshot
→ OnlyBarContext
→ Cluster.on_bar()
```

当前阶段由于 PositionManager 和 AccountManager 尚未完成，可以先实现：

* Market Data 相关风险状态；
* 活跃订单数量；
* 已预占订单额度；
* Cluster Risk Profile 状态；
* Runtime Risk 状态；
* Instrument 风险状态。

必须为账户和持仓估值定义 Port，但不得返回虚构的充足余额。

## 6.2 Pre-Trade Risk Evaluation

发生在策略调用：

```python
ctx.orders.submit(request)
```

之后，创建正式订单之前。

这是不可绕过的最终订单审批。

执行链：

```text
ctx.orders.submit()
→ Request 结构校验
→ OnlyRiskService.evaluate_order()
→ ACCEPT / REJECT / ERROR
```

只有 ACCEPT 才允许：

```text
OnlyOrderManager.create_order()
```

REJECT 和 ERROR 均不得创建正式 `OnlyOrder`。

## 6.3 Post-Order/Post-Trade Risk Update

本阶段只建立接口和状态更新入口。

未来以下事件发生后需要更新 Risk State：

```text
Order Created
Order Rejected
Order Cancelled
Order Expired
Order Failed
Trade Occurred
Position Updated
Account Updated
```

当前阶段至少完整实现：

* 创建订单后的风险预占；
* 撤单、拒绝、过期、失败后的预占释放；
* 重复更新的幂等处理。

成交、Position、Account 的完整更新留到后续组件。

---

# 7. 策略对 Risk 的访问边界

策略不能获得完整 `OnlyRiskService`。

禁止：

```python
ctx.risk.disable_rule(...)
ctx.risk.remove_rule(...)
ctx.risk.accept_order(...)
ctx.risk.reset_limit(...)
ctx.risk.clear_reservations(...)
ctx.risk.set_kill_switch(False)
```

策略未来可以获得只读：

```text
OnlyRiskSnapshotView
```

例如：

```python
ctx.risk.snapshot()
ctx.risk.current_state
ctx.risk.remaining_order_notional
ctx.risk.active_order_count
ctx.risk.kill_switch_active
```

当前阶段可以将只读 Risk Snapshot 接入 `OnlyBarContext`，但不实现任何 `on_risk_xxx` 策略回调。

必须明确：

> 策略读取 Risk Snapshot 只是决策参考，不代表下一张订单一定会通过最终 Risk 检查。

每次 `ctx.orders.submit()` 都必须重新执行 Pre-Trade Risk。

---

# 8. Risk Rule 抽象接口

定义：

```text
OnlyRiskRule
OnlyRiskRuleId
OnlyRiskRuleConfig
OnlyRiskRuleScope
OnlyRiskRuleMode
OnlyRiskRuleMetadata
```

建议接口：

```python
class OnlyRiskRule(ABC):
    @property
    @abstractmethod
    def rule_id(self) -> OnlyRiskRuleId:
        ...

    @property
    @abstractmethod
    def scope(self) -> OnlyRiskRuleScope:
        ...

    @property
    def mode(self) -> OnlyRiskRuleMode:
        ...

    @abstractmethod
    def evaluate(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> OnlyRiskDecision:
        ...
```

Rule 必须：

* 输入统一；
* 输出统一；
* 不直接创建或修改 Order；
* 不直接调用 Gateway；
* 不直接调用 Cluster；
* 不发布 Event；
* 不修改其他 Rule；
* 不读取无权限状态；
* 尽量无状态；
* 可单独测试。

---

# 9. Rule Scope

至少定义：

```text
SYSTEM
RUNTIME
ACCOUNT
CLUSTER
INSTRUMENT
```

含义：

```text
SYSTEM
    系统级强制规则，策略不可关闭

RUNTIME
    当前 Runtime 的全局规则

ACCOUNT
    某账户的额度、资金和保证金规则

CLUSTER
    某策略实例的个性化规则

INSTRUMENT
    某资产、品种或市场相关的规则
```

有状态 Rule 必须明确其状态 Scope。

禁止让不同 Cluster 错误共享：

* 订单计数；
* 冷却时间；
* 日亏损；
* 连续亏损；
* 风险预占。

---

# 10. Rule Mode

定义：

```text
OnlyRiskRuleMode
├── ENFORCING
└── OBSERVING
```

## ENFORCING

可以拒绝订单。

## OBSERVING

只生成观察结果，不阻止订单。

但以下系统规则必须是 ENFORCING，不能被配置为 OBSERVING：

* Runtime Scope；
* Cluster Scope；
* Instrument 存在；
* 不支持订单类型；
* 基础价格与数量有效性；
* 系统 Kill Switch。

Risk Profile 加载时必须校验该约束。

---

# 11. Risk Pipeline

定义：

```text
OnlyRiskPipeline
OnlyRiskPipelineResult
OnlyRiskPipelineConfig
```

执行顺序固定为：

```text
1. System Mandatory Rules
2. Runtime Rules
3. Account Rules
4. Instrument Rules
5. Cluster Profile Rules
```

不得使用 EventBus priority 决定执行顺序。

同一层 Rule 顺序由：

```text
显式 order
→ stable rule_id
```

决定。

推荐执行逻辑：

```python
for rule in rules:
    try:
        decision = rule.evaluate(request, context)
    except Exception as exc:
        return OnlyRiskDecision.error(...)

    if decision.is_error:
        return decision

    if decision.is_rejected and rule.mode is ENFORCING:
        return decision
```

第一版采用：

```text
First Rejection Stops
```

即遇到第一个强制拒绝立即停止。

同时保留未来：

```text
Collect All Rejections
```

扩展点，但不在本阶段实现。

---

# 12. Risk Decision

定义统一结果：

```text
OnlyRiskDecision
OnlyRiskOutcome
OnlyRiskRejection
OnlyRiskErrorInfo
OnlyRiskObservation
```

`OnlyRiskOutcome` 至少：

```text
ACCEPT
REJECT
ERROR
```

## 12.1 ACCEPT

表示所有强制规则通过。

## 12.2 REJECT

表示 Risk 正常工作，并基于规则拒绝订单。

至少包含：

```text
rule_id
code
message
scope
severity
retryable
details
requested_value
allowed_value
```

## 12.3 ERROR

表示 Risk 无法可靠完成判断。

例如：

* Rule 抛异常；
* Account Snapshot 缺失；
* Position Snapshot 版本冲突；
* Currency 无法转换；
* Risk State 损坏；
* 必需数据缺失。

默认：

```text
ERROR → Fail Closed → 拒绝订单
```

策略和配置不能将强制 Rule 的 ERROR 改成 ACCEPT。

---

# 13. Risk Rejection Code

至少定义：

```text
OnlyRiskRejectionCode
```

第一版建议包含：

```text
INSTRUMENT_NOT_FOUND
INSTRUMENT_NOT_TRADABLE
UNSUPPORTED_ORDER_TYPE
INVALID_PRICE
INVALID_PRICE_INCREMENT
INVALID_QUANTITY
INVALID_QUANTITY_INCREMENT
MINIMUM_QUANTITY_NOT_MET
MAXIMUM_QUANTITY_EXCEEDED
MINIMUM_NOTIONAL_NOT_MET
MAXIMUM_ORDER_NOTIONAL_EXCEEDED
OUTSIDE_TRADING_SESSION
PRICE_LIMIT_EXCEEDED
CLUSTER_NOT_AUTHORIZED
ACCOUNT_NOT_AUTHORIZED
DUPLICATE_ORDER_REQUEST
MAX_ACTIVE_ORDERS_EXCEEDED
MAX_CLUSTER_ACTIVE_ORDERS_EXCEEDED
MAX_INSTRUMENT_ACTIVE_ORDERS_EXCEEDED
RISK_RESERVATION_EXCEEDED
KILL_SWITCH_ACTIVE
REQUIRED_RISK_DATA_MISSING
RISK_RULE_ERROR
```

不要使用任意字符串作为拒绝码。

---

# 14. 第一批 Mandatory System Rules

至少实现：

```text
OnlyRuntimeScopeRiskRule
OnlyClusterScopeRiskRule
OnlyInstrumentExistsRiskRule
OnlyInstrumentTradingStatusRiskRule
OnlyOrderTypeSupportedRiskRule
OnlyBasicPriceRiskRule
OnlyBasicQuantityRiskRule
OnlyKillSwitchRiskRule
```

这些规则必须默认启用，Cluster 不可删除。

## 14.1 Runtime Scope

验证请求属于当前 Runtime。

策略不允许伪造 runtime_id。

## 14.2 Cluster Scope

验证当前 Context 和 Cluster 权限。

策略不允许为其他 Cluster 下单。

## 14.3 Instrument Exists

Instrument 必须存在于当前 Runtime 的 Registry。

## 14.4 Instrument Tradable

Instrument 状态必须允许交易。

## 14.5 Order Type

当前 Runtime/Execution Port 必须声明支持该订单类型。

## 14.6 Basic Price

验证：

* LIMIT 必须有 Price；
* MARKET 不应包含无效 Price；
* Price 不是 NaN/Infinity；
* Price 符合基础 Domain 不变量。

## 14.7 Basic Quantity

验证：

* Quantity 大于零；
* Quantity 不是 NaN/Infinity；
* 数量符合基础 Domain 不变量。

---

# 15. 第一批 Instrument 和 Market Rules

实现：

```text
OnlyPriceIncrementRiskRule
OnlyQuantityIncrementRiskRule
OnlyMinimumQuantityRiskRule
OnlyMaximumQuantityRiskRule
OnlyMinimumNotionalRiskRule
OnlyTradingSessionRiskRule
OnlyPriceLimitRiskRule
```

这些 Rule 必须通过：

```text
OnlyInstrumentView
OnlyMarketRuleView
OnlyClockView
OnlyTradingCalendarView
```

读取数据。

Rule 不得在内部散落：

```python
if market == "CN":
elif market == "US":
elif market == "HK":
```

市场差异应来自 Instrument 和 MarketRule。

---

# 16. 第一批 Runtime 和 Cluster Rules

实现：

```text
OnlyMaxActiveOrdersRiskRule
OnlyMaxClusterActiveOrdersRiskRule
OnlyMaxInstrumentActiveOrdersRiskRule
OnlyMaxOrderQuantityRiskRule
OnlyMaxOrderNotionalRiskRule
OnlyClusterInstrumentPermissionRiskRule
OnlyClusterAccountPermissionRiskRule
```

这些 Rule 可以使用：

```text
OnlyOrderRiskView
OnlyRiskReservationView
OnlyClusterPermissionView
```

不得直接访问可变 OrderManager。

---

# 17. Account 和 Position Risk Port

当前阶段不实现完整 AccountManager 和 PositionManager，但必须定义：

```text
OnlyAccountRiskView
OnlyPositionRiskView
OnlyAccountRiskSnapshot
OnlyPositionRiskSnapshot
```

未来规则包括：

```text
OnlyAvailableBalanceRiskRule
OnlyAvailablePositionRiskRule
OnlyMaxPositionRiskRule
OnlyMarginRequirementRiskRule
OnlyDailyLossLimitRiskRule
```

本阶段要求：

* 定义接口；
* 定义数据缺失语义；
* 提供明确 `OnlyUnavailableAccountRiskView`；
* 提供明确 `OnlyUnavailablePositionRiskView`；
* 依赖这些数据的 Rule 在数据不可用时返回 ERROR；
* 不得假设余额无限；
* 不得假设持仓充足；
* 不得伪造零持仓或无限资金。

未启用账户/持仓 Rule 时，订单可由现阶段其他 Rule 决定。

启用依赖数据的 Rule 但数据不可用时，必须 Fail Closed。

---

# 18. Risk Context

定义：

```text
OnlyRiskEvaluationContext
```

至少提供受限只读能力：

```text
runtime_id
cluster_id
account_id
clock
instruments
market_rules
trading_calendar
orders
reservations
account_risk
position_risk
market_data
risk_state
```

禁止提供：

```text
OrderManager
EventBus
Gateway
Cluster 实例
可变 Cache
ExecutionService
```

Risk Rule 只能通过 View/Protocol 查询。

---

# 19. Risk Profile

定义：

```text
OnlyRiskProfile
OnlyRiskProfileId
OnlyRiskProfileConfig
OnlyRiskProfileFactory
OnlyRiskRuleRegistry
```

配置示例：

```yaml
risk_profiles:
  equity_conservative:
    rules:
      - type: OnlyMaxOrderQuantityRiskRule
        order: 100
        config:
          max_quantity: "5000"

      - type: OnlyMaxOrderNotionalRiskRule
        order: 200
        config:
          max_notional:
            amount: "50000"
            currency: CNY

      - type: OnlyMaxClusterActiveOrdersRiskRule
        order: 300
        config:
          maximum: 10

clusters:
  - id: strategy_a
    risk_profile: equity_conservative
```

Runtime 加载 Cluster 时：

```text
读取 risk_profile
→ 通过 Registry 找到 Rule 类型
→ 校验 Config
→ 创建或绑定 Rule
→ 合并 Mandatory Rules
→ 生成最终 Pipeline
→ 绑定 runtime_id / cluster_id / account_id
```

---

# 20. 自定义 Risk Rule

允许用户实现：

```python
class OnlyCustomRiskRule(OnlyRiskRule):
    def evaluate(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> OnlyRiskDecision:
        ...
```

动态加载时必须校验：

* 类名以 `Only` 开头；
* 实现 `OnlyRiskRule`；
* RuleId 唯一；
* Scope 合法；
* Mode 合法；
* Config 可验证；
* 不覆盖 Mandatory Rule；
* 不访问禁止模块；
* 不返回普通 bool；
* 不抛出未处理异常。

Risk Rule 可以通过注册表静态或动态注册。

不要将自定义 Risk 写成依赖策略实例的方法。

---

# 21. Risk Service

每个 Runtime 拥有一个：

```text
OnlyRiskService
```

结构：

```text
OnlyRuntime
└── OnlyRiskService
    ├── Mandatory System Pipeline
    ├── Runtime Rules
    ├── Account Rules
    ├── Cluster Profiles
    ├── Risk State Store
    └── Reservation Manager
```

一个 Runtime 内多个 Cluster 共用 RiskService，但：

* Cluster Profile 独立；
* Cluster State 独立；
* 有状态规则按 Scope 隔离；
* Risk Reservation 按 Cluster/Account/Instrument 隔离。

不同 Runtime 不得共享可变 Risk State。

---

# 22. Risk Service 接口

建议：

```python
class OnlyRiskService:
    def bind_cluster_profile(
        self,
        cluster_id: OnlyClusterId,
        profile: OnlyRiskProfile,
    ) -> None:
        ...

    def unbind_cluster_profile(
        self,
        cluster_id: OnlyClusterId,
    ) -> None:
        ...

    def update_pre_decision_state(
        self,
        context: OnlyRiskStateUpdateContext,
    ) -> OnlyRiskSnapshot:
        ...

    def evaluate_order(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> OnlyRiskDecision:
        ...

    def reserve(
        self,
        reservation: OnlyRiskReservation,
    ) -> OnlyRiskReservationResult:
        ...

    def release_reservation(
        self,
        reservation_id: OnlyRiskReservationId,
        reason: OnlyRiskReleaseReason,
    ) -> OnlyRiskReservationResult:
        ...

    def get_snapshot(
        self,
        cluster_id: OnlyClusterId,
    ) -> OnlyRiskSnapshot:
        ...
```

---

# 23. Pre-Decision Risk Snapshot

定义不可变：

```text
OnlyRiskSnapshot
OnlyRiskSnapshotView
OnlyRiskState
OnlyRiskLevel
```

至少包含：

```text
runtime_id
cluster_id
account_id
ts_event
ts_init
version

risk_level
kill_switch_active
active_order_count
cluster_active_order_count
reserved_notional
reserved_quantity
remaining_order_notional
recent_rejection_count
warnings
quality_flags
```

未来扩展：

```text
gross_exposure
net_exposure
daily_pnl
daily_loss
drawdown
margin_used
margin_available
position_concentration
```

Risk Snapshot 应在 `on_bar` 前更新并加入只读 Context。

本阶段不实现策略 `on_risk_state_changed` 回调。

---

# 24. OrderService 集成

修改 `OnlyOrderService.submit()` 调用顺序：

```text
1. ctx.orders 自动绑定 Runtime/Cluster/Account Scope
2. 校验 OnlyOrderRequest 基础结构
3. 构建 OnlyRiskEvaluationContext
4. 调用 OnlyRiskService.evaluate_order()
5. 如果 REJECT：
   - 不创建 OnlyOrder
   - 不调用 ExecutionService
   - 保存 Risk Decision Audit
   - 发布 OnlyRiskRejectedEvent
   - 返回 OnlyOrderSubmitResult

6. 如果 ERROR：
   - Fail Closed
   - 不创建 OnlyOrder
   - 不调用 ExecutionService
   - 保存 Risk Error Audit
   - 发布 OnlyRiskRuleFailedEvent
   - 返回 OnlyOrderSubmitResult

7. 如果 ACCEPT：
   - 创建 OnlyOrder
   - 创建 Risk Reservation
   - 调用 ExecutionService
   - 根据提交结果维护 Reservation
   - 发布相应事实 Event
```

Risk 必须发生在：

```text
OrderManager.create_order()
```

之前。

---

# 25. 风控拒绝时是否创建 Order

本阶段固定规则：

> Pre-Trade Risk 拒绝时不创建正式 `OnlyOrder`。

但必须记录：

```text
OnlyOrderIntentAudit
OnlyRiskDecisionAudit
```

至少包含：

```text
request_id
runtime_id
cluster_id
account_id
request
decision
ts_event
ts_init
correlation_id
```

这样可以审计策略尝试过的订单，而不污染 OrderManager。

---

# 26. Risk Reservation

必须设计风险预占，避免同一回调内连续订单超额。

例如：

```text
最大订单金额：100000 CNY

订单 A：60000
→ Risk 通过
→ 预占 60000

订单 B：60000
→ Risk 再检查
→ 可用额度只剩 40000
→ Risk 拒绝
```

定义：

```text
OnlyRiskReservation
OnlyRiskReservationId
OnlyRiskReservationType
OnlyRiskReservationState
OnlyRiskReservationManager
OnlyRiskReservationResult
OnlyRiskReleaseReason
```

至少支持：

```text
ACTIVE
RELEASED
CONSUMED
FAILED
```

Reservation 建议包含：

```text
reservation_id
runtime_id
cluster_id
account_id
order_id
instrument_id
currency
reserved_notional
reserved_quantity
created_at
updated_at
state
version
```

---

# 27. Reservation 生命周期

建议：

```text
Risk ACCEPT
    ↓
Order 创建
    ↓
Reservation ACTIVE
```

释放条件：

```text
Order REJECTED
Order CANCELLED
Order EXPIRED
Order FAILED
```

成交后的消耗和 Position/Account 转换在后续 Execution 组件完善。

当前阶段至少确保：

* 创建预占；
* 重复创建幂等；
* 释放幂等；
* 终态订单释放；
* 不允许跨 Cluster 释放；
* 不允许跨 Runtime 释放。

---

# 28. Risk 状态存储

定义：

```text
OnlyRiskStateStore
```

第一版实现：

```text
OnlyInMemoryRiskStateStore
```

负责：

* Cluster Risk State；
* Account Risk State 占位；
* Rule State；
* Rejection Counter；
* Reservation 索引；
* Snapshot Version。

状态不得散落在 Rule 实例的普通字段中，除非 Rule 明确是 Runtime 私有且不可共享。

推荐 Rule 尽量无状态，通过 Context 和 StateStore 查询状态。

---

# 29. Risk Event

定义事实事件：

```text
OnlyRiskAcceptedEvent
OnlyRiskRejectedEvent
OnlyRiskRuleFailedEvent
OnlyRiskLimitTriggeredEvent
OnlyRiskReservationCreatedEvent
OnlyRiskReservationReleasedEvent
OnlyRiskStateUpdatedEvent
```

当前阶段不实现策略侧回调。

Event 用于：

* 审计；
* 日志；
* Storage；
* Web；
* Metrics；
* 未来 Runtime Dispatcher。

Risk Event 不能驱动 Risk Pipeline 执行。

正确顺序：

```text
函数调用 RiskService
→ 得到 Decision
→ OrderService 执行业务结果
→ 发布 Risk Event
```

禁止：

```text
发布 CheckRiskEvent
→ 多个 Handler 决定是否下单
```

---

# 30. Risk Event Publisher Port

定义：

```text
OnlyRiskEventPublisher
```

接口：

```python
publish(event: OnlyRiskEvent) -> None
publish_many(events: tuple[OnlyRiskEvent, ...]) -> None
```

提供：

```text
OnlyNoOpRiskEventPublisher
OnlyInMemoryRiskEventPublisher
OnlyRuntimeRiskEventPublisherAdapter
```

Risk Rule 本身不直接发布 Event。

由 RiskService 或 OrderService Application 层发布。

---

# 31. Risk Rule 异常处理

Rule 执行可能抛异常。

RiskPipeline 必须捕获，并生成：

```text
OnlyRiskDecision(
    outcome=ERROR,
    error=OnlyRiskErrorInfo(...),
)
```

错误信息至少包含：

```text
rule_id
scope
exception_type
message
runtime_id
cluster_id
account_id
request_id
ts_event
ts_init
retryable
details
```

默认：

```text
Risk ERROR → Fail Closed
```

不得让异常继续穿透后默认提交订单。

不得让策略决定是否忽略 Risk Error。

---

# 32. 不允许静默修改订单

第一版固定：

```text
OnlyRiskAdjustmentPolicy.REJECT
```

如果策略请求 1000 股，Risk 只允许 500 股：

* 不得静默改成 500；
* 返回结构化拒绝；
* 可以在 details 中提供 `maximum_allowed_quantity`；
* 策略未来可在下一个 Bar 或 Timer 中重新提交。

本阶段不实现：

```text
CLAMP
SPLIT
AUTO_REPRICE
```

只保留扩展设计。

---

# 33. 同一 on_bar 连续订单

必须测试：

```python
ctx.orders.submit(order_a)
ctx.orders.submit(order_b)
```

第二张订单必须看到第一张订单已经创建的 Risk Reservation。

不能两张订单都使用 `on_bar` 前旧的 Risk Snapshot 通过审批。

正式 Risk 评估必须查询最新：

* 活跃订单；
* Reservation；
* Cluster State；
* Account State Port；
* Position State Port。

---

# 34. ctx.risk 接口

可将只读能力加入：

```text
OnlyClusterContext
OnlyBarContext
OnlyTimerContext
```

形式：

```python
ctx.risk.snapshot()
ctx.risk.current_level
ctx.risk.kill_switch_active
ctx.risk.active_order_count
ctx.risk.reserved_notional
```

类型：

```text
OnlyRiskSnapshotView
```

禁止暴露：

```text
ctx.risk_service
ctx.risk_pipeline
ctx.risk_state_store
ctx.risk.reservations.release(...)
ctx.risk.disable_rule(...)
ctx.risk.evaluate_order(...)
```

订单最终审批只能由 `OnlyOrderService` 调用 RiskService。

策略不能直接调用 `evaluate_order()` 后绕过订单流程。

---

# 35. Profile 生命周期

Cluster 加载和初始化时：

```text
读取 Cluster Config
→ 解析 risk_profile
→ 创建 Profile
→ 合并 Mandatory Rules
→ 绑定到 RiskService
→ 校验 Account/Instrument 权限
→ Cluster 才可进入 READY/RUNNING
```

Cluster 停止或卸载时：

* 解绑 Profile；
* 清理 Cluster 私有 Rule State；
* 处理尚未释放的 Reservation；
* 不影响其他 Cluster。

Profile 加载失败时，Cluster 不得启动。

---

# 36. Kill Switch

本阶段定义：

```text
OnlyRiskKillSwitch
OnlyKillSwitchState
OnlyKillSwitchReason
OnlyKillSwitchView
```

至少支持：

```text
ACTIVE
INACTIVE
```

Kill Switch 可以存在于：

```text
SYSTEM
RUNTIME
ACCOUNT
CLUSTER
```

只要任一适用 Scope 的强制 Kill Switch 激活，订单必须拒绝。

策略只能读取状态，不能关闭。

本阶段可以实现管理端内部接口，但不接 Web，也不暴露给 Cluster。

---

# 37. 幂等与确定性

必须保证：

* 相同 RequestId 重复评估结果稳定；
* Reservation 重复创建不重复占用；
* Reservation 重复释放不重复变更；
* Rule 顺序稳定；
* Profile 配置顺序稳定；
* Event 顺序稳定；
* 相同输入和初始状态产生相同 Decision；
* 不依赖 dict、set、对象地址或随机顺序；
* 不依赖系统当前时间；
* 时间来自 Runtime Clock。

---

# 38. 并发策略

第一版明确：

```text
RiskService 和 RiskStateStore 由单 Runtime 线程串行修改。
```

RiskRule 可以是无状态共享实例，但有状态数据必须存于按 Scope 隔离的 StateStore。

未来外部账户回报必须通过 Runtime 受控队列更新风险状态。

不得让 Gateway SDK 回调线程直接修改 RiskStateStore。

---

# 39. 推荐目录

根据当前工程调整，但建议：

```text
src/onlyalpha/risk/
├── __init__.py
├── enums.py
├── identifiers.py
├── decisions.py
├── rejections.py
├── errors.py
├── snapshots.py
├── contexts.py
├── rules/
│   ├── base.py
│   ├── mandatory.py
│   ├── instrument.py
│   ├── market.py
│   ├── runtime.py
│   ├── cluster.py
│   └── account.py
├── pipeline.py
├── profile.py
├── registry.py
├── factory.py
├── service.py
├── state_store.py
├── reservations.py
├── views.py
├── ports.py
├── events.py
├── publisher.py
├── audit.py
└── exceptions.py
```

---

# 40. 最小 Demo

创建：

```text
examples/risk_demo/
├── README.md
├── accepted_order_demo.py
├── rejected_price_increment_demo.py
├── rejected_max_notional_demo.py
├── cluster_profile_demo.py
├── reservation_demo.py
├── risk_error_fail_closed_demo.py
└── risk_snapshot_demo.py
```

## 40.1 合法订单

```text
ctx.orders.submit()
→ Risk ACCEPT
→ Order CREATED
→ Reservation ACTIVE
→ Placeholder Execution
```

## 40.2 非法 Tick

```text
Price 不符合 price_increment
→ Risk REJECT
→ 不创建 Order
→ 不调用 Execution
→ 返回 INVALID_PRICE_INCREMENT
```

## 40.3 不同 Cluster Profile

Cluster A：

```text
max_order_notional = 50000 CNY
```

Cluster B：

```text
max_order_notional = 200000 CNY
```

同一订单：

* A 拒绝；
* B 接受。

Mandatory Rule 对 A、B 都生效。

## 40.4 连续订单预占

最大额度 100000：

```text
订单 A 60000 → 接受并预占
订单 B 60000 → 拒绝
```

## 40.5 Rule 异常

自定义 Rule 抛异常：

```text
Risk Outcome = ERROR
Order 不创建
Execution 不调用
Fail Closed
```

## 40.6 Snapshot

Bar 前更新 Risk Snapshot，策略 Context 可以读取，但不能修改。

---

# 41. 必须新增的测试

建议：

```text
tests/risk/
├── test_risk_rule_interface.py
├── test_risk_decision.py
├── test_risk_rejection.py
├── test_risk_error.py
├── test_risk_pipeline_order.py
├── test_risk_pipeline_first_rejection.py
├── test_risk_pipeline_observing_rule.py
├── test_risk_pipeline_rule_exception.py
├── test_risk_fail_closed.py
├── test_mandatory_rules_cannot_be_removed.py
├── test_runtime_scope_rule.py
├── test_cluster_scope_rule.py
├── test_instrument_exists_rule.py
├── test_instrument_status_rule.py
├── test_order_type_supported_rule.py
├── test_price_increment_rule.py
├── test_quantity_increment_rule.py
├── test_minimum_quantity_rule.py
├── test_maximum_quantity_rule.py
├── test_minimum_notional_rule.py
├── test_trading_session_rule.py
├── test_price_limit_rule.py
├── test_max_active_orders_rule.py
├── test_max_cluster_active_orders_rule.py
├── test_max_order_quantity_rule.py
├── test_max_order_notional_rule.py
├── test_cluster_instrument_permission_rule.py
├── test_cluster_account_permission_rule.py
├── test_risk_profile_config.py
├── test_risk_profile_factory.py
├── test_custom_risk_rule_loading.py
├── test_risk_rule_scope_isolation.py
├── test_risk_state_store.py
├── test_risk_snapshot.py
├── test_risk_snapshot_immutability.py
├── test_risk_reservation_create.py
├── test_risk_reservation_release.py
├── test_risk_reservation_idempotency.py
├── test_consecutive_orders_reservation.py
├── test_order_service_risk_accept.py
├── test_order_service_risk_reject.py
├── test_order_service_risk_error.py
├── test_rejected_order_not_created.py
├── test_execution_not_called_on_reject.py
├── test_execution_not_called_on_error.py
├── test_risk_events_after_decision.py
├── test_ctx_risk_read_only.py
├── test_runtime_risk_isolation.py
├── test_cluster_risk_isolation.py
└── test_risk_determinism.py
```

---

# 42. 核心验收场景

## 42.1 Risk 在 Order 创建前执行

Risk REJECT 后：

```text
OrderManager 中不存在订单
ExecutionService 未被调用
```

## 42.2 Mandatory Rule

Cluster Profile 不能删除：

```text
OnlyInstrumentExistsRiskRule
OnlyOrderTypeSupportedRiskRule
OnlyKillSwitchRiskRule
```

## 42.3 Profile 差异

不同 Cluster 对相同请求可获得不同 Decision，但系统规则保持一致。

## 42.4 Fail Closed

Rule 抛异常时：

```text
Outcome = ERROR
Order 不创建
Execution 不调用
```

## 42.5 Reservation

同一个 `on_bar` 内连续提交订单，后续订单能看到前一订单的预占。

## 42.6 Scope 隔离

Cluster A 的预占不应错误计入 Cluster B 的 Cluster 限制，但应根据配置计入共享 Account 限制。

当前 Account Scope 尚未完整实现时，测试接口和隔离语义。

## 42.7 Snapshot

Risk Snapshot：

* 不可变；
* 使用 Runtime Clock；
* 版本稳定；
* 不暴露 RiskService；
* 不代表最终下单许可。

## 42.8 确定性

相同：

```text
RuntimeId
ClusterId
Risk Profile
Clock
Instrument
OrderRequest
已有订单
Reservation
```

运行 100 次，Decision、RuleId、Code、Event 和 Reservation 结果完全一致。

---

# 43. 策略回调暂不实现

本阶段明确不实现：

```text
OnlyCluster.on_risk_rejected()
OnlyCluster.on_risk_limit_triggered()
OnlyCluster.on_risk_state_changed()
OnlyCluster.on_risk_error()
```

也不实现 Runtime 对这些回调的调用。

但需要：

* 定义 Risk Event；
* 在 `docs/risk.md` 中记录未来回调方案；
* 确保 RiskService 不依赖 Cluster；
* 确保后续可以由 Runtime/ClusterManager 订阅 Risk Event 后调用策略回调；
* 不在本阶段扩大 Cluster API。

策略当前处理订单拒绝的主要方式是同步读取：

```python
result = ctx.orders.submit(request)

if not result.created:
    rejection = result.risk_rejection
```

Risk Event 仅用于系统通知和未来扩展。

---

# 44. 文档输出

创建或更新：

```text
docs/risk.md
docs/order.md
docs/runtime_context.md
docs/cluster.md
docs/event.md
docs/architecture.md
docs/testing.md
docs/architecture_principles.md
```

`docs/risk.md` 至少包括：

1. Risk 组件职责；
2. 三阶段 Risk 模型；
3. Rule 抽象；
4. Rule Scope；
5. Rule Mode；
6. Pipeline 顺序；
7. Risk Profile；
8. Mandatory Rules；
9. Cluster 自定义规则；
10. Decision；
11. Reject 与 Error；
12. Fail Closed；
13. Risk Context；
14. Risk Snapshot；
15. OrderService 集成；
16. Reservation；
17. Kill Switch；
18. Event；
19. Runtime/Cluster 隔离；
20. Account/Position Port；
21. 配置示例；
22. Demo；
23. 已知限制；
24. 未来策略 Risk 回调方案。

---

# 45. ADR

创建：

```text
docs/adr/0012-risk-pipeline-profile-and-reservation.md
```

至少记录：

## 背景

不同策略需要不同 Risk 策略，但系统级安全规则不能被策略关闭。订单最终审批必须发生在正式订单创建之前。

## 决策

* 每个 Runtime 一个 RiskService；
* Risk 采用 Rule 抽象和组合 Pipeline；
* Cluster 通过配置绑定 Risk Profile；
* Mandatory System Rules 不可关闭；
* on_bar 前更新 Risk Snapshot；
* 每次 Order Submit 都重新执行 Pre-Trade Risk；
* Risk Reject 不创建正式 Order；
* Risk Error 默认 Fail Closed；
* 订单通过后立即创建 Risk Reservation；
* Risk 使用函数调用，结果通知使用 Event；
* RiskService 不依赖 Cluster；
* 本阶段不实现策略 Risk 回调。

## 拒绝方案

* 每个策略实现一个巨大 RiskManager；
* 策略直接调用 Risk 并决定是否绕过；
* 只在 on_bar 前检查一次 Risk；
* 通过 EventBus 并行执行 Risk Rule；
* Risk Error 时默认允许订单；
* 静默修改订单数量和价格；
* Risk Reject 仍创建正式 Order；
* 不考虑活跃订单和预占额度。

---

# 46. Architecture Principles 新增规则

加入：

```text
Rule: 每个 Runtime 拥有独立 OnlyRiskService 和 Risk State。

Rule: Risk Rule 通过统一抽象接口实现，并通过组合形成 Profile。

Rule: Cluster 通过配置绑定 Risk Profile，不直接实例化 RiskManager。

Rule: Mandatory System Risk Rules 不可被 Cluster 关闭。

Rule: on_bar 前更新 Risk Snapshot，但每张订单仍必须执行最终 Pre-Trade Risk。

Rule: Risk Reject 时不创建正式 OnlyOrder。

Rule: Risk Error 默认 Fail Closed。

Rule: Risk Rule 不直接修改 Order、Position 或 Account。

Rule: RiskService 不直接依赖 Cluster。

Rule: 策略不能调用 RiskService.evaluate_order()。

Rule: 策略只能读取只读 Risk Snapshot。

Rule: Risk Command 和 Evaluation 使用函数调用。

Rule: Risk Event 只表达已经发生的 Risk 事实。

Rule: Risk EventBus 不承担 Rule 执行顺序。

Rule: Order 通过 Risk 后必须立即预占风险额度。

Rule: 风控不得默认静默修改订单数量和价格。
```

---

# 47. 实现顺序

严格按以下顺序：

1. 扫描当前 Risk 和 OrderService 实现；
2. 创建差距分析；
3. 定义 Risk Enum、ID、Decision；
4. 实现 OnlyRiskRule 接口；
5. 实现 OnlyRiskEvaluationContext；
6. 实现 Mandatory System Rules；
7. 完成 Mandatory Rule 测试；
8. 实现 Instrument/Market Rules；
9. 完成 Instrument Rule 测试；
10. 实现 Runtime/Cluster Rules；
11. 实现 RiskPipeline；
12. 完成顺序、拒绝和异常测试；
13. 实现 RiskProfile、Registry 和 Factory；
14. 完成不同 Cluster Profile 测试；
15. 实现 RiskStateStore；
16. 实现 RiskSnapshot；
17. 将 Risk Snapshot 接入 Context；
18. 实现 RiskReservationManager；
19. 完成连续订单预占测试；
20. 实现 OnlyRiskService；
21. 将 RiskService 接入 OnlyOrderService；
22. 实现 Reject/Error 审计对象；
23. 定义 Account/Position Risk Port；
24. 实现 Unavailable 占位 View；
25. 实现 Risk Event 和 Publisher Port；
26. 验证 Reject/Error 不创建 Order；
27. 验证 Reject/Error 不调用 Execution；
28. 创建 Demo；
29. 更新文档；
30. 创建 ADR；
31. 运行全部测试；
32. 输出验收报告。

---

# 48. 验收标准

完成后必须满足：

* 每个 Runtime 有独立 RiskService；
* Risk State 不跨 Runtime；
* 不同 Cluster 可配置不同 Profile；
* Mandatory Rule 不可删除；
* Rule API 和 Decision API 统一；
* Risk Rule 不返回普通 bool；
* Pipeline 顺序确定；
* Risk Snapshot 在 on_bar 前可准备；
* Risk Snapshot 不代表最终订单许可；
* 每次 submit 都执行 Pre-Trade Risk；
* Risk Reject 不创建 Order；
* Risk Error 不创建 Order；
* Risk Reject/Error 不调用 Execution；
* Risk Error 默认 Fail Closed；
* Profile 加载失败时 Cluster 不可启动；
* 策略不能调用 RiskService；
* 策略只能读取 Risk Snapshot；
* 同一回调连续订单正确应用 Reservation；
* Reservation 创建和释放幂等；
* 不同 Cluster State 正确隔离；
* Instrument 和 Market Rule 不硬编码市场判断；
* Account/Position 缺失不会被伪造为无限额度；
* Event 在 Decision 形成后发布；
* EventBus 不执行 Rule；
* 相同输入结果确定；
* 文档、测试、Demo、ADR 完整；
* 没有实现策略 `on_risk_xxx` 回调。

---

# 49. 一票否决项

存在以下任一项，不得标记完成：

* 策略可以关闭 Mandatory Risk Rule；
* 策略可以调用 `evaluate_order()`；
* 只在 on_bar 前检查一次 Risk，submit 时不再检查；
* Risk Rule 通过 EventBus 并行审批订单；
* Risk Error 后仍创建或提交订单；
* Risk Reject 后仍创建正式 Order；
* Risk Reject 后仍调用 ExecutionService；
* Rule 抛异常未被捕获；
* Rule 异常默认 ACCEPT；
* 不同 Runtime 共享可变 Risk State；
* 不同 Cluster 错误共享有状态计数器；
* 同一回调连续订单不考虑 Reservation；
* Risk 静默缩量或改价；
* Account 数据不可用时假设资金无限；
* Position 数据不可用时假设持仓充足；
* Cluster Profile 可以覆盖或移除系统 Kill Switch；
* RiskService 直接持有 Cluster 实例；
* Rule 直接修改 OrderManager；
* Event 发布在 Decision 之前；
* 通过 Risk Event Handler 决定是否创建 Order；
* 相同输入产生不同结果；
* 实现了未经要求的策略 Risk 回调。

---

# 50. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Risk 组件边界
三阶段 Risk 模型
Risk Rule 抽象接口
Rule Scope
Rule Mode
Mandatory Rules
Instrument/Market Rules
Runtime/Cluster Rules
Risk Pipeline 顺序
Risk Decision 设计
Reject 与 Error 区别
Fail Closed 行为
Risk Profile 配置
自定义 Rule 加载
Risk Context
Risk Snapshot
OrderService 接入点
Risk Reservation 设计
连续订单预占结果
Kill Switch 设计
Account/Position Port
Risk Event 设计
测试通过数
测试失败数
测试跳过数
确定性测试结果
Demo 运行结果
已知限制
一票否决项
是否建议进入 PositionManager
是否建议进入 AccountManager
是否建议进入 ExecutionSimulator
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Risk Rule
Risk Pipeline
Risk Profile
Risk Service
Risk State
Risk Snapshot
Risk Reservation
Risk Context View
OrderService Risk 集成
Risk Event
Account/Position Risk Port
Placeholder View
测试
Demo
文档
ADR
```

不要在本任务中实现：

* 策略 on_risk_xxx 回调；
* Runtime 调用 Risk 策略回调；
* 真实 AccountManager；
* 真实 PositionManager；
* TradeManager；
* ExecutionProcessor；
* 撮合引擎；
* 真实券商 Risk；
* 自动强平；
* 自动撤单；
* Web；
* 分布式 Risk；
* 真实交易。
