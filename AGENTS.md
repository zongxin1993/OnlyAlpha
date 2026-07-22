# OnlyAlpha 工程实施指南

本文档面向在 OnlyAlpha 仓库内工作的开发者、代码生成 Agent、审查 Agent 和自动化工具，用于规定工程边界、实现原则、验证方式和交付标准。

本文档作用于整个 Monorepo。若未来某个子目录存在更近的 `AGENTS.md`，则子目录文档可以补充本文件，但不得破坏根文档规定的核心架构、不变量和依赖方向。

---

## 1. 项目身份

OnlyAlpha 是一个独立、从零设计的量化交易系统。

必须遵守：

* 永远以第一性原则出发处理问题；
* 不把 OnlyAlpha 描述为其他项目的重构版本；
* 不从其他工程复制内部实现形成隐式耦合；
* 历史分析文档只能作为研究材料，不能覆盖当前架构决策，一切以源码实现为准；
* 所有新增实现必须首先满足 OnlyAlpha 当前公开模型、测试和 ADR。

OnlyAlpha 当前是一个 Monorepo：

```text
OnlyAlpha/
├── src/onlyalpha/
├── packages/fake/onlyalpha-plugin-broker-virtual/
├── packages/provider/onlyalpha-plugin-tushare/
├── packages/provider/onlyalpha-plugin-miniqmt/
├── examples/
├── tests/
├── scripts/
├── docs/
└── .github/
```

---

## 2. 事实来源优先级

发生文档、Prompt、测试和源码描述冲突时，按以下顺序判断：

```text
1. 当前可执行源码和正式公共接口
2. 当前自动化测试和架构门禁
3. 已接受且未被替代的 ADR
4. 当前组件文档
5. README.md 和 AGENTS.md
6. HANDOFF.md
7. docs/reports/
8. prompts/
```

`prompts/` 和历史报告描述的是实施过程，不是当前代码的自动事实来源。

修改架构前必须：

1. 阅读目标组件当前源码；
2. 阅读相关测试；
3. 查找相关 ADR；
4. 查找现有公共接口和 Factory；
5. 确认不存在已经实现的同类能力；
6. 再决定新增、替换或删除。

禁止仅根据 Prompt 创建第二套实现。

---

## 3. 不可破坏的顶层架构

### 3.1 唯一产品入口

`OnlyEngine` 是 OnlyAlpha 唯一产品级运行入口。

正式产品链必须经过：

```text
CLI / Application
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ OnlyRuntime
→ OnlyCluster
```

禁止：

* CLI 直接实例化 Manager；
* CLI 直接执行 Backtest 内部循环；
* Scenario Runner 绕过 Engine；
* 示例手工装配多个 Manager 伪造产品运行；
* 新建第二套 Engine Service；
* 新建仅供某个市场或插件使用的平行产品入口。

文件路径加载只是适配层。核心入口为：

```python
engine.add_cluster(config)
```

文件入口为：

```python
engine.add_cluster_from_file(path)
```

### 3.2 Engine 职责

Engine 负责：

* Cluster Definition 注册；
* 配置和扩展类型验证；
* 配置指纹；
* Runtime 兼容性规划；
* Runtime/Cluster Session；
* 共享基础设施引用计数；
* 生命周期；
* Runtime 执行；
* 结果汇总；
* `user_data` 输出；
* 失败回滚和资源释放。

Engine 不负责：

* 策略算法；
* 指标计算；
* 券商 SDK 调用；
* 具体撮合模型；
* 具体费用公式；
* SQL 业务逻辑；
* Web 展示；
* 市场规则硬编码。

一个 Engine 实例只能完整运行一次。

### 3.3 Runtime 所有权

Runtime 是所有可变交易状态的资源所有者。

每个 Runtime 必须拥有或独占：

* Clock；
* Event Bus；
* MarketData Pipeline；
* MarketData Cache；
* Bar Aggregation；
* MarketData Inbound Queue；
* Broker Inbound Queue；
* Order Manager；
* Position Manager；
* Allocation Manager；
* Strategy Ledger Manager；
* Account Manager；
* Risk Service；
* ExecutionProcessor；
* Settlement/Margin 服务；
* Runtime 级日志、指标和审计。

Cluster、Strategy、Factor、Plugin 和 Broker Gateway 不得持有 Runtime Manager。

### 3.4 Cluster 隔离

一个 Cluster：

* 只持有一个 Strategy；
* 可以持有多个 Factor；
* 每个 Factor 可以创建多个 Indicator；
* 拥有独立的 Strategy、Factor、Indicator 和 Ledger Scope；
* 只能通过受限 Context 使用 Runtime 能力；
* 不得读取其他 Cluster 的订单、持仓分配、账本或私有状态。

固定调度顺序：

```text
MarketData
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ Order
```

调度顺序不得依赖：

* 字典顺序；
* 注册顺序；
* EventBus handler priority；
* Python 导入顺序；
* 外部 SDK 回调先后偶然性。

---

## 4. Monorepo 包职责

### 4.1 Core

路径：

```text
src/onlyalpha/
```

Core 承载：

* 公共领域模型；
* Engine、Runtime 和 Cluster；
* 公共 Port 和 Protocol；
* 配置模型；
* 内建 Synthetic DataSource；
* 内建 Scenario Exact DataSource；
* 通用 Broker SPI、Inbound Queue、Runtime Committed Execution Journal；
* 通用 Indicator；
* 结果、分析、制品和报告；
* Plugin SPI；
* Market Profile 和规则基础设施。

Core 不得依赖：

```text
onlyalpha_plugin_broker_virtual
onlyalpha_plugin_tushare
onlyalpha_plugin_miniqmt
```

Core 不得导入任何具体官方插件包。

### 4.2 Virtual Broker 插件

路径：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
```

职责：模拟外部 Broker 的接收、拒绝、撤单、Next-Bar 撮合、延迟、滑点、确定性调度和查询投影。
插件只通过公共 Broker SPI 输出标准 Update；不得持有 Runtime Manager、完整 MarketRuleEngine、FeeResolver，
也不得把 Broker Projection 当作 Runtime accounting truth。

### 4.3 Tushare 插件

路径：

```text
packages/provider/onlyalpha-plugin-tushare/
```

职责：

* Tushare SDK 加载；
* Tushare 配置解析；
* 历史行情请求；
* 数据标准化；
* 缓存协作；
* DataSource Factory 和 Entry Point；
* 插件 Doctor。

不得：

* 在模块导入阶段访问网络；
* 在默认测试中要求 Token；
* 直接修改 Runtime Clock；
* 绕过 Historical Replay；
* 返回非标准 OnlyAlpha Domain 数据；
* 导入 Engine 或 Runtime 私有实现。

### 4.4 MiniQMT 插件

路径：

```text
packages/provider/onlyalpha-plugin-miniqmt/
```

职责：

* MiniQMT/xtquant SDK 边界；
* Historical/Realtime DataSource Adapter；
* Broker Gateway；
* SDK Callback 标准化；
* DataSource/Broker Factory 和 Entry Point；
* 插件 Doctor；
* 重连和同步边界。

必须：

* 保持 Windows-only 运行语义；
* 延迟加载 `xtquant`；
* 允许非 Windows 环境完成元数据解析和构建；
* 将无类型 SDK 限制在 Adapter 边界；
* 将 SDK 回调转换成标准 Broker Update；
* 先写入 Runtime-owned Inbound Queue；
* 不直接修改 Order、Position、Account 或 Ledger Manager；
* 不把 SDK submit 成功解释为 Venue Accepted；
* 不把 cancel 请求成功解释为订单已经 Cancelled。

### 4.4 Examples

路径：

```text
examples/
```

Examples 用于：

* 展示公共 Strategy/Factor/Config API；
* 提供可运行配置；
* 验证正式 Engine 产品链；
* 说明如何替换 DataSource 和 Broker。

示例代码不得成为 Core 的运行依赖。

可复用、面向产品或外部 SDK 的实现应进入正式 Workspace 插件，不得长期停留在 Examples。

### 4.5 Tests

Core 测试位于：

```text
tests/
```

插件测试分别位于各插件自己的 `tests/`。

不同 distribution 的顶层测试目录不得在同一个 Pytest 进程中作为 `tests` 包同时收集。

---

## 5. 依赖方向

总体依赖方向：

```text
Domain
  ↑
Core utilities / Clock / Event / Ports
  ↑
Order / Position / Account / Risk / MarketData
  ↑
Runtime / Cluster
  ↑
Engine / Application
  ↑
CLI
```

插件方向：

```text
Official Plugin
→ onlyalpha.plugin.api
→ 明确公开的 Domain / Port
```

禁止内层反向依赖外层。

### Domain 禁止依赖

`onlyalpha.domain` 不得依赖：

* Engine；
* Runtime；
* Cluster；
* Plugin；
* CLI；
* Storage 实现；
* 数据库；
* 网络；
* 外部 SDK；
* Web；
* 测试代码。

### 外部插件禁止依赖

外部插件不得依赖：

* Runtime Assembler；
* Manager 实现；
* Composition Root；
* Engine 内部 Session；
* 内部 Registry 容器；
* 测试 Fixture；
* 其他具体插件；
* 私有模块状态。

---

## 6. 公共 API 和命名

### 6.1 `Only` 前缀

所有新增公开类型必须使用 `Only` 前缀，包括：

* class；
* Protocol；
* dataclass；
* enum；
* exception；
* identifier；
* snapshot；
* result；
* request；
* command；
* event；
* service；
* factory；
* registry。

函数、变量和模块继续使用 `snake_case`。

常量使用：

```text
UPPER_SNAKE_CASE
```

### 6.2 公共导出

新增公共 API 时必须：

1. 放入正确的顶层模块；
2. 更新对应 `__init__.py`；
3. 明确 `__all__`；
4. 增加公共导入测试；
5. 避免将内部 Manager 和 Assembler 导出；
6. 更新文档；
7. 评估插件兼容性。

外部插件的稳定入口是：

```python
onlyalpha.plugin.api
```

不得要求插件从多个内部模块拼接 SPI。

---

## 7. Python 和类型规范

当前工程只支持：

```text
Python 3.12
```

代码规范：

* 四空格缩进；
* 行宽 120；
* 双引号；
* Ruff 负责格式化和 import 排序；
* Mypy 使用 strict 模式；
* 所有正式函数和方法补齐类型；
* 优先使用 `collections.abc`；
* 避免无意义 `Any`；
* `Any` 只允许停留在无法控制的 SDK 边界；
* SDK `Any` 必须尽快转换成强类型 DTO；
* 不通过全局关闭 Mypy 错误码隐藏债务；
* 对第三方无类型包使用精确 module override。

推荐数据对象：

```python
@dataclass(frozen=True, slots=True)
class OnlyExample:
    ...
```

可变 Manager 或生命周期 Session 可以使用非 frozen dataclass，但必须明确所有权。

禁止：

* 裸 `dict` 作为长期公共业务模型；
* 无类型回调跨越多个架构层；
* 使用 `object` 后在业务深处依赖动态属性；
* 通过 `# type: ignore` 隐藏内部类型设计错误；
* 在整个插件上关闭 strict Mypy。

---

## 8. 金融数值规则

金额、价格、数量、手续费、保证金和 PnL 的真值不得使用 `float`。

必须使用：

* `Decimal`；
* `OnlyPrice`；
* `OnlyQuantity`；
* `OnlyMoney`；
* `OnlyCurrency`；
* 对应精度和增量约束。

允许在 SDK 最外层进行：

```python
float(price.value)
```

但只能用于调用要求浮点参数的第三方 SDK。返回后必须恢复成精确领域值。

不得：

* 使用二进制浮点累计费用；
* 通过字符串拼接计算金额；
* 忽略币种；
* 在不同精度值之间静默转换；
* 在 Domain 中读取默认货币配置。

---

## 9. 时间和日历

所有业务绝对时间统一使用 UTC。

必须：

* 拒绝 naive datetime；
* Runtime Clock 返回 UTC；
* Backtest Clock 单调推进；
* 只有 Historical Replay 可以因数据推进 Backtest Clock；
* Cluster 不得推进 Clock；
* Strategy、Factor 和 Domain 不得调用系统当前时间；
* 交易日和 Session 由 TradingCalendar 解释；
* 不得使用 `datetime.date()` 直接推导市场 TradingDay；
* 不得假设 UTC 日期等于市场交易日；
* 夜盘、午休、DST 和提前收盘必须由 Calendar 处理；
* Timer 顺序必须稳定且可重放。

Monotonic Clock 只用于性能和等待，不作为持久业务时间。

---

## 10. Event 和状态迁移

Event 只表达已经发生的事实。

禁止使用 EventBus 驱动核心状态迁移。

状态修改应通过：

* Command；
* Service；
* Manager 方法；
* ExecutionProcessor；
* 明确同步调用。

正确顺序：

```text
验证
→ 修改状态
→ 检查不变量
→ 提交事实
→ 发布 Event
```

错误顺序：

```text
发布 Event
→ 依赖订阅者修改关键状态
```

EventBus 不承担：

* Order 状态机；
* Position 记账；
* Account 记账；
* Risk Reservation；
* Settlement；
* Margin；
* Broker Update 排序。

---

## 11. Strategy、Factor 和 Indicator

### Strategy

Strategy：

* 是交易决策单元；
* 读取 Factor Snapshot/Score；
* 维护私有决策状态；
* 只通过 `ctx.orders` 下单；
* 通过 Context 读取自己的 Position、Account、Ledger 和 Risk View；
* 不直接读取 Indicator；
* 不直接访问 Broker、Manager、Runtime 或 EventBus。

### Factor

Factor：

* 可以读取 MarketData；
* 可以创建和持有 Indicator；
* 输出强类型 Snapshot 和 Score；
* 不具有下单能力；
* 不修改 Order、Position、Ledger、Account 或 Risk；
* 依赖关系必须进入稳定依赖图；
* 缺失依赖和循环依赖在组装阶段失败。

### Indicator

Indicator：

* 是最底层无交易副作用计算单元；
* 输入必须来自已标准化 MarketData；
* 输出强类型 Snapshot；
* 可包含 Canonical Score；
* 实例按 Runtime/Cluster/Factor/Indicator Scope 隔离；
* Runtime 和 Assembler 不得识别 MACD、RSI 等具体指标。

---

## 12. MarketData

行情平面和交易执行平面必须分离。

历史链：

```text
Historical DataSource
→ Historical Replay
→ Backtest Clock
→ MarketData Processor
→ MarketData Pipeline
→ Dispatcher
→ Cluster
```

实时链：

```text
MarketData Gateway
→ MarketData Inbound Queue
→ MarketData Processor
→ MarketData Pipeline
→ Dispatcher
→ Cluster
```

必须保证：

* 实时和历史使用相同 Domain 类型；
* Source、Sequence、Version、UTC 双时间和 Quality 可追踪；
* Gap Detection 理解 Calendar 和 Session；
* Derived Bar 在 Runtime 层生成；
* Strategy 默认只读取 Closed Bar；
* 一个逻辑时间片内 Cluster 最多执行一次主 Bar 回调；
* 回测与实盘数据准备顺序一致；
* Cluster 不访问 DataSource、ReplayService、Queue 或 Processor。

---

## 13. Broker 和 Execution

Broker Gateway 只负责外部适配，不负责本地业务状态。

所有 Broker 回报必须：

```text
SDK Callback
→ 标准 Broker Update
→ Runtime Broker Inbound Queue
→ ExecutionProcessor
```

ExecutionProcessor 是唯一业务入口，固定协调：

```text
Order
→ Position
→ Allocation
→ Strategy Ledger
→ Account
→ Reservation
→ Risk
→ Invariant
→ Event
```

必须保证：

* 重复 Update 幂等；
* 重复 Trade 幂等；
* 迟到 Update 不导致状态回退；
* 无法安全处理的乱序 Trade 进入 Reconciliation；
* 中途失败不得发布完整成功事实；
* Broker Snapshot 不得静默覆盖本地 Order/Position/Account 历史；
* Virtual Broker 与真实 Broker 使用相同 Broker Update API；
* Matching Engine 不得读取未来数据；
* Commission、Slippage、Latency 分离建模；
* `market.fees` 和 `brokers[].fees` 必须经 Runtime Assembly 显式进入唯一 Fee Resolver，未知 Schedule 在启动前失败；
* submit 返回只表示请求是否被 SDK 接收；
* Venue Accepted、Fill、Cancelled 必须来自标准异步回报。

---

## 14. Risk、Position、Ledger 和 Account

### Risk

* 每个 Runtime 独占 Risk 状态；
* Mandatory System Rules 不可由 Cluster 删除；
* 每次 submit 必须重新执行 Pre-Trade Risk；
* `REJECT` 和 `ERROR` 都不得创建 Order；
* Risk ERROR 默认 Fail Closed；
* ACCEPT 后立即建立 Reservation。

### Position

* Account Position 和 Cluster Allocation 分离；
* 无法归因的持仓进入 Unallocated；
* T+1 和今昨仓使用 Settlement Bucket；
* Available Quantity 是派生值；
* Broker 冻结和本地 Reservation 分离；
* Broker Snapshot 不覆盖本地历史。

### Strategy Ledger

* 每个 Cluster 拥有独立虚拟账；
* 券商真实账户账与策略账分离；
* 收益基于本 Cluster 的 Trade、Fee 和 Allocation；
* `ctx.ledger` 只提供不可变 Snapshot。

### Account

* Account 是 Runtime-owned 账户级本地真值；
* AccountManager、Virtual Broker 和 StrategyLedger 不共享内部可变对象；
* Account、Position 和 Ledger 更新必须处于同一 ExecutionProcessor 编排中。

---

## 15. Market Profile 和规则

市场行为必须来自版本化 Market Profile 和 Rule Engine。

链路：

```text
OnlyMarketConfig
→ Market Profile Registry
→ Resolver
→ Compiler
→ Compiled Market Rules
→ OnlyMarketRuleEngine
→ Restricted Runtime Ports
```

禁止：

* 在 Virtual Broker 中写死 A 股 T+1；
* 在 Risk 中使用市场名称分支；
* 在 Position 中根据 Venue 字符串决定规则；
* 在 Strategy 中实现交易所规则；
* 在 Broker 插件中复制通用 Market Profile；
* 假设整个回测区间只有一个市场规则版本。

Profile 版本和 Profile Family 是不同身份。

当前内建 Profile 和 Conformance 基础仍处于实验阶段。不得把领域模型存在或 Parser 测试通过描述为完整市场认证。

---

## 16. 配置规则

一个配置文档只能定义一个 Cluster。

正式类型：

```python
OnlyClusterRunConfig
```

顶层区段：

```text
schema_version
cluster
market
runtime
reference_data
universes
data_sources
accounts
brokers
strategy
factors
output
```

要求：

* `market` 必填；
* 禁止顶层 `clusters`；
* DataSource/Broker 使用 `plugin`；
* Strategy/Factor 使用 `class_path` 和 `config_path`；
* 组件专用字段放入 `extensions`；
* 通用 Parser 不理解插件内部配置；
* Factory 负责解析自己拥有的 `extensions`；
* 未知字段默认拒绝；
* 所有配置生成标准化 Payload 和稳定指纹；
* 同一共享资源 ID 的配置指纹冲突必须拒绝；
* Web/Application 未来通过 Mapping 创建相同强类型配置，不建立第二套配置模型。

---

## 17. 插件开发规则

外部插件从：

```python
onlyalpha.plugin.api
```

导入 SPI。

DataSource Entry Point：

```text
onlyalpha.data_sources
```

Broker Entry Point：

```text
onlyalpha.brokers
```

每个插件必须提供：

* `OnlyPluginDescriptor`；
* API Version；
* Plugin Version；
* Capability；
* Factory；
* `parse_config()`；
* `validate_request()`；
* `create()`；
* 生命周期；
* Health；
* 单元测试；
* Entry Point 加载测试；
* wheel 安装 Smoke Test；
* README；
* `py.typed`。

插件不得在导入阶段：

* 访问网络；
* 打开数据库；
* 启动线程；
* 连接券商；
* 读取用户 Token；
* 创建 Runtime 资源。

所有此类操作必须推迟到 Factory/Create/Lifecycle。

---

## 18. Result、Artifact 和 user_data

Runtime 和 Result 不直接写文件。

正确职责：

```text
Runtime
→ immutable Result
→ Analytics
→ Artifact Writer
→ Report
```

所有非源码运行产物必须写入：

```text
user_data/
```

不得写入：

* `src/`；
* `packages/`；
* `examples/`；
* `tests/`；
* 仓库根目录；
* 系统临时目录作为最终结果。

结果必须包含或支持：

* 结构化状态；
* 标准事实；
* 诊断；
* 最终 Snapshot；
* 配置指纹；
* 数据版本；
* 确定性指纹；
* JSON 兼容投影；
* 零行稳定 Schema；
* 原子写入。

---

## 19. 测试规范

### 19.1 测试层次

至少区分：

```text
Unit
Contract
Integration
Scenario
Conformance
External
```

### 19.2 Core 测试

```bash
uv run pytest tests -q
```

### 19.3 插件测试

Tushare：

```bash
uv run pytest \
  packages/provider/onlyalpha-plugin-tushare/tests \
  -q
```

MiniQMT：

```bash
uv run pytest \
  packages/provider/onlyalpha-plugin-miniqmt/tests \
  -q
```

不得将三个顶层 `tests` 包放进同一个 Pytest 收集进程。

### 19.4 外部测试

外部测试必须使用 Marker：

```text
external
integration
requires_network
requires_tushare
requires_local_qmt
windows
slow
```

默认 CI 不运行真实网络或真实交易。

Tushare 真实测试需要：

```text
ONLYALPHA_TUSHARE_TOKEN
```

MiniQMT 真实历史测试需要：

```text
ONLYALPHA_MINIQMT_REAL_HISTORY=1
```

真实交易测试不得在普通 GitHub hosted runner 或普通开发提交中自动执行。

### 19.5 确定性测试

涉及回测、Clock、订单、成交、持仓、Ledger、Account、Market Rule 和 Scenario 的关键测试应使用：

* 固定 UTC 时间；
* 固定输入数据；
* 固定随机种子；
* 精确 Decimal；
* 固定 ID；
* 固定 Event 顺序；
* 稳定序列化；
* 重复运行指纹比较。

不得使用长时间 `sleep` 验证业务顺序。

### 19.6 禁止隐藏失败

禁止：

* 删除历史断言使测试通过；
* 无理由增加 Skip；
* 捕获异常后不检查；
* 将失败测试移动到默认不收集目录；
* 使用 `xfail` 隐藏已知回归；
* 只测试 Parser 而宣称产品链完成；
* 手工构造最终 Fill 绕过 Broker Queue；
* 修改 Manager 状态制造期望结果。

---

## 20. 本地质量门禁

同步环境：

```bash
uv sync --python 3.12 --all-packages --all-groups
```

Ruff：

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
```

Mypy Core：

```bash
uv run mypy src/onlyalpha
```

Mypy Tushare：

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
```

Mypy MiniQMT：

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

Pre-commit：

```bash
uv run pre-commit run --all-files
```

锁文件：

```bash
uv lock --check
```

版本一致性：

```bash
uv run python scripts/version_sync.py check
```

Git 差异：

```bash
git diff --check
```

CI 只能检查，不得自动修改源码。

---

## 21. 版本和依赖策略

正式 Workspace distribution 使用 Lockstep Versioning：

```text
onlyalpha
onlyalpha-plugin-tushare
onlyalpha-plugin-miniqmt
```

必须具有相同版本：

```text
X.Y.Z
```

插件必须精确依赖：

```text
onlyalpha==X.Y.Z
```

根 `pyproject.toml` 的 Core 版本是版本权威。

版本修改必须使用：

```bash
uv run python scripts/version_sync.py set X.Y.Z
```

不得手工分别修改多个 `pyproject.toml`。

版本检查负责验证：

* 正式包版本一致；
* 插件 Core 依赖一致；
* Python 版本约束一致；
* Workspace 成员完整；
* 锁文件同步。

开发工具只能放入开发依赖，不得进入 Core 运行时依赖。

公共仓库不得强制绑定区域性 PyPI 镜像。

---

## 22. 文档规则

新增或修改能力时必须同步更新对应文档。

至少考虑：

* `README.md`；
* `AGENTS.md`；
* `docs/architecture.md`；
* 对应组件文档；
* 相关 ADR；
* Plugin README；
* `docs/testing.md`；
* `docs/roadmap.md`；
* 发布说明。

禁止：

* 文档继续描述已经取消的三仓结构；
* 将历史 Prompt 当成当前架构；
* 声称未通过完整产品纵切面的能力已经完成；
* 只描述接口存在而不说明产品闭环状态；
* 使用“支持实盘”描述只有 Adapter 骨架的能力；
* 使用过时文件路径；
* 记录无法复现的测试通过结果。

历史方案应标记：

```text
Superseded
Deprecated
Historical
```

而不是继续作为当前规范。

---

## 23. Git 和 Pull Request

提交信息使用简洁前缀：

```text
Feat:
Fix:
Refactor:
Chore:
Docs:
Test:
Build:
CI:
```

每个 Commit 应聚焦一个边界。

Pull Request 必须说明：

* 变更目标；
* 当前问题；
* 方案；
* 架构边界；
* 公共 API 变化；
* 配置变化；
* 数据迁移；
* 确定性影响；
* 运行时和平台影响；
* 已执行测试；
* 未执行外部测试；
* 已知限制；
* 文档更新。

不得提交：

* Token；
* 券商账户信息；
* `.env`；
* `.pypirc`；
* QMT 用户数据；
* `user_data`；
* Cache；
* 构建目录；
* 测试输出；
* 私钥；
* 真实交易日志。

---

## 24. 禁止事项

禁止创建：

* 第二套 Engine；
* 第二套 Runtime 产品入口；
* 第二套 Cluster 配置模型；
* 第二套 Order/Position/Account 真值；
* 仅供某个插件使用的内部 Manager；
* 绕过 ExecutionProcessor 的成交路径；
* 绕过 Historical Replay 的正式回测路径；
* Strategy 直接访问 Indicator；
* Factor 下单；
* Broker Gateway 修改 Manager；
* EventBus 驱动关键状态；
* Plugin 导入 Engine 私有实现；
* 市场字符串分支散落在通用组件；
* 通过宽泛 `Any` 和 Mypy Ignore 掩盖边界问题；
* 使用 `float` 作为金融真值；
* 在 Domain 中读取系统时间；
* 在普通 CI 中连接真实券商；
* 复制已有组件形成新旧架构叠加。

发现相似实现时，应先合并、迁移或删除旧路径，再引入新实现。

---

## 25. 完成交付检查表

任务只有满足以下条件才可声明完成：

* [ ] 已阅读现有源码、测试和 ADR；
* [ ] 没有创建平行实现；
* [ ] 依赖方向正确；
* [ ] 公共类型符合 `Only` 命名；
* [ ] 类型注解完整；
* [ ] Ruff 通过；
* [ ] Mypy 通过；
* [ ] Core 测试通过；
* [ ] 受影响插件测试通过；
* [ ] 产品纵切面测试通过；
* [ ] 确定性测试通过；
* [ ] 外部测试状态明确；
* [ ] 没有默认连接真实网络或券商；
* [ ] 配置和版本保持一致；
* [ ] `uv.lock` 已同步；
* [ ] wheel/sdist 可以构建；
* [ ] 干净环境可以安装 wheel；
* [ ] Entry Point 可以发现并加载；
* [ ] `user_data` 输出符合规范；
* [ ] 文档已更新；
* [ ] 已知限制被明确记录；
* [ ] `git diff --check` 通过。

未满足的项目必须明确写入“未完成”或“已知限制”，不得通过模糊措辞宣称完成。
