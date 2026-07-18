# OnlyAlpha 路线图

## 当前状态（2026-07-18）

OnlyAlpha 已完成模块化单体的确定性回测内核纵切面，但尚未完成真实 A 股回测产品。完成标记仅代表现有源码、测试和公开边界覆盖的能力。

## Phase 0：分析与架构基线（已完成）

- MyQuant 行为分析与 NautilusTrader 领域模型研究；
- Engine / Runtime / Cluster、Event、Clock、Cache / Storage 架构与 ADR；
- 三仓职责和核心仓独立依赖方向。

## Phase 1：核心运行骨架（已完成）

- Engine / Runtime / Cluster 生命周期；
- Cluster Definition、Session 与 Runtime Session；
- Runtime 兼容性分组和多 Cluster 隔离；
- 有界 Event Bus、确定性 Clock、配置、Cache 与 Storage；
- Strategy / Factor / Indicator 分层及受限 Context；
- DataSource / Broker Plugin SPI 与 Entry Point 发现。

## Phase 2A：确定性回测内核（基本完成）

- Synthetic Historical Replay；
- Virtual Broker 与基础 Next-Bar 撮合；
- Risk / Order / ExecutionProcessor；
- Position / Allocation、Strategy Ledger / Account；
- 单 Cluster、多 Cluster与共享 Runtime 分组；
- user_data 输出、完整纵切面和确定性重放。

“基本完成”不表示具备完整市场仿真：当前实现用于验证正式产品链和交易不变量。

## Phase 2B：真实历史数据（未完成）

- 真实 A 股历史行情 DataSource；
- 数据版本、质量、缺口和交易日历治理；
- 复权、公司行为与参考数据；
- 大规模数据读取和回放验证。

## Phase 2C：A 股市场规则（部分完成）

已具备 T+1 基础持仓语义和可扩展规则边界。尚缺：

- 完整涨跌停、停牌、交易单位与申报规则；
- 完整手续费、印花税及其他费用；
- 成交量约束和更完整撮合语义；
- 历史规则版本化验证。

## Phase 2D：回测分析与报告（未完成）

- 标准绩效指标、归因和回撤分析；
- 完整回测报告与可复现产物；
- 批量参数实验和结果比较。

## Phase 3：Paper 产品循环（未完成）

实时行情、模拟成交、状态恢复和可操作产品入口尚未闭环。

## Phase 4：Live 产品循环（未完成）

真实行情/交易 Gateway、重连、同步和生产级对账尚未闭环。本阶段开始前继续保持真实交易禁用。

## Phase 5：Research 工作流（未完成）

因子接口已有基础边界；数据探索、IC/分组分析、实验管理、统计和绘图工作流尚未形成产品循环。

## Phase 6：Web（未完成）

Application Service、REST、WebSocket/SSE、权限和控制台尚未实现。

## Phase 7：多市场（未完成）

领域模型保留扩展能力；中国期货、港股、美股、数字资产、外汇和期权产品适配尚未开始。

## Phase 8：性能与分布式（未完成）

多进程回测、大规模因子、远程 Worker 和分布式任务不在当前阶段。在真实 A 股回测闭环和性能基线建立前不提前引入。
