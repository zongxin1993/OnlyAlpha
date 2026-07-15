# Virtual Broker 与 Matching Engine

`OnlyVirtualBrokerGateway` 是标准 Broker Ports 的确定性实现，不是共享 Manager 的 Fake。它独占 Account/Order/Trade Store，
与 Runtime 的 AccountManager、OrderManager、PositionManager 和 StrategyLedgerManager 物理分离。主动查询返回 Broker
Snapshot，异步事实只通过 Runtime inbound callback/queue 进入本地系统。

Gateway 构造时绑定强类型 Runtime ID，并把它放入每条 Update；它仍只调用 Queue Port。Queue 之后唯一允许的业务消费者是
Runtime-owned ExecutionProcessor。

默认 `OnlyNextBarMatchingEngine` 固定规则：Bar N 提交、Bar N+1 检查；BUY LIMIT 在 low <= limit 时成交，SELL LIMIT
在 high >= limit 时成交，第一版成交价固定为 LIMIT_PRICE；MARKET 使用下一 Bar open。接受时冻结 Broker 现金或已结算持仓，
成交/撤单后只修改 Broker Store 并发送标准化 Update。

Commission、Slippage、Latency 是独立、可注入、使用 Decimal/强类型值的模型。Scheduler 使用 Runtime Clock 和稳定堆顺序，
不调用系统时间、随机数或 sleep。A 股 T+1 在 TradingDay 前进时结算 Broker settled quantity，并通过 Position/Account Update
与本地状态对账。

第一版不模拟盘口队列、涨跌停撮合细节、保证金、Short、融资融券、期货/期权和网络断线恢复。
