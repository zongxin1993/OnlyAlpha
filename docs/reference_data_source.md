# Reference Data Source

Reference Data 与 Bar/Tick、Broker 交易接口分离。`OnlyReferenceDataSource` 组合三个只读候选 Port：Instrument Source、
TradingCalendar Source 和 MarketRule Source。

Runtime 的 Instrument Registry 仍是已校验的规范真值。Reference Source 返回候选对象，不得静默覆盖正在交易的定义。第一版
`OnlyInMemoryReferenceDataSource` 在装配/加载阶段提供只读候选；完整文件 manifest、有效期对账与热更新留待持久化数据目录阶段。
