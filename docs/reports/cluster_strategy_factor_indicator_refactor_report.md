# Cluster、Strategy、Factor、Indicator 架构重构报告

日期：2026-07-16
结论：`ACCEPTED`

## 修改前架构

`OnlyCluster` 同时承担容器与具体策略，Strategy Factory 创建 Indicator，Runtime/Assembly 识别 MACD，Bar Subscription 携带 `indicator_ids`，通用 Result 暴露 MACD 字段；工程没有正式 Factor 模型。详细基线见 `cluster_strategy_factor_indicator_gap_analysis.md`。

## 修改后架构

```text
OnlyEngine
└── OnlyRuntime (many, isolated)
    └── OnlyCluster (many, isolated)
        ├── exactly one OnlyStrategy
        ├── zero or more OnlyTimeSeriesFactor / OnlyCrossSectionFactor
        └── Cluster-scoped OnlyIndicatorRegistry
             └── Factor-scoped OnlyIndicator instances
```

固定回调顺序为 `MarketData → Indicator → Factor dependency plan → required-factor ready gate → Strategy → Order`。交易后链继续复用正式 Risk、Virtual Broker、Execution Processor、Position、Allocation、Strategy Ledger 与 Account 接口。

## Engine 与 Cluster

Engine/Runtime 继续通过 `OnlyClusterManager` 管理多个隔离 Cluster。Cluster 是生命周期、Scope、订阅与计算调度容器，不实现具体买卖算法；不同 Cluster 分别创建 Strategy、Factor 与 Indicator 可变实例。

## Cluster 与 Strategy

Cluster 构造时只接受一个 `OnlyStrategy`；未配置交易算法的基础设施 Cluster 显式持有 `OnlyNoopStrategy`，因此运行期始终满足“恰好一个”。Strategy 生命周期由 Cluster 转发，交易回调由 required Factor ready gate 控制。

## Cluster 与 Factor

Cluster 可注册零到多个 Factor。`OnlyFactorRegistry` 校验唯一 ID，`OnlyFactorDependencyGraph` 生成稳定执行计划并拒绝未知依赖、循环依赖以及 TimeSeries 对 CrossSection 的逆阶段依赖。

## Factor 与 Indicator

Factor 只在 `on_initialize` 通过 `OnlyFactorIndicatorContext` 创建 Factor-scope Indicator，并读取强类型 Snapshot/Score。Factor Context 不含 orders、positions、ledger、accounts、risk mutation、Broker 或 Manager。

## 抽象接口与结果

- Strategy：统一 initialize/start/bar/timer/pause/resume/stop 生命周期，读取 `OnlyStrategyFactorView`，专有诊断通过结果扩展输出。
- Factor：统一生命周期、`snapshot()` 与 `score()`；分别定义 TimeSeries `on_bar` 和 CrossSection `on_cross_section`。
- Indicator：统一 update/warmup/ready/reset/snapshot/score；Bar 指标只接收标准 `OnlyBar`。
- Indicator Snapshot：不可变基类；MACD 等专有结果使用强类型 dataclass，不提供任意可变 getter。
- Indicator Canonical Score：携带 indicator ID、Decimal value、Dimension、confidence、ready 与时间。
- Factor Snapshot/Score：不可变、强类型，并保留 Factor 业务语义与统一评分维度。

## TimeSeries Factor 与 CrossSection Factor

TimeSeries Factor 随目标 Bar 更新。CrossSection Factor 接收同一 `bar_end` 的多 Instrument 映射；Universe Snapshot 不可变、按 Instrument ID 稳定排序、显式记录 expected/missing members，并拒绝混合时点。截面排名测试使用值降序与 ID tie-break，结果确定。

## Indicator Factory Registry、参数与 Scope

`OnlyIndicatorFactoryRegistry` 按类型 ID 注册 Factory，拒绝未知类型和重复注册。MACD、RSI、EMA、SMA、ATR、Bollinger、Rolling Return、Rolling Volatility、ZScore 均有标准目录和默认 Factory。默认参数由具体 Config 提供，Factor Config 的 `parameters` 覆盖特殊参数。

实例 Scope 固定为 `runtime_id / cluster_id / factor_id / indicator_id`；重复 ID 与跨 Factor 读取失败，不共享可变实例。

## Cluster Pipeline 与 Context 权限

Cluster Pipeline 先更新 Indicator，再按 DAG 调用 Factor；依赖或 required Factor 未 ready 时跳过 Strategy。Strategy Context 暴露只读 Factor、行情、Instrument 与受限 orders/positions/ledger/accounts/risk/timer/logger；不暴露 Indicator mutation、Runtime、Manager、Broker 或 EventBus。Indicator 不接收任何 Runtime Context。

## 目录重构与动态加载

- 核心抽象：`src/onlyalpha/{cluster,strategy,factor,indicator}/`。
- 标准 Indicator：`src/onlyalpha/indicator/<type>/`，MACD 保留核心。
- MACD Signal Factor：`examples/factors/macd_signal/`。
- MACD Strategy：`examples/strategies/macd/`。
- 通用入口与配置：`examples/run.py`、`examples/configs/backtest/macd/`。

Cluster Factory 根据 `clusters[].strategy` 与 `clusters[].factors[]` 动态加载 Config/实现类型。Strategy Factory 只创建 Strategy；Factor Factory 只创建 Factor；具体 Indicator 由 Factor 初始化阶段经 Registry 创建。Runtime/Assembly 无 MACD/RSI 分支。

## MACD Indicator、Factor 与 Strategy

MACD Indicator 输出 fast/slow EMA、MACD line、signal、histogram、cross state、ready 与 Canonical Score，支持默认/特殊参数、warmup 和 reset。示例 Factor 将其解释为 MACD signal Factor Snapshot/Score；示例 Strategy 只读该 Factor 并通过 `ctx.orders` 交易，不计算或持有 MACD。

## 配置与通用 Result

配置已从旧 `strategies` 改为 `clusters[].strategy + clusters[].factors[].indicators[]`。Bar Subscription 不再携带 Indicator ID。通用 `OnlyClusterResult` 只有 `strategy_result_extension`、`factor_results` 和 `indicator_diagnostics`，不依赖 MACD 类型或信号字段。

## 新增测试

新增 `tests/indicator/`、`tests/factor/`、`tests/strategy/`、`tests/cluster/` 和策略体系集成测试，覆盖 Factory 默认/特殊参数、未知/重复注册、warmup/reset/snapshot/score、Scope 隔离、Factor 权限与 DAG、截面 Universe、Strategy 权限/下单、生命周期顺序、ready gate、动态装配和算法无关静态边界。没有删除、skip、xfail 或放宽历史测试。

## 完整 MACD 回测

命令：

```text
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.run --config examples/configs/backtest/macd/run.yaml
```

结果：`COMPLETED`，720 条 Bar，2 个 Order，2 个 Trade，最终 Equity `998958.00 CNY`，fingerprint `bcc238d9724e49801a7ed4f148e3f3b64dad2da5bc827d0138a09e636b1a1d13`。

## 历史 Vertical Slice 与确定性重放

固定验收脚本 `scripts/run_component_validation.sh` 于 2026-07-16 成功：

- 全仓测试：`282 passed`；
- Integration：`55 passed`；
- Integration Demo：34/34 PASS；
- Product MACD：基线后重复 100 次 fingerprint 完全一致；
- 完整 Vertical Slice：基线后重复 100 次 projection 完全一致；
- Ruff check：通过；
- Ruff format check：526 files already formatted；
- Mypy：289 source files，无问题。

关键不变量包括 Runtime/Cluster Scope、事件顺序、Risk fail-closed、Order/Fill 幂等、Position=Allocation+Unallocated、T+1、Ledger/Account 对账及相同输入重放，均由历史场景继续验证。

## Placeholder/Fake 与已知限制

Product 使用明确的 deterministic Synthetic Historical Data Source 和 Virtual Broker，不是真实行情或真实券商；Integration Demo 保留已标明的测试数据/外部边界适配。没有未标明虚假实现，也没有直接修改 Manager 内部状态。

首阶段 Product Cluster Factory 仍只支持一个启用 Cluster/账户/数据源/Broker 组合；配置驱动的多 Instrument Universe 展开、生产级截面同步、Live/Paper 外部 SDK、持久化恢复与多币种不在本任务范围。Runtime MarketData 仍保留算法无关的通用 barrier/pipeline 接口用于既有组件测试，但不创建或识别具体 Indicator。

## 一票否决项审计

逐项静态检索和测试确认：Cluster 不等于具体 Strategy；单 Cluster 不含多个 Strategy；Strategy Factory 不创建 Indicator；不存在 `OnlyStrategyBuildResult.indicators`；Runtime/Assembly 不实例化具体指标；Subscription 无 `indicator_ids`；Factor 无交易能力；Indicator 无 Runtime/Broker/Manager；实例按 Scope 隔离；DAG 检查循环；ready gate 生效；MACD Factor/Strategy 不在 `src/onlyalpha`；Demo 使用正式 Factory、Context 和 Runtime；历史 Vertical Slice 与两组 100 次重放通过；旧测试未被删除、跳过或放宽。

## 最终结论

`ACCEPTED`

组件、直接上下游、完整 Product、历史 Vertical Slice、确定性与静态质量门禁全部满足，可以进入下一组件开发。
