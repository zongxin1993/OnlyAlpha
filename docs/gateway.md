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
