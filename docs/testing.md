# 测试规范

## 1. 层次

```text
tests/unit
tests/integration
tests/regression
tests/property
```

## 2. 单元测试

覆盖：

- 值对象；
- 配置；
- 生命周期；
- Registry；
- Loader；
- Event Bus；
- Cache；
- Repository；
- 风控；
- Clock；
- 撮合；
- 因子；
- 统计。

## 3. 集成测试

覆盖：

- Engine 启停；
- 多 Runtime；
- 多 Cluster；
- 静态和动态加载；
- 订单到成交到持仓；
- Cache 落盘恢复；
- Paper；
- Backtest；
- Web Service 调用。

## 4. 回归测试

使用 MyQuant 固定策略和固定数据。

比较：

- 信号；
- 订单；
- 成交；
- 持仓；
- 费用；
- 滑点；
- 收益；
- 回撤。

## 5. 资产模型测试

覆盖：

- 精度；
- Tick；
- Step；
- Currency；
- Money；
- A 股手数；
- 港股手数；
- 美股碎股；
- 期货乘数；
- 线性合约；
- 反向合约；
- 期权；
- Instrument 版本。

## 6. 确定性

测试应使用：

- 固定时钟；
- 固定随机种子；
- 固定数据；
- 固定配置；
- 明确舍入。

## 7. 时间模型测试

`tests/time_model` 固定覆盖 naive 拒绝、UTC 同瞬间、纳秒单位、IANA 时区、Venue 引用、
A 股午休、中国期货跨午夜夜盘、美股冬夏 DST、不存在/重复本地时间、提前收盘、Bar
`[start,end)`、历史 Calendar、Event/Domain 序列化、UTC/MARKET/USER_LOCAL 显示、
旧数据迁移和不同进程 `TZ` 的确定性。CI 应至少在 `UTC`、`Asia/Shanghai`、
`America/New_York` 环境运行关键测试；测试本身不得依赖机器本地时区。
