# Market Profile Configuration

最简必填配置必须同时显式选择 Market Fee Pack。生产 A 股费用覆盖从 `2025-06-30` 开始：

```yaml
market:
  profile: CN_A_SHARE_CASH
  fee_pack:
    pack_id: CN_A_SHARE_PRODUCTION_MARKET_FEES
    pack_version: "2025.06.30"
```

固定版本与允许的有限覆盖：

```yaml
market:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
  fee_pack:
    pack_id: CN_A_SHARE_PRODUCTION_MARKET_FEES
    pack_version: "2025.06.30"
  overrides:
    liquidity:
      maximum_participation_rate: "0.05"
    slippage:
      model: FIXED_TICKS
      ticks: "2"
```

数值必须是带引号的 Decimal 字符串。缺失 `market` 或使用已删除的旧 key 会立即拒绝加载。

真实佣金合同在顶层 `authorities.broker_fee_contracts` 定义，Account 只通过 ID/Version 选择。完整严格 Schema 见
`examples/configs/tushare_daily_backtest.yaml`。窗口外日期、未安装 Pack/Contract、Broker 或 Account scope 不匹配均 Fail Closed。
