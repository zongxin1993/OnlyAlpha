# 统一市场规则运行时：修改前审计

> 审计日期：2026-07-19（Asia/Shanghai）  
> 范围：配置、Market Profile、Runtime、Risk、Virtual Broker、Execution、Position、Account、Collector、Result/Artifact 及相关测试和文档。

## 审计结论

现有 `onlyalpha.market` 已有版本化 Profile、结算/保证金/费用/流动性等领域模型，但它们尚未进入正式 Runtime 纵切面。产品配置仍把市场规则命名为可选 `market_simulation`；Runtime/Risk 仍走旧 `OnlyMarketRule` Mapping；Virtual Broker 仍自带撮合、滑点、佣金和 T+1 制度；Position 仍由日切服务直接把全部未结算仓位转为可用。因此当前是两套并行但未打通的语义，不能通过保留 Legacy 分支修补。

## 重复模型表

| 业务概念 | 现有表达 | 问题 | 处置 |
| --- | --- | --- | --- |
| 市场配置 | `OnlyMarketSimulationConfig` / `market_simulation` | 把真实市场制度错归为仿真，且可选 | 删除，迁移为必填 `OnlyMarketConfig` / `market` |
| 有效市场规则 | `OnlyEffectiveMarketRules = OnlyMarketProfile` | Profile 被当成运行规则，没有编译边界 | 删除别名，新增不可变 Compiled Rules |
| 基础下单规则 | `domain.OnlyMarketRule` 与 Profile 的 Price/Quantity/Settlement/Fee | 同一语义分布在 Domain/Risk/Market | 迁移 Instrument Reference 与 Compiled Rules 后删除旧 Mapping |
| 结算 | `market.OnlySettlementModel` / `position.OnlySettlementService` / Broker `settle()` | 规则、状态和 Broker 快照混在三处 | Rule Engine 产生 Instruction，Runtime Settlement Manager 应用，Broker 仅维护外部快照 |
| 费用 | Market `OnlyFeeModel/Accumulator` / Broker commission model | Broker 直接决定市场费用，Accumulator 未进交易链 | Rule Engine 生成 Fee Instruction，Execution 应用累计 delta |
| 撮合/滑点 | Profile models / Broker factory extensions | 市场制度仍由 Broker Config 选择 | 编译为 Match-Time Policy，Broker 仅消费 Port |

## 旧接口引用表

| 旧接口/字段 | 主要调用点 | 迁移目标 |
| --- | --- | --- |
| `OnlyMarketSimulationConfig` | `config.models` / `config.cluster_document` / `config.__init__` / config tests/docs | `OnlyMarketConfig` |
| `market_simulation` | Cluster document parser、HANDOFF、ADR 0024/0025、Profile config doc | 必填 `market`；旧 key 显式拒绝 |
| `OnlyMarketRuleRiskView` / `OnlyMarketRuleRiskMappingView` | `risk.ports` / `risk.views` / Runtime 装配 | `OnlyPreTradeMarketRulePort` |
| `register_instrument(..., market_rule=...)` | Backtest Runtime 与 runtime test support | `register_instrument(instrument, reference=...)`，规则由 Engine 按日编译 |
| Broker `commission_model/slippage_model/matching_engine` | Virtual config/factory/gateway 及 fixtures | Match-Time/Fee Ports；Broker config 仅留 latency/连接/故障注入 |
| Broker `account_store.settle()` / `t-plus-one-settlement` | `OnlyVirtualBrokerGateway.on_bar()` | 删除日切推断，结算由 Runtime Manager 依 Instruction 到期推进 |

## 错误职责与写死逻辑

- Risk 通过 `dict[InstrumentId, OnlyMarketRule]` 读取静态规则，无法表达按 Trading Day 的版本变化，也没有独立 Market Decision 审计身份。
- Virtual Broker 在 Trading Day 变化时无条件结算并发布 `t-plus-one-settlement`，同时把 commission/slippage/matching 当成 Broker 插件配置。
- ExecutionProcessor 直接从 Broker Fill 中取 fee，自行构造 Position Trade 与 Cash Flow，未先经 Trade Instruction Port，也没有 Settlement/Margin/Fee 状态步骤。
- Position 实体仅以 settled/unsettled bucket 表达资产可用；`OnlySettlementService` 通过固定 T1 Rule 直接 settle Position/Allocation，没有交易可用现金、可取现金和法律结算的独立生命周期。
- Margin 只有纯计算模型和值对象，没有 Runtime-owned reservation/occupation/release Manager。
- Collector 对 execution commission/slippage 存在从 Broker Fill 再投影或填零的逻辑，尚未收集 compiled identity、market decisions、settlement/margin/fee 标准事实。

## 应保留模型

- 版本化 Profile family/version/registry/request/resolved identity、有效期、Capability、Override Policy 和 fingerprint。
- `OnlyInstrument`、Instrument Reference、Trading Calendar、Order/Trade/Position/Account 强类型与 `Decimal` 真值。
- Runtime-owned Order/Position/Allocation/Account/Strategy Ledger Manager，以及 ExecutionProcessor 唯一 Broker Update 应用入口。
- Broker Order/Trade/Account/Position Store，但只作为模拟外部 Broker Snapshot，不作为 Runtime 真值。
- Result/Artifact 的 Settlement、Margin、Market Rule Decision 不变事实边界，由 Collector 读取正式状态生成。

## 删除清单

1. `OnlyMarketSimulationConfig`、`market_simulation` 解析/导出/测试/正式文档。
2. Market 缺失时的 Legacy 分支与 optional market config。
3. `OnlyEffectiveMarketRules = OnlyMarketProfile` 别名与 Profile 直接运行时消费。
4. Risk `OnlyMarketRuleRiskView/MappingView` 及 Runtime `market_rule=` 注册参数。
5. Virtual Broker 的 T+1 日切和属于市场制度的 commission/slippage/matching 配置。
6. Position 层固定 `OnlyT1SettlementRule` 的正式 Runtime 路径。

## 迁移清单

1. Config 必填 `market` → Registry 解析 family/version/override。
2. Resolved Profile + Instrument Reference + Venue + Trading Day + Runtime Mode → `OnlyMarketRuleCompiler` → immutable `OnlyCompiledMarketRules`。
3. Runtime Factory 注入 `OnlyMarketRuleEngine`；引擎按 profile family/reference/day/override fingerprint 缓存，不假设跨期版本不变。
4. Risk 调用 Pre-Trade Port；Broker 调用 Match-Time Port；Execution 仅应用 Trade/Position/Settlement/Margin/Fee/Cash Instruction。
5. 新增 Runtime-owned Settlement/Margin Manager，接管 availability/margin 生命周期；Fee Accumulator 按 Order 累计。
6. Collector 只收集 Resolution/Compiled Identity/Decision/Settlement/Margin/Fee 正式事实。

## 目标组件边界图

```text
OnlyMarketConfig
    ↓
OnlyMarketProfileRegistry / Resolver
    ↓  (Profile 边界到此为止)
OnlyMarketRuleCompiler + Instrument/Venue/TradingDay/RuntimeMode
    ↓
OnlyCompiledMarketRules
    ↓
OnlyMarketRuleEngine
    ├─ Pre-Trade Port → Risk
    ├─ Match-Time Port → Broker Gateway
    └─ Trade/Settlement/Margin/Fee Instruction Ports → ExecutionProcessor
                                                        ├─ Position Manager
                                                        ├─ Settlement Manager
                                                        ├─ Margin Manager
                                                        ├─ Account Manager
                                                        └─ Reservation/Risk State

Runtime facts/managers → Collector → Result → Analytics → Artifact/Report
```

Backtest/Paper/Live/Shadow 共用上述 Market Rule 语义；它们只在数据源、Broker Gateway、时间驱动、外部状态权威和失败模式上不同。
