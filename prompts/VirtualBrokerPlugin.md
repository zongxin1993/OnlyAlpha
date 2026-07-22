# OnlyAlpha Virtual Broker 插件化重构

## 一、任务目标

从第一性原则重新划分 OnlyAlpha Core 与 Virtual Broker 的职责边界，将当前位于 Core 内的虚拟券商完整剥离为独立插件发行包。

这不是简单移动目录，也不是保持历史 API 的兼容迁移。允许重写：

* Broker SPI；
* Broker 创建和装配接口；
* Backtest Runtime 与 Broker 的交互方式；
* Broker Inbound Queue；
* Runtime 成交事实存储；
* Virtual Broker 内部结构；
* 现有测试；
* 示例配置；
* CI；
* 当前架构文档。

最终必须达到：

```text
Core
├── Broker 公共领域语言
├── Broker SPI / Port
├── 通用 Broker Inbound Queue
├── Runtime / ExecutionProcessor
├── Market Rule
├── Position / Account / Ledger
└── Result / Artifact

Virtual Broker Plugin
├── Virtual Broker Gateway
├── Matching
├── Latency
├── Slippage
├── Scheduler
├── Broker-side Projection
└── Virtual Broker 配置与 Factory
```

依赖方向必须严格为：

```text
onlyalpha-plugin-broker-virtual
        ↓
onlyalpha Core 公共 API
```

禁止：

```text
OnlyAlpha Core
        ↓
Virtual Broker 具体实现
```

---

# 二、工作原则

## 2.1 以当前源码为事实源

开始修改前必须重新检查当前工作树和仓库结构。

不要直接信任：

* 历史 Prompt；
* 旧 HANDOFF 内容；
* 旧 NEXT 内容；
* 历史架构报告；
* 本任务中出现的旧文件路径。

优先级为：

```text
当前源码
→ 当前测试
→ 当前配置模型
→ 当前 CI
→ 当前正式文档
→ 历史报告和 Prompt
```

首先执行并记录：

```bash
git status
git log -n 10 --oneline
```

然后搜索所有 Virtual Broker 具体依赖：

```bash
rg "onlyalpha\.broker\.virtual"
rg "OnlyVirtualBroker"
rg "virtual_broker_config"
rg "bind_market_rules"
rg "product backtest requires Virtual Broker"
rg "query_trades"
rg "broker_gateway"
```

建立实际依赖图后再开始修改。

## 2.2 不保留历史兼容性

本任务明确不要求兼容旧 API。

禁止创建：

* `onlyalpha.broker.virtual` 兼容转发模块；
* 旧类名 Alias；
* Deprecated Wrapper；
* 条件 Import；
* Core 到插件的延迟 Import；
* Core 内隐藏的 Virtual Broker 默认实现；
* “插件不存在时退回内置虚拟券商”的逻辑。

旧入口应直接删除。

配置中的插件标识可以继续使用：

```yaml
plugin: virtual
```

但其实现只能来自独立插件 Entry Point。

## 2.3 不允许隐藏依赖

禁止使用：

```python
getattr(gateway, "bind_market_rules")
hasattr(...)
isinstance(gateway, OnlyVirtualBrokerGateway)
```

来识别插件能力。

所有 Runtime 所需能力必须通过：

* 明确的 Protocol；
* 明确的 DTO；
* 明确的 Factory 返回对象；
* 明确的 Create Request；
* 明确的 Capability；

进行表达。

## 2.4 Runtime 是本地交易状态权威

以下状态的本地权威仍属于 Runtime：

* Order；
* Applied Trade；
* Position；
* Position Allocation；
* Account；
* Strategy Ledger；
* Settlement；
* Margin；
* Fee；
* Risk；
* Result；
* Audit；
* Reconciliation。

Virtual Broker 只负责模拟外部 Broker 行为：

* 接收订单请求；
* 模拟 Broker 接受、拒绝和撤单；
* 模拟撮合；
* 模拟延迟；
* 模拟滑点；
* 生成标准 Broker Inbound Update；
* 提供 Broker-side Query Projection；
* 模拟外部 Broker 序列和回报顺序。

Virtual Broker 不得直接访问或修改：

* `OnlyOrderManager`；
* `OnlyPositionManager`；
* `OnlyAccountManager`；
* `OnlyStrategyLedgerManager`；
* `OnlyFeeManager`；
* `OnlyMarginManager`；
* `OnlySettlementManager`；
* `OnlyExecutionProcessor`；
* Runtime 可变缓存。

## 2.5 Broker Projection 不等于 Runtime Truth

插件可以维护 Broker-side：

* Order Store；
* Trade Store；
* Account Projection；
* Position Projection。

这些是用于 Query 和 Reconciliation 的外部模拟证据，不是 Runtime 本地账务权威。

不得为了让两边数值强行相等而：

* 在 Virtual Broker 中复制 Runtime Fee 计算；
* 让插件直接读取 Runtime Account；
* 让插件直接读取 Strategy Ledger；
* 让插件重用 Runtime Manager；
* 让插件覆盖 Runtime 状态。

---

# 三、目标包结构

新增独立发行包：

```text
packages/
└── broker/
    └── onlyalpha-plugin-broker-virtual/
        ├── pyproject.toml
        ├── README.md
        ├── src/
        │   └── onlyalpha_plugin_broker_virtual/
        │       ├── __init__.py
        │       ├── descriptor.py
        │       ├── config.py
        │       ├── factory.py
        │       ├── gateway.py
        │       ├── scheduler.py
        │       ├── latency.py
        │       ├── slippage.py
        │       ├── matching/
        │       │   ├── __init__.py
        │       │   ├── base.py
        │       │   └── next_bar.py
        │       ├── projection/
        │       │   ├── __init__.py
        │       │   ├── orders.py
        │       │   ├── trades.py
        │       │   ├── account.py
        │       │   └── positions.py
        │       └── errors.py
        └── tests/
            ├── unit/
            ├── contract/
            └── integration/
```

发行包名称：

```text
onlyalpha-plugin-broker-virtual
```

Python 包名称：

```text
onlyalpha_plugin_broker_virtual
```

插件 ID：

```text
virtual
```

Entry Point：

```toml
[project.entry-points."onlyalpha.brokers"]
virtual = "onlyalpha_plugin_broker_virtual.factory:OnlyVirtualBrokerFactory"
```

根据实际实现可以调整插件内部文件拆分，但不得把 Virtual Broker 具体实现重新放回 Core。

更新根 Workspace：

```toml
[tool.uv.workspace]
members = [
    "packages/fake/onlyalpha-plugin-broker-virtual",
    "packages/provider/onlyalpha-plugin-tushare",
    "packages/provider/onlyalpha-plugin-miniqmt",
]
```

---

# 四、Core 需要保留的边界

Core 只保留通用 Broker 语言和运行端口。

至少检查并整理以下公共概念：

```text
OnlyBrokerGateway
OnlyBrokerFactory
OnlyBrokerCreateRequest
OnlyBrokerCapabilities
OnlyBrokerPluginCapabilities
OnlyBrokerOrderRequest
OnlyBrokerCancelRequest
OnlyBrokerQuery
OnlyBrokerOrderSnapshot
OnlyBrokerTradeSnapshot
OnlyBrokerAccountSnapshot
OnlyBrokerPositionSnapshot
OnlyBrokerInboundUpdate
OnlyBrokerTradeUpdate
OnlyBrokerOrderAcceptedUpdate
OnlyBrokerOrderRejectedUpdate
OnlyBrokerOrderCancelledUpdate
OnlyBrokerAccountUpdate
OnlyBrokerPositionUpdate
```

这些公共类型不得依赖 Virtual Broker 包。

---

# 五、重构通用 Broker Inbound Queue

当前任何带有 `Virtual` 命名的 Broker Queue 都应从 Runtime 通用路径中删除。

在 Core 中建立通用、有界、确定性的 Broker Inbound Queue，例如：

```python
class OnlyBrokerInboundQueue(Protocol):
    def put(self, update: OnlyBrokerInboundUpdate) -> None:
        ...

    def drain(self) -> tuple[OnlyBrokerInboundUpdate, ...]:
        ...

    def __len__(self) -> int:
        ...
```

Core 可以提供通用实现，例如：

```python
class OnlyBoundedBrokerInboundQueue:
    ...
```

要求：

* 不包含 Virtual Broker 语义；
* 支持容量限制；
* 顺序确定；
* 明确溢出策略；
* 可被 MiniQMT、Virtual Broker 和未来 Broker 共用；
* 测试属于 Core；
* Runtime 不再导入任何插件 Queue 类型。

删除：

```text
OnlyVirtualBrokerUpdateQueue
```

或将其能力完全重写为通用 Core Queue。

---

# 六、定义 Backtest Broker 的显式能力

Backtest Runtime 需要驱动模拟 Broker 处理市场数据和定时任务，但这不是所有 Broker Gateway 都具备的能力。

禁止把 `on_bar()`、`run_due()` 隐式加到通用实盘 Broker Gateway 上。

设计明确的 Backtest Simulation Port，例如：

```python
class OnlyDeterministicBrokerDriver(Protocol):
    def on_market_data(self, update: OnlyMarketDataInboundUpdate) -> None:
        ...

    def run_due(self) -> int:
        ...
```

也可以按当前数据模型选择以 `OnlyBar` 为输入，但必须满足：

* 名称不包含 Virtual；
* 能力只表达 Backtest Runtime 所需的确定性驱动；
* 与通用 Broker Gateway 分离；
* 不通过 `getattr` 获取；
* 不通过具体类型判断获取。

推荐让 Broker Factory 返回一个明确的组件对象：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerComponent:
    gateway: OnlyBrokerGateway
    deterministic_driver: OnlyDeterministicBrokerDriver | None
```

Backtest Runtime Factory 必须在构建阶段验证：

```text
Broker 声明 simulated_execution capability
且提供 deterministic_driver
```

否则在 Runtime 启动前明确失败。

不要在执行到第一根 Bar 时才发现接口缺失。

---

# 七、删除 Runtime 中的 Virtual Broker 具体配置

从通用 Core Runtime 配置中删除：

```python
virtual_broker_config: OnlyVirtualBrokerConfig | None
```

`OnlyRuntimeAssemblyConfig` 只能保存通用信息，例如：

```text
broker_gateway_id
account_initial_cash
market_rule_port
fee_resolver_config
market_fee_schedules
broker_fee_schedules
```

Virtual Broker 的配置全部由插件解析：

```yaml
brokers:
  - gateway_id: virtual-main
    plugin: virtual
    fees:
      mode: NONE
    extensions:
      matching:
        type: NEXT_BAR
      latency:
        submit_ns: 0
        acceptance_ns: 0
        fill_ns: 0
      slippage:
        type: NONE
      maximum_fill_quantity: null
```

Core 配置解析器只能保留通用 `extensions`，不得理解：

* Matching 类型；
* Slippage 类型；
* Latency 参数；
* Maximum Fill Quantity；
* Virtual Broker Store 配置。

这些全部由：

```text
onlyalpha_plugin_broker_virtual.config
onlyalpha_plugin_broker_virtual.factory
```

负责。

---

# 八、移除完整 MarketRuleEngine 的后置绑定

删除所有：

```python
bind_market_rules(...)
getattr(gateway, "bind_market_rules")
```

Virtual Broker 不得获得完整 Runtime `OnlyMarketRuleEngine` 实例。

先分析 Virtual Broker 当前为什么需要 Market Rule：

* Broker-side settlement projection；
* T+1 可用持仓；
* Position effect；
* Broker acceptance；
* 其他匹配或账户投影逻辑。

根据实际需要，在 Core 中定义最小只读 Port，例如：

```python
class OnlyBrokerSimulationRulePort(Protocol):
    def settlement_instruction(
        self,
        request: OnlyBrokerSimulationSettlementRequest,
    ) -> OnlyBrokerSimulationSettlementInstruction:
        ...
```

实际命名可调整，但必须满足：

* 只暴露 Virtual Broker 模拟外部状态所需的最少信息；
* 不暴露 Runtime Manager；
* 不暴露完整 Market Profile；
* 不允许插件修改 Market Rule 状态；
* 通过 `OnlyBrokerCreateRequest` 或明确的组件构造参数注入；
* 不使用全局单例；
* 不使用后置动态绑定。

如果分析后确认 Broker-side Projection 不需要 Market Rule，则直接删除该依赖，不要为了保留旧实现而创建多余 Port。

---

# 九、Runtime 必须拥有 Applied Trade Journal

当前 Result/Collector 不应在回测结束后通过：

```python
gateway.query_trades(...)
```

重新获取本地交易结果。

原因：

* Broker Query 返回的是外部 Projection；
* Result 应基于 Runtime 已成功提交的交易事务；
* Broker 中可能存在 Runtime 未接受、重复、乱序或需要对账的回报；
* Result 不应要求 Broker 实现 Query Trade 才能工作；
* Backtest Result 不应写死“必须是 Virtual Broker”。

在 Core 中增加明确的 Runtime-owned Applied Trade Journal，例如：

```python
class OnlyAppliedTradeJournal:
    def append(self, trade: OnlyAppliedTradeFact) -> None:
        ...

    def records(self) -> tuple[OnlyAppliedTradeFact, ...]:
        ...
```

要求：

1. 只有 ExecutionProcessor 完整事务成功后才能写入；
2. Duplicate Trade 不得重复写入；
3. Partial Mutation Failure 不得写入已成功交易；
4. Journal 中保存 Result 所需的不可变成交事实；
5. Collector、Backtest Result、Analytics 和 Artifact 从 Journal 读取；
6. Broker `query_trades()` 只用于 Broker 查询和 Reconciliation；
7. 删除：

   ```text
   product backtest requires Virtual Broker
   ```
8. Backtest Result 不得依赖具体 Broker 类型。

如果现有 Execution Audit 或其他 Journal 已经满足要求，应重用并正式命名其权威职责，不要无意义创建第三套重复存储。

---

# 十、重新定义 Virtual Broker 的职责

插件内部只保留模拟 Broker 所需职责。

## 10.1 Gateway

负责：

* Connect；
* Authenticate；
* Start；
* Stop；
* Submit；
* Cancel；
* Query；
* 标准 Broker Callback/Update 输出。

## 10.2 Matching

负责：

* 基于当前及历史已到达行情撮合；
* 禁止未来数据；
* Next-bar 语义；
* Limit/Market 支持范围；
* Partial Fill；
* Liquidity 限制。

## 10.3 Latency 与 Scheduler

负责：

* Submit latency；
* Acceptance latency；
* Cancel latency；
* Fill latency；
* 确定性任务顺序；
* 同时间事件稳定排序。

## 10.4 Slippage

负责生成模拟 Broker 成交价。

不得在 Slippage 模型中：

* 计算 Fee；
* 更新 Runtime Position；
* 更新 Runtime Account；
* 调用 Runtime Manager。

## 10.5 Broker Projection

负责：

* Broker Order Snapshot；
* Broker Trade Snapshot；
* Broker Account Snapshot；
* Broker Position Snapshot。

这些状态必须被文档明确标记为：

```text
external simulated broker projection
```

而不是：

```text
Runtime accounting truth
```

---

# 十一、Fee 边界

当前 Runtime Fee 权威链必须保持：

```text
market.fees + brokers[].fees
→ Runtime Assembly
→ OnlyFeeResolver
→ OnlyFeeInstruction
→ ExecutionProcessor
→ Position / Account / StrategyLedger / FeeManager
```

Virtual Broker：

* 不计算 Runtime 本地权威费用；
* Fill 不报告费用时：

  ```python
  reported_fee = None
  fee_reporting_mode = NONE
  ```
* 不得使用零金额伪装“Broker 已确认费用”；
* 不得持有第二套 Commission Formula；
* 不得直接访问 `OnlyFeeResolver`；
* 不得直接应用 `OnlyFeeInstruction`。

Broker-side Account Projection 与 Runtime Account 因本地 Fee 产生差异是允许的，该差异属于未来 Reconciliation 解释范围。

---

# 十二、默认 Engine 服务重构

当前 Core 默认服务不得直接：

```python
brokers.register(OnlyVirtualBrokerFactory())
```

修改为：

```text
Core 注册空的 Broker Factory Registry
→ Entry Point Discovery
→ 安装了 Virtual Broker 插件时发现 virtual
```

只安装 Core 时：

```python
import onlyalpha
```

必须成功。

但运行以下配置：

```yaml
plugin: virtual
```

必须在装配阶段明确失败：

```text
BROKER_PLUGIN_NOT_FOUND
```

不得：

* 自动安装；
* 自动回退；
* 从 Core 隐式创建 Virtual Broker；
* 使用测试 Fixture 代替插件。

---

# 十三、测试重构

允许删除和重写现有测试。测试必须按所有权重新划分。

## 13.1 Core Tests

Core 测试不能依赖 Virtual Broker 插件实现。

保留或新增：

```text
tests/broker/
tests/runtime/
tests/execution/
tests/result/
tests/plugin/
```

验证：

* Broker DTO；
* Broker Factory Contract；
* 通用 Inbound Queue；
* Broker Component；
* Deterministic Driver Protocol；
* ExecutionProcessor；
* Applied Trade Journal；
* Result 不查询 Broker 获取本地成交；
* 插件缺失错误；
* Core 不导入具体插件。

Core 纵切面需要 Broker 时，创建最小的 Test Broker Fixture。

Test Broker 应位于：

```text
tests/fixtures/
```

或测试插件 Distribution 中，不得进入生产 Core。

## 13.2 Virtual Broker Plugin Tests

移动或重写到：

```text
packages/fake/onlyalpha-plugin-broker-virtual/tests/
```

至少覆盖：

* Descriptor；
* Entry Point；
* Config parsing；
* Factory validation；
* Gateway lifecycle；
* Submit；
* Reject；
* Cancel；
* Next-bar matching；
* Partial fill；
* Maximum fill quantity；
* Slippage；
* Latency；
* Scheduler deterministic order；
* LONG open/close；
* SHORT open/close；
* Broker Account Projection；
* Broker Position Projection；
* Update sequence；
* Duplicate prevention；
* Plugin health；
* No future-data matching。

## 13.3 产品集成测试

产品测试安装 Core 和 Virtual Broker 插件，验证：

```text
Config
→ Entry Point Discovery
→ Engine
→ Backtest Runtime
→ Virtual Broker Plugin
→ ExecutionProcessor
→ Result
→ Artifact
```

必须覆盖：

1. Generic T0 Backtest；
2. A 股 T+1；
3. Futures LONG；
4. Futures SHORT；
5. Partial Fill；
6. Fee NONE；
7. Market Fee；
8. Broker Plugin 缺失；
9. 重复运行指纹一致；
10. 多 Cluster 共享 Runtime。

## 13.4 独立安装验证

增加干净环境 Smoke：

### 只安装 Core

验证：

```text
import onlyalpha
Core public API import
Core 无 onlyalpha.broker.virtual
Core 无 Virtual Broker Entry Point
```

### 安装 Core + Virtual Plugin

验证：

```text
import onlyalpha_plugin_broker_virtual
Entry Point virtual 可加载
Factory Descriptor 正确
最小 Backtest 可运行
```

### 不安装 Virtual Plugin

配置引用 `plugin: virtual` 时必须明确失败。

---

# 十四、示例迁移

更新所有依赖 Virtual Broker 的示例。

示例配置中的：

```yaml
plugin: virtual
```

可以保持不变。

但是 README 必须说明需要安装：

```bash
pip install onlyalpha onlyalpha-plugin-broker-virtual
```

Monorepo 开发环境则通过 Workspace 安装。

检查并更新：

```text
examples/configs/
tests/fixtures/
tests/integration_demo/
tests/scenario/
tests/conformance/
README.md
docs/
```

不得在示例 Python 代码中直接导入：

```python
onlyalpha.broker.virtual
```

所有产品示例必须通过：

```text
配置
→ Plugin ID
→ Entry Point Discovery
```

使用 Virtual Broker。

---

# 十五、CI 调整

增加独立 Virtual Broker 插件门禁。

推荐 CI 结构：

```text
Metadata and workspace

Core / Linux
Core / Windows
Core / macOS

Virtual Broker Plugin / Linux
Virtual Broker Plugin / Windows
Virtual Broker Plugin / macOS

Tushare / Linux
Tushare / Windows
Tushare / macOS

MiniQMT / Windows

Product scenarios and integration
Build smoke / onlyalpha
Build smoke / onlyalpha-plugin-broker-virtual
Build smoke / onlyalpha-plugin-tushare
Build smoke / onlyalpha-plugin-miniqmt
Required CI
```

Virtual Broker 插件门禁至少执行：

```bash
ruff check
ruff format --check
mypy
pytest
build
twine check
clean-wheel install
entry-point load
```

Core 门禁增加禁止具体插件 Import 的检查，至少匹配：

```text
onlyalpha_plugin_broker_virtual
onlyalpha.broker.virtual
OnlyVirtualBroker
```

注意：测试 Fixture 中可以存在 Test Broker，但生产 `src/onlyalpha` 中不得出现具体 Virtual Broker 类型。

---

# 十六、文档调整

更新当前正式文档：

```text
README.md
AGENTS.md
docs/architecture.md
docs/runtime.md
docs/virtual_broker.md
docs/execution_processor.md
docs/results_framework.md
docs/plugin*.md
HANDOFF.md
NEXT.md
```

新增 ADR，例如：

```text
docs/adr/0032-extract-virtual-broker-as-plugin.md
```

ADR 至少说明：

* 为什么 Virtual Broker 不属于 Core；
* Core 与插件的依赖方向；
* Runtime Truth 与 Broker Projection；
* 为什么 Result 使用 Applied Trade Journal；
* 为什么不保留历史兼容层；
* 为什么 Backtest Driver 与通用 Broker Gateway 分离；
* Fee、Settlement、Margin 的所有权；
* 独立安装行为；
* 后续对 Paper Runtime 的影响。

历史 Prompt 和历史 Report 可以保留，但若其中内容会被误认为当前架构，必须增加明确的历史标记。

---

# 十七、禁止事项

本任务中禁止：

1. 只移动目录后修复 Import。
2. 在 Core 中保留 Virtual Broker Wrapper。
3. 创建兼容 Alias。
4. 使用动态 `getattr` 发现能力。
5. 使用具体类型判断插件类型。
6. 使用模块级全局 Broker 单例。
7. 让插件访问 Runtime Manager。
8. 让 Result 查询 Broker 作为本地成交权威。
9. 让 Virtual Broker 计算 Runtime 本地 Fee。
10. 让 Core 自动注册 Virtual Broker。
11. 为通过测试而跳过、xfail 或放宽不变量。
12. 为保持旧 Golden Data 而保留错误架构。
13. 声称未执行的外部测试已经通过。
14. 发布包或推送代码，除非明确收到额外指令。

---

# 十八、实施顺序

必须按以下顺序实施。

## Phase 1：依赖审计

输出当前：

* Core 到 Virtual Broker 的 Import；
* Runtime 对 Virtual Broker 的调用；
* Result 对 Broker Query 的依赖；
* 测试对 Virtual Broker 的依赖；
* 示例和文档引用；
* CI 和 Workspace 配置。

## Phase 2：先建立 Core 通用边界

实现：

* 通用 Broker Inbound Queue；
* Broker Component；
* Deterministic Broker Driver；
* 必要的受限 Simulation Rule Port；
* Applied Trade Journal；
* Result 从 Runtime Journal 读取。

此阶段 Virtual Broker 代码可以暂时仍在原目录，但生产 Core 已不能依赖其具体类型。

## Phase 3：建立独立插件包

创建：

```text
packages/fake/onlyalpha-plugin-broker-virtual
```

迁移并重构 Virtual Broker 实现。

## Phase 4：删除 Core 旧实现

删除：

```text
src/onlyalpha/broker/virtual/
```

以及所有：

```text
OnlyVirtualBroker*
virtual_broker_config
bind_market_rules
```

在 Core 中的残留。

## Phase 5：迁移测试和示例

按所有权拆分：

* Core Contract；
* Plugin Unit/Contract；
* Product Integration；
* Examples。

允许更新 Golden Fingerprint，但必须说明变化原因。不得无解释地覆盖 Golden 文件。

## Phase 6：更新 CI 和文档

完成独立包门禁、构建和安装验证。

## Phase 7：完整回归

执行全部适用命令并记录真实结果。

---

# 十九、验收标准

以下条件必须全部满足。

## 架构边界

```text
src/onlyalpha
```

中不存在：

```text
onlyalpha.broker.virtual
OnlyVirtualBrokerGateway
OnlyVirtualBrokerFactory
OnlyVirtualBrokerConfig
OnlyVirtualBrokerUpdateQueue
OnlyVirtualBrokerScheduler
OnlyNextBarMatchingEngine
```

Core 不导入：

```text
onlyalpha_plugin_broker_virtual
```

## 插件发现

安装插件后：

```text
onlyalpha.brokers
└── virtual
```

可通过 Entry Point 发现。

未安装插件时，配置引用 `virtual` 会明确失败。

## Runtime

Backtest Runtime：

* 不判断具体 Broker 类型；
* 不使用动态属性探测；
* 只使用 Core Broker Port；
* 只通过 Deterministic Driver 驱动模拟 Broker；
* 不从 Broker Query 获取本地成交权威；
* Result 来自 Runtime Applied Trade Journal。

## Fee

* Runtime FeeResolver 仍为本地唯一权威；
* Virtual Broker 无本地权威 Fee 计算；
* Fill 未报告费用时使用 `None + NONE`；
* Fee 现有测试和 Golden 语义保持正确。

## 测试

以下全部通过：

```text
Core tests
Virtual Broker plugin tests
Tushare tests
MiniQMT offline tests
Integration tests
Scenario tests
Conformance tests
Integration demo tests
Ruff
Ruff format
Core Mypy
Virtual Plugin Mypy
Tushare Mypy
MiniQMT Mypy（若当前平台可运行）
Build smoke
Clean installation smoke
Entry Point smoke
```

## 确定性

同一配置重复运行必须保持：

```text
Result fingerprint 相同
Artifact fingerprint 相同
Order/Trade 序列相同
Broker Update 顺序相同
```

## 文档

当前正式文档必须准确描述：

```text
Virtual Broker 是独立插件
Core 不包含 Virtual Broker 实现
Backtest 需要安装模拟 Broker 插件
Runtime Truth 与 Broker Projection 分离
```

---

# 二十、完成后输出报告

任务完成后给出结构化报告。

## 1. 架构变化

说明：

* Core 删除了什么；
* Core 新增了哪些通用 Port；
* 插件拥有了什么；
* Runtime 和 Result 如何解耦 Broker 实现。

## 2. 文件变化

列出：

* 新增文件；
* 删除文件；
* 移动或重写文件；
* 测试归属变化。

## 3. 公共 API 变化

列出所有删除和新增的 Core 公共 API。

明确说明不存在兼容层。

## 4. 测试结果

提供真实命令和结果，例如：

```text
Core: N passed
Virtual Broker: N passed
Tushare: N passed
MiniQMT: N passed / N skipped
Scenario: N passed
Conformance: N passed
Ruff: passed
Mypy: passed
Build smoke: passed
```

不得伪造数量。

## 5. 未完成事项

明确列出：

* 外部网络测试；
* 本地 QMT 测试；
* Paper Runtime；
* Live Runtime；
* Broker Fee Statement；
* Runtime Recovery；

中哪些未执行或不属于本任务。

---

# 最终目标

重构完成后，工程应满足：

```text
OnlyAlpha Core
    是可独立安装、无具体 Broker 实现的量化交易内核

onlyalpha-plugin-broker-virtual
    是通过公开 Broker SPI 实现的确定性模拟券商

Backtest Runtime
    依赖通用 Broker 能力，不依赖 Virtual Broker 类型

Result
    基于 Runtime 已应用交易事实，不基于 Broker Query

Virtual Broker
    可替换、可独立测试、可独立构建、可独立发现
```

优先保证边界正确、事务正确和测试可信。不要为了减少改动量保留错误耦合。
