# 测试规范

Strategy Ledger 必测固定资金、连续 Cash Reservation、买卖成交、Fee、Allocation 收益归因、多 Cluster/Runtime Scope、不可变
Snapshot、双视图、Risk Fail Closed、幂等、无损序列化、Replay、HWM/Drawdown 与固定时钟确定性。

Risk 测试必须使用固定 Clock 和精确 Decimal 输入，覆盖 Rule 顺序、Mandatory Profile、防绕过、Scope、Fail Closed、
Reservation 即时可见与幂等释放、OrderService 零副作用拒绝、Runtime/Cluster 隔离、Snapshot 不可变和重放确定性。
Demo 必须使用明确命名的 Placeholder 或 Virtual Broker，禁止连接真实 SDK；统一主场景禁止伪造成交。

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

## 8. Clock 测试

`tests/clock` 固定覆盖 Unix 纳秒转换和精度边界、Virtual/Backtest 单调推进、Timer deadline/sequence
顺序、100 次确定性重放、周期与取消、callback 重入和异常、Live 单调等待/单调读取/单 scheduler
thread/关闭，以及 Cluster 无推进权限。核心源码的直接系统时间读取由 AST 测试限制到
`core/clock.py` 白名单；测试不得使用长 sleep。

## 9. Event 与 MarketData Pipeline 测试

`tests/event` 覆盖强类型/纳秒 Event、Scope、FIFO、Subscription、显式 handler priority、满载策略、异常和
关闭。`tests/market_data` 覆盖默认/显式主周期、1m→3m/5m/15m Calendar 聚合、午休 Session 锚定、缺失和
不完整窗口、Cache/version、Required/Optional Indicator barrier、Snapshot 不可变与 closed-only、每时间片
单次回调、多 Cluster 共享/隔离、Live/Backtest 同语义和序列化 Event 重放。多周期业务测试不得以 EventBus
priority 或订阅注册顺序作为准备步骤。

## 10. RuntimeContext 测试

`tests/runtime` 覆盖 Runtime/Cluster 状态机、Context 禁止能力、Subscription 生命周期、Clock 所有权、
1m→3m 默认与显式主周期、同时间 Timer 先于 Bar、Cluster 失败隔离、多 Runtime 隔离、状态 DTO 和 100 次
确定性重放。测试必须确认停止/失败 Cluster 不再接收 Bar，Timer 与 Subscription 自动释放。

## 11. Order 测试

`tests/order` 覆盖 Request 校验、受控状态机、全部终态、部分成交均价、Overfill、request/trade/external
sequence 幂等、迟到 Accepted/Fill、Manager 索引、open order、Runtime 隔离、Cluster Scope、Context 禁止
能力、Placeholder、事件变更后发布、序列化和 100 次确定性重放。测试不得通过 EventBus handler 驱动
状态，不得由 Placeholder 生成 Accepted、Cancelled 或 Fill。

## 12. Position 测试

`tests/position` 覆盖 NETTING Long-only 开增减平、每轮新 PositionId、Average Cost、Linear PnL、账户/Cluster 独立
成本、T+1 Bucket、Restriction、Reservation 全阶段和券商冻结去重、Unallocated、不变量、Broker Difference/Severity/
阻断、不可变 Snapshot、序列化、重复与迟到 Trade、Runtime 隔离、Event 顺序及 100 次确定性重放。券商对账测试必须
断言本地总量没有被静默覆盖。
## Account / Virtual Broker 门禁

除组件单测外，统一环境必须覆盖账户初始化、完整买入、部分成交、Broker 确认撤单、T+1、多 Cluster 共享账户、Broker/Local
冲突以及重复/乱序回报。正常成交不得手工构造 Fill。完整 projection 包含 Local Account 与 Broker Account/Order Snapshot，
同一输入至少重放 100 次并比较全部结果。

## Execution Processor 门禁

必须覆盖 Runtime/Gateway/Account Scope、显式分派、Accepted/Rejected/Cancelled、部分/完全成交、部分成交后撤单、四类
Reservation、重复 Update、重复 Trade、迟到 Accepted、乱序 Trade、中途失败、字段级 Reconciliation、固定 Mutation Step、
Audit/Snapshot 序列化、Runtime 隔离和 100 次完整重放。中途失败断言不得出现 Order/Position/Ledger/Account 完整成功事实。
所有正常成交必须由 Virtual Broker 产生并通过 Queue；Fault/Test Adapter 也只能注入标准 Broker Update。

## Market Data Source 门禁

必须覆盖 Source Capability、Envelope 序列化、UTC 半开范围、InMemory/CSV/Parquet、下推过滤、Queue 背压、Processor Scope、
重复/乱序、Session-aware Gap、Lookahead、稳定多流归并、Clock 唯一推进、Snapshot Quality、Runtime 隔离、完整交易闭环和至少
100 次 Replay。正常历史场景不得直接调用 Pipeline，实时场景不得绕过 MarketData Queue。
