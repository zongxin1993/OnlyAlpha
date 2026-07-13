# OnlyAlpha 路线图

## 当前状态（2026-07-13）

Phase 0 文档分析和 Phase 1 最小骨架已建立。这里的“完成”仅指架构可运行骨架，不代表回测、模拟盘或实盘行为已经迁移。明确未包含任何真实策略、撮合算法、订单执行或券商 Gateway。

## Phase 0：分析

- MyQuant 分析；
- NautilusTrader 资产模型研究；
- 模块映射；
- ADR。

## Phase 1：基础骨架

- Domain；
- Engine；
- Runtime；
- Cluster；
- Event Bus；
- Clock；
- Config；
- Logging；
- Tests。

已实现的最小边界：Engine/Runtime/Cluster 生命周期、静态注册与显式模块加载、有界同步 Event Bus、Live/Backtest Clock、Memory Cache、SQLite Storage、基础金融值对象及确定性测试。Config/Logging 目前使用标准 Python 能力，独立子系统延后到真实用例出现时。

## Phase 2：A 股回测

- A 股 Instrument；
- 历史数据；
- 撮合；
- 手续费；
- 滑点；
- T+1；
- 涨跌停；
- 报告。

## Phase 3：Paper

- 实时行情；
- 模拟成交；
- 风控；
- 状态恢复。

## Phase 4：A 股实盘

- Market Gateway；
- Trade Gateway；
- 账户；
- 持仓；
- 委托；
- 成交；
- 重连；
- 对账。

## Phase 5：投研

- 因子；
- Pipeline；
- IC；
- 分组；
- 图表；
- 报告。

## Phase 6：Web

- Application Service；
- REST；
- WebSocket/SSE；
- 权限；
- 控制台。

## Phase 7：多市场

建议顺序：

1. 中国期货；
2. 港股；
3. 美股；
4. 数字货币；
5. 外汇；
6. 期权。

## Phase 8：性能与扩展

- 多进程回测；
- 大规模因子；
- Redis/Postgres；
- 远程 Worker；
- 分布式任务。

在核心模型稳定前不提前进入 Phase 8。
