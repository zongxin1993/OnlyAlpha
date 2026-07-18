# Gateway 设计

## 1. 类型

```text
OnlyMarketGateway
OnlyTradeGateway
OnlyGatewayManager
OnlyGatewayConfig
OnlyGatewayState
OnlyInstrumentProvider
```

## 2. Market Gateway

负责：

- 连接；
- 订阅；
- Tick/Bar；
- 重连；
- 状态；
- 数据标准化；
- 时间戳校验；
- Instrument 关联。

## 3. Trade Gateway

负责：

- 登录；
- 账户；
- 持仓；
- 下单；
- 撤单；
- 委托回报；
- 成交回报；
- 重连；
- 状态恢复。

## 4. 标准化

所有外部对象必须转换为 OnlyAlpha 领域对象后再进入 Event Bus。

DataSource 与 Broker 外部适配器通过 `onlyalpha.plugin.api` 实现 Factory SPI，并由 `onlyalpha.data_sources`、
`onlyalpha.brokers` Entry Point 发现。Broker 原始 SDK 对象不得进入核心；标准回报固定经过：

```text
Broker Plugin -> BrokerInboundQueue -> ExecutionProcessor -> Order/Position/Ledger/Account
```

插件不得持有或直接修改 Manager，也不得调用 Strategy/Factor。Descriptor、Capability、配置、生命周期与错误规则见
`docs/plugin_system.md` 和 `docs/broker_plugin.md`。

## 5. 幂等和去重

必须处理：

- 重复回报；
- 乱序回报；
- 重连补发；
- 本地与远端 ID 映射；
- 查询与推送冲突。

## 6. 安全

真实交易 Gateway 默认关闭。

启用真实交易必须：

- 明确配置；
- 明确环境；
- 明确账户；
- 风控通过；
- 日志完整；
- 禁止测试代码误触发。
