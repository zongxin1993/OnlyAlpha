# Virtual Broker 插件

Virtual Broker 是独立发行包 `onlyalpha-plugin-broker-virtual`，Python 包名为
`onlyalpha_plugin_broker_virtual`，插件 ID 为 `virtual`。Core 不包含其实现、兼容模块、默认注册或回退逻辑。

安装：

```bash
pip install onlyalpha onlyalpha-plugin-broker-virtual
```

产品配置继续使用：

```yaml
brokers:
  - gateway_id: virtual-main
    plugin: virtual
    extensions:
      matching:
        type: NEXT_BAR
        partial_fill:
          mode: SCHEDULE
          dispatch_mode: ONE_PER_BAR
          steps:
            - {bar_offset: 1, quantity: "300"}
            - {bar_offset: 2, quantity: "400"}
            - {bar_offset: 3, quantity: "300"}
      latency:
        submit_ns: 0
        acceptance_ns: 0
        fill_ns: 0
      slippage:
        type: NONE
      maximum_fill_quantity: null  # legacy: null → WHOLE, positive → MAX_PER_BAR
```

Core Parser 只保留 `extensions`；具体 Matching、Latency、Slippage 和最大成交量由插件 Factory 解析和拒绝未知字段。
Backtest 装配要求 Broker 声明 `simulated_execution` 且 `OnlyBrokerComponent.deterministic_driver` 非空，否则 Runtime
启动前失败。

插件职责限于模拟外部 Broker：连接与生命周期、请求接收、拒绝与撤单、Next-Bar 撮合、部分成交、滑点、延迟、
稳定调度、标准 Broker Update，以及 Order/Trade/Account/Position 查询投影。插件 Store 是
`external simulated broker projection`，不是 Runtime accounting truth。

Trading Runtime 独占 Order、Runtime Transaction Store、Applied Projection Ledger、Position、Allocation、Account、Strategy
Ledger、Fee、Settlement、Margin、Risk、
Audit、Reconciliation 和 Result。Broker Update 只能进入 Runtime-owned `OnlyBrokerInboundQueue`，再由
`OnlyExecutionProcessor` 应用。成功成交在完整事务提交后进入 Runtime Persistence Store 的 Projection Ready Query；
Collector、Analytics、Artifact 和 Backtest Result 只读取该权威，`query_trades()` 仅用于 Broker 查询和对账。

Virtual Broker 服务于目标 Backtest/Sim Trading Runtime。Research Runtime 没有 Broker 或 trading authorities；目标 Sim
必须复用本插件与完整 Trading Kernel，绝不能连接或提交到 Real Broker。

Virtual Broker 不接收完整 `OnlyMarketRuleEngine`，不使用后置 `bind_market_rules`，不访问 Runtime Manager。市场规则、
T+1、本地 Settlement/Margin 和费用仍由 Runtime 权威链处理。模拟 Fill 不携带本地或外部费用权威；插件不持有第二套
Runtime Commission/Fee 公式。Runtime 通过显式 Market Fee Pack 与 Account Broker Fee Contract 评估本地费用。

确定性约束：Matching 只读取当前及已经到达的历史 Bar；Scheduler 按 `(due_ns, sequence)` 稳定排序；不读取系统时间、
不 sleep、不使用随机隐式状态。同一输入应产生相同 Order/Trade/Update 顺序与结果指纹。

PR4.3.3 将 WHOLE、旧 `maximum_fill_quantity` 的 MAX_PER_BAR 和显式 SCHEDULE 统一归一化为订单级 immutable Fill
Plan。ONE_PER_BAR 每 Bar执行一个到期 Step；ALL_DUE 可按 Step Index 同 Bar执行多个 Step。Ratio schedule 以前 N-1
项向下量化、最后一项接收 remainder，严格保持订单总量。Plan 使用 canonical JSON + SHA-256 identity，cursor 与
Order/Trade/Scheduler 与 submission control 一起进入 Gateway checkpoint schema 3；`broker.virtual` participant 与插件
capability 同为 version 3。Version 1/2 checkpoint fail fast。Broker execute 先推进 Account/Order/Trade/Plan，`PUBLISH_FILL` 后续才进入 Runtime，因此
execute-before-publish checkpoint 只恢复发布，不重复 Broker 成交。详见 ADR 0051。

PR4.4.2 不修改 Fill Plan 或 Gateway 的 BUY/SELL 中立设计。同一 SCHEDULE 已通过 OnlyEngine 正式产品链验证 Long Close
`300 → 400 → 300`：ONE_PER_BAR 跨三个 Bar，ALL_DUE 可在同 Bar按 Step Index 连续发布；每个 Step 进入 Runtime 后形成
独立 durable Trade Transaction。Close Fill 1/2 后的 Plan cursor checkpoint、延迟 publish、Commit、Projection、Outbox 与
A→B→C 恢复均与无故障基线一致。Virtual Broker 不计算 Runtime realized PnL、Fee、Reservation 或 Risk。
