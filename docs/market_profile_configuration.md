# Market Profile Configuration

最简 opt-in：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
```

固定版本与允许的仿真假设：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
  overrides:
    liquidity:
      maximum_participation_rate: "0.05"
    slippage:
      model: FIXED_TICKS
      ticks: "2"
```

数值必须是带引号的 Decimal 字符串。未声明本节时 `market_simulation=None`，沿用 Legacy Next-Bar Cash，绝不自动切换到 A 股规则。

