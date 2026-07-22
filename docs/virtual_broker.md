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
    fees:
      mode: NONE
    extensions:
      matching:
        type: NEXT_BAR
      latency:
        submit_ns: 0
        acceptance_ns: 0
        fill_ns: 0
      slippage:
        type: NONE
      maximum_fill_quantity: null
```

Core Parser 只保留 `extensions`；具体 Matching、Latency、Slippage 和最大成交量由插件 Factory 解析和拒绝未知字段。
Backtest 装配要求 Broker 声明 `simulated_execution` 且 `OnlyBrokerComponent.deterministic_driver` 非空，否则 Runtime
启动前失败。

插件职责限于模拟外部 Broker：连接与生命周期、请求接收、拒绝与撤单、Next-Bar 撮合、部分成交、滑点、延迟、
稳定调度、标准 Broker Update，以及 Order/Trade/Account/Position 查询投影。插件 Store 是
`external simulated broker projection`，不是 Runtime accounting truth。

Runtime 独占 Order、Committed Execution、Position、Allocation、Account、Strategy Ledger、Fee、Settlement、Margin、Risk、
Audit、Reconciliation 和 Result。Broker Update 只能进入 Runtime-owned `OnlyBrokerInboundQueue`，再由
`OnlyExecutionProcessor` 应用。成功成交在完整事务提交后写入 `OnlyCommittedExecutionJournal`；Collector、Analytics、Artifact
和 Backtest Result 都从 Journal 读取，`query_trades()` 仅用于 Broker 查询和对账。

Virtual Broker 不接收完整 `OnlyMarketRuleEngine`，不使用后置 `bind_market_rules`，不访问 Runtime Manager。市场规则、
T+1、本地 Settlement/Margin 和费用仍由 Runtime 权威链处理。模拟 Fill 未收到外部费用时使用
`reported_fee=None` 与 `fee_reporting_mode=NONE`；插件不持有第二套 Runtime Commission/Fee 公式。

确定性约束：Matching 只读取当前及已经到达的历史 Bar；Scheduler 按 `(due_ns, sequence)` 稳定排序；不读取系统时间、
不 sleep、不使用随机隐式状态。同一输入应产生相同 Order/Trade/Update 顺序与结果指纹。
