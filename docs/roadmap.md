# OnlyAlpha 路线图

## 当前状态（2026-07-19）

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

## Phase 2B：真实历史数据（部分完成）

- 已有 Tushare 日线 DataSource、严格校验、Parquet Cache 与 CACHE_ONLY 正式示例；
- 数据版本、质量、缺口和交易日历治理；
- 复权、公司行为与参考数据；
- 大规模数据读取和回放验证。

## Phase 2C：A 股市场规则（部分完成）

已完成版本化 `CN_A_SHARE_CASH@2025.1` 基础领域 Profile：T+1 instruction、Long-only、禁止裸卖空、
多 Session、Reference 驱动的主板/ST/创业板/科创板涨跌幅、整手/零股清仓和基础税费。尚缺正式 Runtime 纵切面：

- 完整涨跌停、停牌、交易单位与申报规则；
- 跨部分成交最低佣金累计；
- Profile 驱动的 Broker/ExecutionProcessor 状态更新；
- 历史规则版本化验证。

## Multi-Market Simulation Foundation（部分完成）

- 已完成 Market Profile、Settlement、Position Mode/Effect、Short、Margin、Session、Price、Quantity、Fee、
  Liquidity、Slippage、Matching 的核心不可变抽象；
- 已完成 Generic T0 Cash、Generic Margin Futures、Generic 24×7 Crypto Spot 的领域级确定性验证；
- 已扩展 Settlement、Margin、Market Rule Decision 的 Result 与零行稳定 Parquet Schema；
- 尚未完成 Generic Profile 通过正式 Engine 的四类示例、Virtual Broker/ExecutionProcessor 全纵切面及 Tushare 对照验收。

## Phase 2D：回测分析与报告（基础阶段已完成）

- 已完成标准事实、结构化诊断、FIFO Trade、基础收益/回撤/交易/Exposure 统计；
- 已完成原子 JSON/Parquet Artifact、Manifest、CLI/Console/Markdown Report 和稳定指纹；
- 未完成高级风险、归因、图表、批量参数实验和结果比较。

## Phase 3：Paper 产品循环（未完成）

实时行情、模拟成交、状态恢复和可操作产品入口尚未闭环。

## Phase 4：Live 产品循环（未完成）

真实行情/交易 Gateway、重连、同步和生产级对账尚未闭环。本阶段开始前继续保持真实交易禁用。

## Phase 5：Research 工作流（未完成）

因子接口已有基础边界；数据探索、IC/分组分析、实验管理、统计和绘图工作流尚未形成产品循环。

## Phase 6：Web（未完成）

Application Service、REST、WebSocket/SSE、权限和控制台尚未实现。

## Phase 7：多市场（基础边界已开始）

核心 Profile/规则边界与三个 Generic Profile 已建立；港股、美股、中国期货、数字资产衍生品、外汇和期权正式产品适配尚未开始。

## Phase 8：性能与分布式（未完成）

多进程回测、大规模因子、远程 Worker 和分布式任务不在当前阶段。在真实 A 股回测闭环和性能基线建立前不提前引入。
