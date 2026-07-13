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
