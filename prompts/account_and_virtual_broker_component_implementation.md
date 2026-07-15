# OnlyAlpha AccountManager、Broker 通用接口与 Virtual Broker 组件实现任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的账户真实账、通用券商接口以及可供回测和测试使用的虚拟券商组件。

当前已经实现或规划完成：

```text
Domain
Clock
EventBus
Runtime
RuntimeContext
Cluster
MarketData Pipeline
Snapshot
Order
Risk
Position
Position Allocation
Strategy Ledger
```

本阶段需要建立：

```text
OnlyAccountManager
    维护 OnlyAlpha Runtime 内的账户真实资金状态

OnlyBrokerGateway Ports
    定义不同券商统一的连接、交易、查询和回报接口

OnlyVirtualBrokerGateway
    模拟真实券商的订单、成交、账户和持仓行为

OnlyMatchingEngine
    独立决定虚拟订单如何成交

OnlyAccountReconciliationService
    对比本地账户状态与券商账户快照
```

总体结构：

```text
OnlyRuntime
├── OnlyOrderManager
├── OnlyRiskService
├── OnlyPositionManager
├── OnlyPositionAllocationManager
├── OnlyStrategyLedgerManager
├── OnlyAccountManager
├── OnlyExecutionService
├── OnlyBrokerGateway
│   └── OnlyVirtualBrokerGateway
└── OnlyMatchingEngine
```

必须明确区分：

```text
OnlyAccountManager
    OnlyAlpha 本地账户真实状态

OnlyVirtualBrokerGateway
    模拟外部券商状态

OnlyStrategyLedgerManager
    Cluster 内部虚拟资金与收益归因
```

三者不得共享同一份可变状态。

---

# 2. 核心架构原则

必须遵循：

```text
账户真实账与策略虚拟账分离

AccountManager 不直接依赖具体券商 SDK

BrokerGateway 不直接修改 AccountManager

Virtual Broker 拥有独立券商侧账户状态

本地状态与券商状态通过 Snapshot、Update 和 Reconciliation 交互

券商提交成功不等于订单 Accepted

撤单请求成功不等于订单 Cancelled

券商异步回报必须进入 Runtime Inbound Queue

Manager 状态修改使用函数调用

状态成功变化后发布事实 Event

EventBus 不承担账户、订单、持仓或成交状态机

所有时间来自 Runtime Clock

回测、Paper 和 Live 使用统一 Broker Port

所有新增实现必须接入完整 Vertical Slice
```

---

# 3. 本阶段交付范围

本任务分为两个内部阶段。

## 3.1 阶段一：Account Domain、AccountManager 和 Broker Ports

实现：

```text
OnlyAccount
OnlyAccountId
OnlyAccountType
OnlyAccountStatus
OnlyAccountConfig

OnlyAccountBalance
OnlyAccountCashBalance
OnlyAccountSnapshot
OnlyAccountMutationResult

OnlyAccountManager
OnlyAccountQueryService
OnlyAccountQueryView
OnlyAccountRiskView

OnlyAccountCashChange
OnlyAccountFee
OnlyAccountValuation
OnlyAccountReservation
OnlyAccountReservationManager

OnlyBrokerGatewayId
OnlyBrokerAccountSnapshot
OnlyBrokerBalanceSnapshot
OnlyBrokerPositionSnapshot
OnlyBrokerOrderSnapshot
OnlyBrokerTradeSnapshot

OnlyBrokerConnectionPort
OnlyBrokerTradingPort
OnlyBrokerAccountPort
OnlyBrokerPositionPort
OnlyBrokerOrderQueryPort
OnlyBrokerTradeQueryPort

OnlyBrokerGateway
OnlyBrokerCapability
OnlyBrokerCapabilities

OnlyAccountReconciliationService
OnlyAccountDifference
OnlyAccountConflict
OnlyAccountAuthorityPolicy
OnlyAccountReconciliationSeverity
OnlyAccountReconciliationAction

OnlyAccountEvent
OnlyAccountEventPublisher
OnlyAccountRepository
```

## 3.2 阶段二：Virtual Broker 与最小 Matching Engine

实现：

```text
OnlyVirtualBrokerGateway
OnlyVirtualBrokerConfig
OnlyVirtualBrokerAccountStore
OnlyVirtualBrokerOrderStore
OnlyVirtualBrokerTradeStore

OnlyMatchingEngine
OnlyMatchingResult
OnlyImmediateMatchingEngine
OnlyNextBarMatchingEngine

OnlyCommissionModel
OnlyFixedCommissionModel
OnlyCnEquityCommissionModel

OnlySlippageModel
OnlyNoSlippageModel
OnlyFixedSlippageModel

OnlyLatencyModel
OnlyZeroLatencyModel
OnlyFixedLatencyModel

OnlyBrokerInboundUpdate
OnlyBrokerConnectionUpdate
OnlyBrokerOrderAcceptedUpdate
OnlyBrokerOrderRejectedUpdate
OnlyBrokerOrderCancelledUpdate
OnlyBrokerTradeUpdate
OnlyBrokerAccountUpdate
OnlyBrokerPositionUpdate

OnlyVirtualBrokerScheduler
OnlyVirtualBrokerUpdateQueue
```

---

# 4. 本阶段暂不实现

本任务不要实现：

```text
真实券商 SDK
XTP
QMT
CTP
IBKR
Binance
OKX
融资融券
期货保证金
期权保证金
复杂多币种换算
借券
Funding Rate
利息
分红
公司行动
自动强平
真实网络连接
高可用和分布式 Broker
Web
数据库具体实现
Production 级 Matching Engine
完整订单簿仿真
盘口排队模型
复杂成交概率模型
```

但接口必须允许未来增加：

```text
OnlyXtpBrokerGateway
OnlyQmtBrokerGateway
OnlyCtpBrokerGateway
OnlyIbkrBrokerGateway
OnlyCryptoBrokerGateway
```

而不修改上层 Order、Risk、Position、Ledger 和 Account API。

---

# 5. 执行前必须阅读

必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/event.md
docs/runtime.md
docs/runtime_context.md
docs/cluster.md
docs/market_data_pipeline.md
docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/integration_vertical_slice.md
docs/testing.md
docs/coding_style.md
docs/architecture_principles.md
docs/adr/
```

同时分析旧工程：

```text
/home/zongxin/workspace/MyQuant
```

重点了解：

* 券商连接；
* 账户查询；
* 持仓查询；
* 下单；
* 撤单；
* 订单回报；
* 成交回报；
* 券商订单 ID；
* 账户资金冻结；
* 持仓冻结；
* 回测成交；
* 实盘和回测接口差异；
* 启动同步；
* 重连；
* 对账。

只参考现有行为，不直接复制旧架构。

---

# 6. 先创建差距分析

创建：

```text
docs/account_broker_component_analysis.md
```

至少分析：

## 6.1 当前账户模型

| 当前类型 | 职责 | 问题 | 目标类型 |
| ---- | -- | -- | ---- |

## 6.2 当前券商调用链

画出：

```text
Cluster
→ Order
→ Broker
→ Order Callback
→ Trade Callback
→ Position
→ Account
```

检查：

* 是否策略直接调用券商 SDK；
* 是否 OrderManager 直接调用券商 SDK；
* 是否 Broker 回调直接修改 Manager；
* 是否账户状态和策略 Ledger 混用；
* 是否实盘和回测使用不同接口；
* 是否 Submit 成功就被当成 Accepted；
* 是否 Cancel 返回成功就被当成 Cancelled；
* 是否 Broker Snapshot 静默覆盖本地状态；
* 是否 Virtual Broker 与 AccountManager 共用状态；
* 是否缺少券商能力声明；
* 是否缺少主动查询和异步回报区分。

## 6.3 当前依赖关系

检查是否存在：

```text
Account → StrategyLedger
Broker → AccountManager
Broker → PositionManager
Broker → OrderManager
```

等错误方向。

先输出分析，再开始修改。

---

# 7. AccountManager 的定位

`OnlyAccountManager` 是：

> 当前 Runtime 内账户资金、余额、权益和本地账户状态的唯一可信来源。

每个 Runtime 一个：

```text
OnlyRuntime
└── OnlyAccountManager
```

一个 AccountManager 可以管理多个账户。

不同 Runtime 不共享任何可变账户状态。

AccountManager 不拥有：

* Cluster 虚拟资金；
* Cluster 收益；
* Cluster Ledger；
* Broker SDK；
* 网络连接；
* Matching Engine。

---

# 8. StrategyLedger 与 Account 的边界

必须固定：

```text
OnlyAccountManager
    账户真实现金、冻结、权益和券商侧状态

OnlyStrategyLedgerManager
    Cluster 虚拟资金、收益、费用和净值归因
```

示例：

```text
Broker Account Equity = 1,000,000 CNY

Cluster A Ledger Capital = 600,000 CNY
Cluster B Ledger Capital = 400,000 CNY
```

这不代表券商有两个子账户。

禁止：

* 将 Cluster 虚拟现金写入 Account；
* 使用 Account 余额直接代替 Cluster 可用资金；
* 将 StrategyLedger Snapshot 当 Broker Account Snapshot；
* 将账户总收益按比例分给 Cluster。

---

# 9. Account 第一版范围

第一版完整支持：

```text
单币种
CNY
现金账户
Long-only 股票/ETF
现金余额
可用现金
冻结现金
待结算现金
累计手续费
已实现盈亏
未实现盈亏
账户持仓市值
账户权益
账户状态
账户 Snapshot
账户 Reservation
Broker Account Snapshot
账户对账
```

预留但不完整实现：

```text
多币种
保证金
融资融券
负债
借贷
期货
期权
Crypto Margin
```

对于不适用字段，使用明确状态：

```text
NOT_APPLICABLE
UNAVAILABLE
UNSUPPORTED
```

不要简单填零伪装已支持。

---

# 10. OnlyAccount 核心字段

建议：

```text
account_id
runtime_id
gateway_id
account_type
base_currency
status

cash_balance
available_cash
frozen_cash
unsettled_cash

position_market_value
realized_pnl
unrealized_pnl
fees

equity
liabilities
margin_used
margin_available

created_at
updated_at
valuation_time

version
last_external_sequence
quality_flags
metadata
```

建议核心状态：

```text
cash_balance
frozen_cash
unsettled_cash
fees
realized_pnl
status
```

建议派生或估值状态：

```text
available_cash
position_market_value
unrealized_pnl
equity
margin_available
```

禁止维护互相矛盾的多个可写真值。

---

# 11. Account 内部可变与外部 Snapshot

采用：

> 内部受控可变实体，外部只暴露 immutable Snapshot。

禁止：

```python
account.cash_balance = ...
account.available_cash = ...
account.equity = ...
account.status = ...
```

必须通过：

```python
account.apply_cash_change(...)
account.reserve_cash(...)
account.release_cash(...)
account.apply_fee(...)
account.apply_trade_cash_flow(...)
account.apply_valuation(...)
account.start_reconciliation(...)
account.apply_reconciliation(...)
account.close(...)
```

所有修改返回：

```text
OnlyAccountMutationResult
```

外部只获得：

```text
OnlyAccountSnapshot
```

---

# 12. AccountManager 推荐接口

```python
class OnlyAccountManager:
    def create_account(
        self,
        config: OnlyAccountConfig,
    ) -> OnlyAccountSnapshot:
        ...

    def apply_cash_change(
        self,
        change: OnlyAccountCashChange,
    ) -> OnlyAccountMutationResult:
        ...

    def reserve_cash(
        self,
        reservation: OnlyAccountReservation,
    ) -> OnlyAccountMutationResult:
        ...

    def release_cash(
        self,
        reservation_id: OnlyAccountReservationId,
    ) -> OnlyAccountMutationResult:
        ...

    def consume_cash_reservation(
        self,
        reservation_id: OnlyAccountReservationId,
        amount: OnlyMoney,
    ) -> OnlyAccountMutationResult:
        ...

    def apply_fee(
        self,
        fee: OnlyAccountFee,
    ) -> OnlyAccountMutationResult:
        ...

    def apply_trade_cash_flow(
        self,
        cash_flow: OnlyAccountTradeCashFlow,
    ) -> OnlyAccountMutationResult:
        ...

    def apply_valuation(
        self,
        valuation: OnlyAccountValuation,
    ) -> OnlyAccountMutationResult:
        ...

    def get_snapshot(
        self,
        account_id: OnlyAccountId,
    ) -> OnlyAccountSnapshot:
        ...

    def list_accounts(self) -> tuple[OnlyAccountSnapshot, ...]:
        ...
```

禁止无语义接口：

```text
set_balance
set_equity
set_available
replace_state
```

---

# 13. Account 现金不变量

至少保证：

```text
cash_balance >= 0
frozen_cash >= 0
unsettled_cash >= 0
available_cash >= 0
```

现金账户第一版：

```text
available_cash
=
cash_balance
- frozen_cash
```

如果 `unsettled_cash` 不允许立即使用，则：

```text
available_cash
=
cash_balance
- frozen_cash
- unavailable_unsettled_cash
```

具体语义由 AccountRule 或 SettlementRule 决定。

禁止默认负现金。

---

# 14. Broker Port 拆分

不要建立单个巨大接口。

定义：

```text
OnlyBrokerConnectionPort
OnlyBrokerTradingPort
OnlyBrokerAccountPort
OnlyBrokerPositionPort
OnlyBrokerOrderQueryPort
OnlyBrokerTradeQueryPort
```

通过组合形成：

```python
class OnlyBrokerGateway(
    OnlyBrokerConnectionPort,
    OnlyBrokerTradingPort,
    OnlyBrokerAccountPort,
    OnlyBrokerPositionPort,
    OnlyBrokerOrderQueryPort,
    OnlyBrokerTradeQueryPort,
):
    ...
```

各具体 Gateway 可以声明自己支持的能力。

---

# 15. Broker Capability

定义：

```text
OnlyBrokerCapability
OnlyBrokerCapabilities
```

至少包括：

```text
CONNECT
AUTHENTICATE
SUBMIT_ORDER
CANCEL_ORDER
QUERY_ACCOUNT
QUERY_BALANCES
QUERY_POSITIONS
QUERY_OPEN_ORDERS
QUERY_ORDERS
QUERY_TRADES
PUSH_ORDER_UPDATES
PUSH_TRADE_UPDATES
PUSH_ACCOUNT_UPDATES
PUSH_POSITION_UPDATES
MARKET_ORDER
LIMIT_ORDER
PARTIAL_FILL
```

运行时必须检查 Capability。

如果某 Gateway 不支持某能力，返回明确：

```text
UNSUPPORTED_CAPABILITY
```

不要抛普通 `NotImplementedError` 后继续运行。

---

# 16. Broker Connection Port

```python
class OnlyBrokerConnectionPort(Protocol):
    def connect(self) -> OnlyBrokerConnectionResult:
        ...

    def authenticate(self) -> OnlyBrokerAuthenticationResult:
        ...

    def disconnect(self) -> OnlyBrokerDisconnectResult:
        ...

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot:
        ...
```

连接状态至少：

```text
DISCONNECTED
CONNECTING
CONNECTED
AUTHENTICATING
READY
RECONNECTING
FAILED
```

---

# 17. Broker Trading Port

```python
class OnlyBrokerTradingPort(Protocol):
    def submit_order(
        self,
        request: OnlyBrokerOrderRequest,
    ) -> OnlyBrokerOrderSubmitResult:
        ...

    def cancel_order(
        self,
        request: OnlyBrokerCancelRequest,
    ) -> OnlyBrokerCancelResult:
        ...
```

`submit_order()` 返回只表示：

```text
请求是否成功进入 Broker 接口
```

不表示：

```text
订单已 Accepted
```

推荐结果：

```text
request_received
gateway_request_id
client_order_id
immediate_error
```

`cancel_order()` 同理。

---

# 18. Broker Query Ports

## Account

```python
query_account(account_id)
query_balances(account_id)
```

## Position

```python
query_positions(account_id)
```

## Order

```python
query_open_orders(account_id)
query_orders(account_id, query)
```

## Trade

```python
query_trades(account_id, query)
```

所有返回必须是 OnlyAlpha 标准 DTO，不得向上层暴露 SDK 原始结构。

---

# 19. Broker Update 模型

定义：

```text
OnlyBrokerInboundUpdate
OnlyBrokerConnectionUpdate
OnlyBrokerOrderAcceptedUpdate
OnlyBrokerOrderRejectedUpdate
OnlyBrokerOrderCancelledUpdate
OnlyBrokerTradeUpdate
OnlyBrokerAccountUpdate
OnlyBrokerPositionUpdate
```

字段至少包括：

```text
gateway_id
account_id
update_id
source_sequence
ts_event
ts_init
correlation_id
causation_id
quality_flags
metadata
```

订单和成交 Update 还必须包含标准化 ID 和业务字段。

---

# 20. Broker 回调进入 Runtime

正确链路：

```text
Broker / Virtual Broker
→ 标准化 OnlyBrokerInboundUpdate
→ Runtime Inbound Queue
→ Runtime 单写入线程
→ Update Processor / ExecutionProcessor
→ Manager 函数调用
→ 事实 Event
```

禁止：

```text
Broker Gateway
→ AccountManager.apply_xxx() 直接调用

Broker Gateway
→ PositionManager.apply_xxx() 直接调用

Broker Gateway
→ OrderManager.apply_xxx() 直接调用
```

Gateway 不认识 Manager。

---

# 21. Virtual Broker 的定位

`OnlyVirtualBrokerGateway` 是：

> 一个实现标准 Broker Ports 的虚拟外部券商。

它不是简单 Fake。

它必须模拟：

* 独立券商账户状态；
* 独立券商订单状态；
* 独立券商成交记录；
* 异步回报；
* 主动查询；
* 连接和认证状态；
* 下单接收；
* 订单接受或拒绝；
* 成交；
* 撤单；
* 账户冻结；
* 持仓冻结；
* Broker Snapshot。

它不得直接复用 `OnlyAccountManager`、`OnlyPositionManager` 或 `OnlyOrderManager` 的内部数据。

---

# 22. Virtual Broker 独立状态

定义：

```text
OnlyVirtualBrokerAccountStore
OnlyVirtualBrokerOrderStore
OnlyVirtualBrokerTradeStore
```

必须与本地 Manager 状态物理分离。

结构：

```text
Virtual Broker State
    模拟外部券商真值

Runtime Manager State
    OnlyAlpha 本地状态

Reconciliation Service
    对比两者
```

这样才能测试：

* 延迟；
* 丢失回报；
* 重复回报；
* 乱序；
* Broker/Local 冲突；
* 重启恢复；
* Reconciliation。

---

# 23. Virtual Broker 第一版行为

完整支持：

```text
单账户
单币种 CNY
现金账户
股票/ETF Long-only
MARKET
LIMIT
订单提交
订单接受
订单拒绝
部分成交
完全成交
撤单
撤单失败
现金冻结
持仓冻结
账户查询
持仓查询
订单查询
成交查询
```

暂不支持：

```text
期货
期权
Short
融资融券
保证金
复杂盘口
真实交易所撮合
```

---

# 24. Matching Engine 与 Broker 分离

必须定义：

```text
OnlyMatchingEngine
```

不要把撮合逻辑写死在 `OnlyVirtualBrokerGateway` 中。

Gateway 负责：

* 接收请求；
* 生成 Broker Order；
* 调度更新；
* 维护账户和订单存储；
* 调用 Matching Engine。

Matching Engine 负责：

* 判断能否成交；
* 成交数量；
* 成交价格；
* 部分成交；
* 成交时点。

第一版实现：

```text
OnlyImmediateMatchingEngine
OnlyNextBarMatchingEngine
```

至少选一个作为默认，并完整测试。

---

# 25. Immediate Matching

用于单元测试和最小集成场景。

行为：

```text
MARKET
    立即按当前参考价成交

LIMIT
    如果当前价格满足条件则立即成交
    否则保持 Accepted
```

必须明确价格来源：

```text
OnlyMarketPriceView
```

不得使用随机价格或系统时间。

---

# 26. Next Bar Matching

用于回测 Vertical Slice。

示例规则：

```text
订单在 Bar N 提交
在 Bar N+1 使用 OHLC 检查是否成交
```

建议：

```text
BUY LIMIT
    当 next_bar.low <= limit_price 时可成交

SELL LIMIT
    当 next_bar.high >= limit_price 时可成交
```

成交价格策略必须明确：

```text
LIMIT_PRICE
OPEN_PRICE_WITH_LIMIT
CONFIGURABLE
```

第一版选择一种并在文档中固定。

不要暗中使用未来数据。

---

# 27. Commission Model

定义：

```text
OnlyCommissionModel
```

第一版实现：

```text
OnlyFixedCommissionModel
OnlyCnEquityCommissionModel
```

A 股模型至少预留：

```text
commission_rate
minimum_commission
stamp_duty_rate
transfer_fee_rate
```

具体默认费率不得硬编码成不可配置常量。

测试必须显式传入配置。

---

# 28. Slippage Model

定义：

```text
OnlySlippageModel
```

第一版：

```text
OnlyNoSlippageModel
OnlyFixedSlippageModel
```

所有滑点使用精确 Price/Rate 类型，不使用裸 float。

---

# 29. Latency Model

定义：

```text
OnlyLatencyModel
```

第一版：

```text
OnlyZeroLatencyModel
OnlyFixedLatencyModel
```

至少支持：

```text
submit_latency
acceptance_latency
fill_latency
cancel_latency
query_latency
```

时间必须使用 Runtime Clock。

不得调用：

```python
datetime.now()
time.time()
```

---

# 30. Virtual Broker Scheduler

虚拟券商不能通过真实 sleep 模拟延迟。

定义：

```text
OnlyVirtualBrokerScheduler
```

使用：

```text
Runtime Clock
Runtime Timer
Deterministic Queue
```

调度：

```text
OrderAcceptedUpdate
TradeUpdate
CancelUpdate
AccountUpdate
PositionUpdate
```

回测中必须确定性执行。

---

# 31. Virtual Broker Submit 流程

推荐：

```text
OnlyBrokerTradingPort.submit_order()
    ↓
检查 Connection/Authentication
    ↓
检查 Capability
    ↓
检查请求结构
    ↓
生成 Gateway Request Id
    ↓
记录 Broker Order
    ↓
返回 request_received=True
    ↓
调度 Accepted 或 Rejected Update
    ↓
Matching Engine
    ↓
调度 Trade Update
```

提交返回不得直接修改本地 Order 状态。

---

# 32. Virtual Broker Cancel 流程

```text
cancel_order()
    ↓
检查 Broker Order
    ↓
检查是否可撤
    ↓
返回 cancel_request_received
    ↓
异步调度 Cancelled 或 CancelRejected Update
```

不能在方法返回时直接表示订单已经取消。

---

# 33. Virtual Broker 资金冻结

买单 Accepted 后，虚拟券商应根据配置冻结：

```text
estimated_notional
+
estimated_fee
```

卖单 Accepted 后冻结券商侧可卖持仓。

必须区分：

```text
Virtual Broker Frozen State
Local Account Reservation
Local Position Reservation
Strategy Cash Reservation
Risk Reservation
```

这些是不同状态。

不得共用同一个 Reservation 对象。

---

# 34. Broker Account Snapshot

定义：

```text
OnlyBrokerAccountSnapshot
```

字段至少：

```text
gateway_id
account_id
account_type
base_currency

cash_balance
available_cash
frozen_cash
unsettled_cash

position_market_value
equity

realized_pnl
unrealized_pnl
fees

margin_used
margin_available

snapshot_time
source_sequence
quality_flags
metadata
```

现金账户中保证金字段应标记：

```text
NOT_APPLICABLE
```

---

# 35. Account Valuation

定义：

```text
OnlyAccountValuationService
```

读取：

```text
OnlyPositionManager 的账户级 Position Snapshot
OnlyPositionValuation
Account Cash State
```

计算：

```text
equity
=
cash_balance
+
position_market_value
-
liabilities
```

第一版：

```text
liabilities = 0
```

但必须标记现金账户模式，而不是认为所有账户都无负债。

不得使用 Cluster Allocation 计算账户总权益。

---

# 36. Account Risk View

替换当前占位：

```text
OnlyUnavailableAccountRiskView
```

提供：

```text
OnlyAccountRiskView
```

至少支持：

```text
account_status
cash_balance
available_cash
frozen_cash
equity
position_market_value
realized_pnl
unrealized_pnl
fees
reconciliation_status
```

Risk 可用于：

```text
OnlyAvailableBalanceRiskRule
OnlyMinimumAccountEquityRiskRule
OnlyAccountStatusRiskRule
OnlyAccountReconciliationRiskRule
```

当 Account 为：

```text
RECONCILING
SUSPENDED
ERROR
```

Risk 默认 Fail Closed。

---

# 37. Account Reconciliation

定义：

```text
OnlyAccountReconciliationService
OnlyAccountDifference
OnlyAccountConflict
OnlyAccountAuthorityPolicy
OnlyAccountReconciliationResult
```

比较：

```text
cash_balance
available_cash
frozen_cash
unsettled_cash
equity
position_market_value
realized_pnl
unrealized_pnl
fees
```

字段使用不同 Authority。

---

# 38. Account Authority Policy

建议：

```text
Live Runtime:
    Broker cash/equity 是外部权威
    Local-only reservation 是本地权威

Backtest/Paper:
    Virtual Broker 是模拟外部权威
    本地 Manager 通过 Update 同步

Strategy Ledger:
    永远是 Cluster 本地归因账
```

不能给整个 Account 简单设置一个统一权威。

---

# 39. 可用资金冲突

如果：

```text
local_available = 100000
broker_available = 80000
```

冲突期间：

```text
effective_available
=
min(local_available, broker_available)
-
local_only_reservations_not_reflected_by_broker
```

必须避免已经反映在 Broker Snapshot 中的冻结被重复扣减。

同时：

* 标记 conflict；
* 触发 Reconciliation；
* 不永久使用 `min()` 掩盖问题；
* 严重冲突进入 `BLOCK_ACCOUNT`。

---

# 40. Reconciliation Severity

定义：

```text
INFO
WARNING
BLOCK_ACCOUNT
FAIL_RUNTIME
```

示例：

```text
INFO
    Broker Fee 与 Local Fee 有微小算法差异

WARNING
    Broker Frozen Cash 更新延迟

BLOCK_ACCOUNT
    Cash 或 Equity 出现无法解释差异

FAIL_RUNTIME
    AccountId 错误、快照损坏或状态不可解析
```

---

# 41. ctx.accounts 接口

策略统一通过：

```text
ctx.accounts
```

读取只读账户视图。

建议：

```python
ctx.accounts.current()
ctx.accounts.get(account_id)
```

返回：

```text
OnlyAccountSnapshot
```

策略不能：

```text
reserve_cash
release_cash
apply_fee
apply_trade
apply_broker_snapshot
start_reconciliation
```

普通 Cluster 默认只能读取授权账户。

---

# 42. Broker 配置

建议：

```yaml
broker:
  type: OnlyVirtualBrokerGateway
  gateway_id: virtual_cn_equity

  accounts:
    - account_id: virtual_account_001
      account_type: CASH
      base_currency: CNY
      initial_cash: "1000000"

  matching:
    type: NEXT_BAR
    fill_price_policy: LIMIT_OR_OPEN

  latency:
    type: FIXED
    submit_ms: 1
    acceptance_ms: 2
    fill_ms: 5
    cancel_ms: 2

  slippage:
    type: NONE

  commission:
    type: CN_EQUITY
    commission_rate: "0.0003"
    minimum_commission: "5"
    stamp_duty_rate: "0.0005"

  rules:
    long_only: true
```

配置必须有类型校验。

---

# 43. 推荐目录

```text
src/onlyalpha/account/
├── __init__.py
├── identifiers.py
├── enums.py
├── configs.py
├── balances.py
├── reservations.py
├── cash_changes.py
├── fees.py
├── valuations.py
├── entities.py
├── snapshots.py
├── results.py
├── manager.py
├── queries.py
├── views.py
├── risk_view.py
├── reconciliation.py
├── authority.py
├── repositories.py
├── events.py
├── publisher.py
├── serialization.py
└── exceptions.py

src/onlyalpha/broker/
├── __init__.py
├── identifiers.py
├── enums.py
├── capabilities.py
├── ports/
│   ├── connection.py
│   ├── trading.py
│   ├── account.py
│   ├── position.py
│   ├── order_query.py
│   └── trade_query.py
├── gateway.py
├── requests.py
├── results.py
├── snapshots.py
├── updates.py
├── queries.py
└── exceptions.py

src/onlyalpha/virtual_broker/
├── __init__.py
├── config.py
├── gateway.py
├── account_store.py
├── order_store.py
├── trade_store.py
├── scheduler.py
├── update_queue.py
├── matching/
│   ├── base.py
│   ├── immediate.py
│   └── next_bar.py
├── commission/
│   ├── base.py
│   ├── fixed.py
│   └── cn_equity.py
├── slippage/
│   ├── base.py
│   ├── none.py
│   └── fixed.py
└── latency/
    ├── base.py
    ├── zero.py
    └── fixed.py
```

根据现有结构调整，但职责不能混合。

---

# 44. 单元测试要求

至少新增：

```text
tests/account/
tests/broker/
tests/virtual_broker/
```

## Account

```text
test_account_creation
test_account_cash_balance
test_account_reservation
test_account_fee
test_account_valuation
test_account_snapshot
test_account_runtime_isolation
test_account_reconciliation
test_account_risk_view
test_ctx_accounts_read_only
test_account_serialization
test_account_determinism
```

## Broker Ports

```text
test_broker_capabilities
test_broker_submit_semantics
test_broker_cancel_semantics
test_broker_snapshot_models
test_broker_update_models
test_unsupported_capability
```

## Virtual Broker

```text
test_virtual_broker_connect
test_virtual_broker_authenticate
test_virtual_broker_submit
test_virtual_broker_accept_update
test_virtual_broker_reject_update
test_virtual_broker_partial_fill
test_virtual_broker_full_fill
test_virtual_broker_cancel
test_virtual_broker_cancel_failure
test_virtual_broker_account_query
test_virtual_broker_position_query
test_virtual_broker_order_query
test_virtual_broker_trade_query
test_virtual_broker_cash_freeze
test_virtual_broker_position_freeze
test_virtual_broker_duplicate_update
test_virtual_broker_out_of_order_update
test_virtual_broker_latency
test_virtual_broker_clock_usage
test_virtual_broker_determinism
```

---

# 45. 强制完整连通测试

本任务必须严格遵守：

```text
AGENTS.md
docs/integration_vertical_slice.md
scripts/run_component_validation.sh
```

本次不只实现 Account 和 Virtual Broker。

必须把当前所有已经实现的组件全部串联。

统一 Vertical Slice：

```text
OnlyBacktestRuntime
    ↓
OnlyBacktestClock
    ↓
1m Bar
    ↓
MarketData Pipeline
    ↓
3m Bar / Indicator
    ↓
Snapshot
    ↓
Cluster.on_bar()
    ↓
ctx.orders.submit()
    ↓
RiskService
    ↓
OrderManager
    ↓
ExecutionService
    ↓
VirtualBrokerGateway
    ↓
MatchingEngine
    ↓
Broker Update Queue
    ↓
Order Update
    ↓
PositionManager
    ↓
PositionAllocationManager
    ↓
StrategyLedgerManager
    ↓
AccountManager
    ↓
Risk State Update
    ↓
事实 Event
    ↓
Final Snapshot / Report
```

不得再依赖手工直接注入 Manager 内部状态完成主场景。

允许在专门错误测试中注入标准化 Broker Update，但正常完整场景必须通过 Virtual Broker 自动产生回报。

---

# 46. Integration Environment 更新

更新：

```text
OnlyIntegrationEnvironment
```

加入：

```text
account_manager
account_query_view
virtual_broker_gateway
virtual_broker_account_store
matching_engine
commission_model
slippage_model
latency_model
broker_update_queue
account_reconciliation_service
```

所有历史组件必须继续使用正式装配关系。

---

# 47. 新增 Integration Scenarios

在：

```text
examples/integration_demo/scenarios/
tests/integration/
```

新增至少以下场景。

## 47.1 Account 初始化

```text
Runtime 启动
→ Virtual Broker 创建账户
→ AccountManager 创建本地账户
→ 查询 Broker Snapshot
→ Reconciliation 一致
```

## 47.2 完整买入链路

```text
Bar
→ Cluster Buy
→ Risk ACCEPT
→ Order CREATED/SUBMITTED
→ Virtual Broker ACCEPTED
→ Matching Engine Fill
→ Order FILLED
→ Position 增加
→ Allocation 增加
→ Strategy Ledger 记账
→ Account 现金减少
→ Account Position Value 增加
→ Equity 正确
```

## 47.3 部分成交

验证：

* Broker Order 部分成交；
* Order 状态；
* Position；
* Allocation；
* Ledger；
* Account；
* Reservation；
* Fee。

## 47.4 撤单

验证：

```text
Accepted 未成交订单
→ Cancel Request
→ Broker Cancelled Update
→ Order CANCELLED
→ Cash/Position Reservation 释放
→ Account 与 Ledger 可用资金恢复
```

## 47.5 T+1

买入后：

```text
Position unsettled
同日卖出 Risk REJECT
下一 Trading Day Settlement
卖出允许
```

## 47.6 多 Cluster 共享账户

A、B 共用 Virtual Broker Account。

验证：

* Account 是合并真实账；
* Position 是账户总仓位；
* Allocation 分开；
* Ledger 分开；
* Reservation 竞争正确；
* Cluster 不能操作其他 Cluster Allocation。

## 47.7 Broker/Local 冲突

故意制造：

```text
Virtual Broker cash != local account cash
```

验证：

* Reconciliation Difference；
* Severity；
* Risk Fail Closed；
* 不静默覆盖。

## 47.8 重复和乱序 Broker Update

验证：

* 重复 Fill 不重复计入；
* 旧 Update 不回退状态；
* 必要时进入 Reconciliation。

---

# 48. 历史场景回归

必须运行所有已有场景：

```text
MarketData
Runtime
Cluster
Order
Risk
Position
Position Allocation
Strategy Ledger
```

不得：

* 删除旧场景；
* skip；
* 放宽断言；
* 修改业务期望掩盖回归；
* 只运行新测试。

如果 Account 或 Virtual Broker 接入导致旧接口不一致，应修复正式装配，不得建立旁路。

---

# 49. 完整不变量

全链路结束后至少验证：

```text
Runtime 状态合法
Cluster 状态合法
Clock 时间确定
Event 顺序确定

Risk Reject 不创建订单
Broker Submit 成功不等于 Accepted
Broker Cancel 返回成功不等于 Cancelled

Order 状态合法
重复 Broker Trade 不重复更新

Account Position
=
Allocation Sum
+
Unallocated

T+1 当日买入不可卖
Reservation 不重复冻结

Strategy Ledger 使用 Allocation 成本
Account 使用账户 Position 估值
Strategy Ledger 与 Account 不混用

Account cash + position market value = account equity
Strategy Cash View = Strategy PnL View

Virtual Broker State 与 Local State 独立
Broker Snapshot 不直接共享 Manager 内部对象

相同输入重放结果一致
```

---

# 50. 确定性重放

同一：

```text
Runtime 配置
Clock
Bar 序列
Cluster 配置
Risk Profile
Virtual Broker 配置
Matching Model
Commission Model
Latency Model
```

重复执行至少 100 次。

比较：

```text
OrderId
VenueOrderId
TradeId
Broker Update 顺序
Order Snapshot
Position Snapshot
Allocation Snapshot
Ledger Snapshot
Account Snapshot
Fees
PnL
Equity
Event Sequence
```

必须一致。

不得使用随机 ID，除非测试配置提供固定种子且结果可重放。

---

# 51. Demo

更新：

```text
examples/integration_demo/
```

并增加：

```text
examples/account_demo/
examples/virtual_broker_demo/
```

完整 Demo 必须可以通过一条命令运行：

```bash
python examples/integration_demo/run_all.py
```

输出：

```text
Scenario
Result
Order Summary
Broker Summary
Position Summary
Allocation Summary
Ledger Summary
Account Summary
Reconciliation Summary
Invariant Results
```

---

# 52. 文档输出

创建或更新：

```text
docs/account.md
docs/broker_gateway.md
docs/virtual_broker.md
docs/integration_vertical_slice.md
docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/runtime.md
docs/runtime_context.md
docs/event.md
docs/architecture.md
docs/testing.md
docs/architecture_principles.md
```

---

# 53. ADR

创建：

```text
docs/adr/0015-account-broker-ports-and-virtual-broker.md
```

至少记录：

## 背景

OnlyAlpha 需要适配多个真实券商，同时在当前阶段提供可用于回测、Paper 和集成测试的虚拟券商。

## 决策

* AccountManager 与 BrokerGateway 分离；
* StrategyLedger 与 Account 分离；
* Broker 能力拆成多个 Port；
* Virtual Broker 实现同一 Broker Port；
* Virtual Broker 拥有独立券商侧状态；
* Virtual Broker 不共享 AccountManager 状态；
* Matching Engine 独立；
* Commission、Slippage、Latency 独立；
* Broker 回报进入 Runtime Queue；
* Broker 不直接修改 Manager；
* Submit 成功不等于 Accepted；
* Cancel Request 成功不等于 Cancelled；
* Broker 与 Local 通过 Reconciliation 对账；
* 所有已实现组件必须进入完整 Vertical Slice。

## 拒绝方案

* AccountManager 直接调用具体 SDK；
* 为每个券商修改上层 Order API；
* Virtual Broker 直接复用本地 Manager 状态；
* Gateway 内部写死撮合逻辑；
* Broker 回调直接修改 Order、Position、Account；
* 回测与实盘使用不同订单接口；
* 新组件只做单元测试，不做完整连通测试。

---

# 54. Architecture Principles 新增规则

加入：

```text
Rule: AccountManager 维护 Runtime 本地账户状态。

Rule: BrokerGateway 只负责外部券商能力和标准化数据。

Rule: BrokerGateway 不直接修改 Manager。

Rule: Virtual Broker 必须拥有独立券商侧状态。

Rule: Virtual Broker 与真实券商实现相同 Broker Ports。

Rule: Matching Engine 与 Broker Gateway 分离。

Rule: Commission、Slippage 和 Latency 使用独立模型。

Rule: Broker Submit 成功不等于 Order Accepted。

Rule: Broker Cancel Request 成功不等于 Order Cancelled。

Rule: Broker Update 必须进入 Runtime 受控队列。

Rule: Account 真实账与 Strategy Ledger 虚拟账必须分离。

Rule: Broker Snapshot 不得静默覆盖 Local Account。

Rule: 每次新增组件必须接入完整 Integration Vertical Slice。

Rule: 每次新增组件必须运行所有历史集成场景。
```

---

# 55. 实现顺序

严格按以下顺序：

1. 扫描当前 Account、Execution 和 Broker 相关实现；
2. 创建差距分析；
3. 实现 Account Domain；
4. 实现 Account Snapshot；
5. 实现 AccountManager；
6. 实现 Account Query 和 Context View；
7. 实现 Account Risk View；
8. 实现 Account Reconciliation；
9. 定义 Broker Capabilities；
10. 定义 Broker Ports；
11. 定义标准 Broker DTO；
12. 定义 Broker Update；
13. 实现 Virtual Broker 独立 Store；
14. 实现 Virtual Broker Connection；
15. 实现 Submit/Cancel；
16. 定义 Matching Engine；
17. 实现最小 Matching Engine；
18. 实现 Commission Model；
19. 实现 Slippage Model；
20. 实现 Latency Model；
21. 实现 Scheduler 和 Update Queue；
22. 实现 Broker Account/Position/Order/Trade Query；
23. 将 Virtual Broker 接入 ExecutionService；
24. 将 Broker Update 接入 Runtime；
25. 将 AccountManager 接入成交链；
26. 更新 Integration Environment；
27. 新增完整场景；
28. 运行所有历史场景；
29. 运行确定性重放；
30. 创建 Demo；
31. 更新文档；
32. 创建 ADR；
33. 生成集成报告。

---

# 56. 验收标准

完成后必须满足：

* 每个 Runtime 有独立 AccountManager；
* Account 与 StrategyLedger 分离；
* Broker Ports 清晰；
* 具体 Gateway 可替换；
* Virtual Broker 实现统一 Port；
* Virtual Broker 状态与本地状态分离；
* Submit 语义正确；
* Cancel 语义正确；
* Broker Update 异步进入 Runtime；
* Matching Engine 独立；
* Commission/Slippage/Latency 可配置；
* Account Snapshot 不可变；
* Account Risk View 可用；
* Broker Snapshot 可对账；
* Account 冲突可阻断 Risk；
* 正常买入链自动从 Bar 运行到 Account；
* 部分成交正确；
* 撤单释放正确；
* T+1 正确；
* 多 Cluster 共享账户正确；
* Strategy Ledger 不受账户合并成本污染；
* 所有历史集成场景通过；
* 确定性重放通过；
* 文档、Demo、ADR 和报告完整。

---

# 57. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

* AccountManager 直接依赖具体券商 SDK；
* Virtual Broker 共享 AccountManager 内部状态；
* Broker 回调直接修改 Manager；
* Submit 返回成功直接标记 Accepted；
* Cancel 返回成功直接标记 Cancelled；
* Matching 逻辑写死在不可替换 Gateway 中；
* 系统时间用于 Virtual Broker；
* 使用 sleep 模拟回测延迟；
* Broker 原始 SDK 对象传播到 Domain；
* Account 和 StrategyLedger 混用；
* Broker Snapshot 静默覆盖本地状态；
* Risk 无法读取真实 Account View；
* 新组件未接入完整 Vertical Slice；
* 未运行历史集成场景；
* 删除、skip 或放宽旧测试；
* Demo 直接修改内部状态；
* 相同输入重放结果不同。

---

# 58. 集成报告

生成：

```text
docs/reports/account_virtual_broker_integration_report.md
```

至少包含：

```text
新增文件
修改文件
Account 组件边界
StrategyLedger 与 Account 边界
Broker Port 设计
Broker Capability
Virtual Broker 设计
Virtual Broker 独立状态
Matching Engine 设计
Commission Model
Slippage Model
Latency Model
Broker Update Queue
Account Reconciliation
Risk Account View
ctx.accounts API
ExecutionService 接入
Vertical Slice 接入点
新增集成场景
历史场景结果
单元测试结果
直接集成测试结果
完整链路结果
确定性重放结果
关键不变量
使用的 Placeholder
已知限制
一票否决项
是否建议进入 ExecutionProcessor
是否建议进入 Paper Runtime
是否建议接入首个真实 Broker Gateway
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```
