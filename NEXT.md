# 当前后续任务（2026-07-22）

> 当前架构更新：Virtual Broker 插件化和 Runtime Applied Trade Journal 已落地；下文涉及 Core 内置 Virtual
> Broker、后置 Market Rule 绑定或 Result 查询 Broker 的条目均视为 Historical/Superseded。

Unified Fee 的本地 Backtest 权威链和配置装配已完成，下面历史记录中的“Fee 双重真相”描述已被 ADR 0031 和当前源码取代。
下一项 Fee 工作不是再建 Resolver，而是把现有 `OnlyFeeReconciliationService` 接到未来 Live/Paper 的迟到报告入口：以
Adjustment Instruction 幂等更新 Account、Strategy Ledger、FeeManager、Audit/Result，并让重大未知差异进入 Risk trading
block。随后补齐 adjustment/reconciliation Artifact timeline 和真实 Broker contract schedule 注册机制。

当前验证：Core 408 passed；Tushare 16 passed/1 external skip；MiniQMT 10 passed/1 local-QMT skip；全仓 Ruff、三个包 Mypy、
三个 wheel/sdist build、干净环境安装/import/Entry Point smoke 均通过。未执行外部网络/QMT 与 Linux/macOS CI。

---

以下为历史压缩上下文，其中 Fee 状态已被上述说明取代。

已将会话压缩为以下上下文，后续 OnlyAlpha 讨论以此为基准。

## OnlyAlpha 当前定位

OnlyAlpha 是独立的新量化交易系统，不是 MyQuant 重构。

当前工程已进入**确定性 Backtest 产品闭环阶段**，正式主链为：

```text
配置
→ Engine
→ Runtime Planner / Assembler
→ Backtest Runtime
→ DataSource / Replay
→ MarketData Pipeline
→ Indicator → Factor → Strategy
→ Risk → Order
→ Virtual Broker
→ Broker Inbound Queue
→ ExecutionProcessor
→ Position / Allocation / Account / StrategyLedger
→ Result / Analytics / Artifact
```

仓库已经改为**单仓多包模式**：

```text
src/onlyalpha/                         Core
packages/provider/onlyalpha-plugin-*   外部数据源和 Broker 插件
examples/                              策略、因子、配置和场景
tests/                                 Core 和集成测试
```

## 组件状态

### 已完成或基本完成

* Domain 强类型金融模型、Decimal 值对象、Instrument、Calendar、Order、Trade。
* UTC Clock、确定性 Virtual Clock、Timer。
* 有界同步 EventBus、Scope、优先级和背压。
* Engine、Runtime Planner、Assembler、配置解析。
* Backtest Runtime。
* 历史数据 Replay、MarketData Processor、去重、序列、Gap、Audit。
* Bar Aggregation、MarketData Cache、Snapshot。
* Cluster、Strategy、Factor、Indicator 执行链。
* Order Manager、Order Service、Reservation 生命周期。
* Risk Service 基础规则和订单风险预留。
* Virtual Broker 的提交、撤单、撮合、部分成交、延迟、佣金、滑点。
* ExecutionProcessor 作为 Broker Update 唯一业务消费者。
* Position、Allocation、Account、Strategy Ledger。
* 结果事实、Analytics、Parquet/JSON Artifact、指纹。
* Scenario Runner。
* Market Profile、Market Rule 和 Conformance 基础设施。
* Tushare 日线历史数据插件。
* MiniQMT 历史/实时行情和股票 Broker Adapter 一期。

### 部分完成

* Futures：开多、平多、开空、平空和保证金生命周期已进入正式链，但尚未完全闭环。
* Settlement：已有规则指令、Runtime Settlement 和 Position Settlement，但权威边界需统一。
* Margin：已有 Reserve/Occupy/Release，缺每日盯市、维持保证金、Margin Call 和强平。
* Fee：有 Market Profile Fee Facts，但账户实际扣费仍依赖 Broker Fill Fee，存在双重真相。
* Multi-Cluster：运行链支持多个 Cluster，但总体 Performance 错误使用 `ledgers[0]`。
* Result：最终事实较完整，但缺逐 Bar Equity、Position 和 Account 时间序列。
* Conformance：基础设施完整，但并非所有内置 Profile 都有完整正式 Pack。

### 尚未实现

* Paper Runtime。
* Live Runtime。
* Shadow Runtime。
* Research Runtime。
* 动态启动、暂停和恢复 Cluster。
* 生产级 Runtime 状态恢复。
* Web 控制层。
* 完整期货账户系统。
* 多账户、多 Broker 和多数据源 Runtime 装配。

## 已确认的重要缺陷

### P0：Fee 双重真相

当前：

```text
Virtual Broker Commission
→ fill.fee
→ Account / Ledger 实际扣费

Market Profile Fee Model
→ FeeManager
→ Result Fee Facts
```

两边可能不一致。需要让 MarketRuleEngine 产生唯一权威 Fee Breakdown。

### P0：SHORT 路径仍有 LONG 写死

ExecutionProcessor 已能把：

```text
SELL + OPEN → SHORT
BUY + CLOSE → SHORT 平仓
```

但审计快照、失败 Scope 阻断和部分 reconciliation 仍使用固定 `OnlyPositionSide.LONG`。

### P0：多 Cluster 结果错误

Backtest 总体 Performance 使用 `ledgers[0]`，不能代表多个 Cluster 或共享 Account。

### P0：单仓 CI 覆盖不完整

主 CI 安装全部包，但不一定执行所有 `packages/` 下插件的测试、ruff 和 mypy。

### P1：Virtual Broker 与 Runtime 重复解释 Market Rule

两边都生成 Settlement、Fee 或其他规则相关状态，需明确 Broker 外部事实与 Runtime 本地真相的边界。

### P1：结果只有最终权益快照

缺逐 Bar/逐估值事件的 Equity Curve，因此回撤、Exposure 和 Cluster Attribution 不够完整。

### P1：Python 与发布配置不一致

Core 声明支持 Python 3.12，但部分插件测试和发布流程使用 Python 3.13。

## 推荐开发顺序

```text
1. 修复单仓 CI、Python 版本、发布和文档
2. 统一 Fee 权威来源
3. 修复 SHORT 审计、Snapshot、阻断和 reconciliation
4. 修复多 Cluster Performance 和 ledgers[0]
5. 完成 Futures LONG/SHORT 正式 Scenario
6. 建立 GENERIC_MARGIN_FUTURES Conformance Pack
7. 增加逐时点 Equity、Account、Position Facts
8. 统一 Settlement、Margin、Fee 事实边界
9. 清理 Virtual Broker 与 Core 的具体类型耦合
10. 实现 Paper Runtime
11. 接入 MiniQMT 实时行情到 Paper Runtime
12. 实现 MiniQMT Live Runtime
```

## Futures 完成门槛

至少通过以下正式 Engine Scenario：

```text
LONG_OPEN → LONG_CLOSE
SHORT_OPEN → SHORT_CLOSE
PARTIAL_FILL → CANCEL
MARGIN_REJECT → RELEASE
CLOSE_TODAY
CLOSE_YESTERDAY
跨交易日 Settlement
乱序 SHORT Trade
SHORT Position Reconciliation
```

并保证以下状态一致：

```text
Order
Position
Allocation
Account
StrategyLedger
Margin
Settlement
Fee
Result
Artifact
```

## 插件边界原则

Core 保留：

* Domain；
* DataSource/Broker SPI；
* Runtime；
* ExecutionProcessor；
* Manager；
* Market Rule；
* Result 和 Artifact。

具体实现放独立包：

```text
onlyalpha-plugin-data-tushare
onlyalpha-plugin-data-miniqmt
onlyalpha-plugin-broker-miniqmt
onlyalpha-plugin-broker-virtual
onlyalpha-plugin-data-synthetic
onlyalpha-plugin-data-scenario-exact
```

依赖方向必须保持：

```text
Plugin → Core 公共 API
Core -/→ Plugin 具体实现
```

当前不应优先增加新市场、新 Broker、新指标或 Web 功能。当前核心目标是将已有交易链、期货链、结果链和工程门禁收敛为单一、一致、可验证的正式基线。
