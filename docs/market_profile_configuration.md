# Market Profile Configuration

最简必填配置：

```yaml
market:
  profile: CN_A_SHARE_CASH
```

固定版本与允许的有限覆盖：

```yaml
market:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
  overrides:
    liquidity:
      maximum_participation_rate: "0.05"
    slippage:
      model: FIXED_TICKS
      ticks: "2"
```

数值必须是带引号的 Decimal 字符串。缺失 `market` 或使用已删除的旧 key 会立即拒绝加载。
