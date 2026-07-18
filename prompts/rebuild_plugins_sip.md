# OnlyAlpha DataSource/Broker 插件 SPI 重构任务

## 1. 任务目标

基于 OnlyAlpha 当前最新源码，实现稳定、可外部扩展的数据源和券商插件机制，为后续独立仓库：

```text
onlyalpha-plugins
```

提供公共接入边界。

最终必须支持：

```text
OnlyAlpha
    定义公共协议、配置模型、生命周期、Factory Registry 和插件发现

onlyalpha-plugins
    实现真实数据源和券商适配器

onlyalpha-examples
    实现 Strategy、Factor 和使用示例
```

本任务只处理：

```text
DataSource 插件 SPI
Broker 插件 SPI
Plugin API Version
Factory Registry
Entry Point 插件发现
插件配置解析
Capability 校验
插件冲突检测
插件生命周期
测试用外部插件
完整 CLI 验证
```

本任务不处理：

```text
QMT、CTP、IBKR 等真实接入
Strategy/Factor 插件化
examples 仓库迁移
Paper/Live Runtime 完整实现
Cluster 动态热加载
Web 控制接口
```

---

# 2. 开始前检查

修改前必须完整检查当前实际代码，重点包括：

```text
src/onlyalpha/config/
src/onlyalpha/data/
src/onlyalpha/broker/
src/onlyalpha/runtime/
src/onlyalpha/engine/
src/onlyalpha/cluster/
src/onlyalpha/order/
src/onlyalpha/execution/
src/onlyalpha/account/
src/onlyalpha/position/
src/onlyalpha/cli.py
tests/
pyproject.toml
```

重点确认：

```text
当前 DataSource Factory Registry
当前 Broker Factory Registry
Synthetic DataSource 的创建路径
Virtual Broker 的创建路径
RuntimeAssembler 如何解析 DataSource/Broker
配置中的 type、class_path、extensions 等字段
Broker 回报如何进入 ExecutionProcessor
DataSource 数据如何进入 MarketData Pipeline
```

所有修改必须基于当前真实接口。

禁止：

```text
建立第三套平行 Registry
绕过现有 Runtime/Engine 装配链
把真实插件逻辑硬编码进 RuntimeAssembler
为了测试直接手工创建插件对象
```

---

# 3. 架构目标

最终创建链必须统一为：

```text
Cluster Config
→ Plugin Descriptor
→ Factory Registry
→ Factory.parse_config()
→ Capability Validation
→ Factory.create()
→ Engine/Runtime 管理生命周期
```

核心内建组件与外部插件必须走同一创建流程：

```text
DataSourceFactoryRegistry
├── synthetic        核心内建
├── test-external    测试插件
└── xtquant          未来外部插件

BrokerFactoryRegistry
├── virtual          核心内建
├── test-external    测试插件
└── qmt              未来外部插件
```

禁止出现：

```python
if source_type == "synthetic":
    ...
elif source_type == "xtquant":
    ...
```

或：

```python
if broker_type == "virtual":
    ...
elif broker_type == "qmt":
    ...
```

Runtime 和 Engine 只能通过 Registry 获取 Factory。

---

# 4. 公共插件包结构

建议新增：

```text
src/onlyalpha/plugin/
├── __init__.py
├── api.py
├── version.py
├── descriptor.py
├── compatibility.py
├── discovery.py
├── registry.py
├── capabilities.py
├── lifecycle.py
├── errors.py
├── data_source.py
└── broker.py
```

如果当前项目已有相近模块，应优先整合，不要重复建立同义抽象。

所有允许外部插件依赖的接口必须通过稳定公共模块导出。

插件不得依赖：

```text
onlyalpha.engine._*
onlyalpha.runtime._*
OnlyRuntimeAssembler 私有实现
OnlyClusterPipeline 私有实现
Manager 私有字段
内部容器对象
```

---

# 5. Plugin API Version

实现明确的插件 API 版本。

建议：

```python
@dataclass(frozen=True, slots=True, order=True)
class OnlyPluginApiVersion:
    major: int
    minor: int
```

核心至少公开：

```python
ONLYALPHA_PLUGIN_API_VERSION = OnlyPluginApiVersion(
    major=1,
    minor=0,
)
```

兼容规则：

```text
major 不一致：
    不兼容，拒绝加载

插件要求的 minor 高于核心 minor：
    不兼容，拒绝加载

major 相同且插件 minor 不高于核心：
    允许加载
```

必须提供结构化错误：

```text
PLUGIN_API_VERSION_INCOMPATIBLE
PLUGIN_API_VERSION_MISSING
PLUGIN_DESCRIPTOR_INVALID
```

不得只抛出模糊的 `ValueError`。

---

# 6. Plugin Descriptor

定义统一插件描述信息：

```python
@dataclass(frozen=True, slots=True)
class OnlyPluginDescriptor:
    plugin_id: str
    plugin_type: OnlyPluginType
    plugin_version: str
    api_version: OnlyPluginApiVersion
    display_name: str
    provider: str | None
    capabilities: object
```

`OnlyPluginType` 至少支持：

```text
DATA_SOURCE
BROKER
```

插件 ID 必须：

```text
稳定
全局唯一
适合配置文件引用
与 Python 包名解耦
```

例如：

```text
synthetic
virtual
xtquant
qmt
ctp
```

---

# 7. DataSource 插件 SPI

## 7.1 Factory

定义稳定公共接口：

```python
class OnlyDataSourceFactory(Protocol):
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        ...

    def parse_config(
        self,
        extensions: Mapping[str, object],
    ) -> object:
        ...

    def validate_request(
        self,
        request: OnlyDataSourceCreateRequest,
    ) -> Sequence[OnlyPluginValidationIssue]:
        ...

    def create(
        self,
        request: OnlyDataSourceCreateRequest,
    ) -> OnlyDataSource:
        ...
```

`parse_config()` 必须由插件自己处理专用字段。

核心 Parser 只处理：

```text
source_id
plugin
enabled
coverage
extensions
```

核心不得理解：

```text
QMT 路径
Token
用户名
数据库地址
供应商专用周期参数
```

## 7.2 CreateRequest

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyDataSourceCreateRequest:
    source_id: OnlyDataSourceId
    plugin_config: object
    runtime_type: OnlyRuntimeType
    requested_capabilities: OnlyDataSourceCapabilities
    clock: OnlyClock
    event_bus: OnlyEventBus
    instrument_registry: OnlyInstrumentRegistry
    calendar_registry: OnlyTradingCalendarRegistry
    logger: OnlyLogger
```

不得把整个 Engine、RuntimeAssembler 或可随意访问的 ServiceContainer 传给插件。

CreateRequest 只能包含插件运行所需的最小稳定依赖。

---

# 8. DataSource Capability

定义能力模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyDataSourceCapabilities:
    historical_bars: bool = False
    historical_ticks: bool = False
    live_bars: bool = False
    live_ticks: bool = False
    instruments: bool = False
    calendars: bool = False
```

如当前架构需要，可扩展：

```text
order_book
corporate_actions
fundamentals
trading_status
```

但不得在本任务中无边界扩大。

Runtime Planning 或 `dry-run` 必须校验：

```text
BACKTEST 使用历史 bar：
    插件必须支持 historical_bars

LIVE 使用实时 tick：
    插件必须支持 live_ticks

配置要求 reference data：
    插件必须支持 instruments/calendars
```

能力不足时返回：

```text
PLUGIN_CAPABILITY_NOT_SUPPORTED
```

不得运行到数据请求阶段才失败。

---

# 9. DataSource 生命周期

统一生命周期状态：

```text
CREATED
INITIALIZED
CONNECTING
CONNECTED
RUNNING
STOPPING
STOPPED
FAILED
```

数据源公共协议至少支持：

```python
class OnlyDataSource(Protocol):
    @property
    def state(self) -> OnlyPluginLifecycleState:
        ...

    def initialize(self) -> None:
        ...

    def connect(self) -> None:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def close(self) -> None:
        ...

    def health(self) -> OnlyPluginHealth:
        ...
```

历史文件型或 Synthetic 数据源不需要真实网络连接，但仍必须遵守统一生命周期。

可以让：

```text
connect()
```

成为幂等空操作，但不能绕过状态机。

---

# 10. Broker 插件 SPI

## 10.1 Factory

定义：

```python
class OnlyBrokerGatewayFactory(Protocol):
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        ...

    def parse_config(
        self,
        extensions: Mapping[str, object],
    ) -> object:
        ...

    def validate_request(
        self,
        request: OnlyBrokerCreateRequest,
    ) -> Sequence[OnlyPluginValidationIssue]:
        ...

    def create(
        self,
        request: OnlyBrokerCreateRequest,
    ) -> OnlyBrokerGateway:
        ...
```

## 10.2 CreateRequest

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerCreateRequest:
    gateway_id: OnlyBrokerGatewayId
    plugin_config: object
    runtime_type: OnlyRuntimeType
    requested_capabilities: OnlyBrokerCapabilities
    clock: OnlyClock
    event_bus: OnlyEventBus
    broker_inbound_queue: OnlyBrokerInboundQueue
    instrument_registry: OnlyInstrumentRegistry
    logger: OnlyLogger
```

插件不得直接访问：

```text
Strategy
Factor
ClusterPipeline
PositionManager 内部状态
LedgerManager 内部状态
Engine 私有 Registry
```

---

# 11. Broker Capability

至少定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerCapabilities:
    submit_order: bool = False
    cancel_order: bool = False
    replace_order: bool = False
    query_orders: bool = False
    query_trades: bool = False
    query_account: bool = False
    query_positions: bool = False
    live_execution: bool = False
    simulated_execution: bool = False
```

Runtime 或配置要求与 Broker 能力必须在启动前校验。

例如：

```text
BACKTEST：
    至少要求 simulated_execution

LIVE：
    至少要求 submit_order、cancel_order、live_execution

要求账户同步：
    必须支持 query_account

要求仓位同步：
    必须支持 query_positions
```

---

# 12. Broker 公共接口

券商插件至少提供：

```python
class OnlyBrokerGateway(Protocol):
    @property
    def state(self) -> OnlyPluginLifecycleState:
        ...

    def initialize(self) -> None:
        ...

    def connect(self) -> None:
        ...

    def start(self) -> None:
        ...

    def submit_order(
        self,
        command: OnlySubmitOrderCommand,
    ) -> None:
        ...

    def cancel_order(
        self,
        command: OnlyCancelOrderCommand,
    ) -> None:
        ...

    def query_account(self) -> None:
        ...

    def query_positions(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def close(self) -> None:
        ...

    def health(self) -> OnlyPluginHealth:
        ...
```

如果当前项目已有正式 Broker 抽象，应基于现有接口扩展，不要创建重复的 Broker 领域协议。

---

# 13. Broker 事件标准化

外部券商原始对象不得进入核心系统。

插件必须将供应商回报转换为 OnlyAlpha 标准对象或事件。

至少覆盖：

```text
Order Accepted
Order Rejected
Order Updated
Order Canceled
Trade
Account Snapshot
Position Snapshot
Connection Changed
Broker Error
```

优先复用当前已有的：

```text
BrokerInboundQueue
ExecutionProcessor
Order Event
Trade Event
Account Snapshot
Position Snapshot
```

不得为插件单独建立一条旁路执行链。

标准链必须保持：

```text
Broker Plugin
→ BrokerInboundQueue
→ ExecutionProcessor
→ Order/Position/Ledger/Account
```

禁止：

```text
Broker Plugin
→ 直接修改 PositionManager
Broker Plugin
→ 直接修改 Ledger
Broker Plugin
→ 直接调用 Strategy
```

---

# 14. Factory Registry

建立或重构统一 Registry。

至少提供：

```python
class OnlyDataSourceFactoryRegistry:
    def register(
        self,
        factory: OnlyDataSourceFactory,
        *,
        origin: OnlyPluginOrigin,
    ) -> None:
        ...

    def resolve(
        self,
        plugin_id: str,
    ) -> OnlyDataSourceFactory:
        ...

    def descriptors(self) -> tuple[OnlyPluginDescriptor, ...]:
        ...


class OnlyBrokerFactoryRegistry:
    ...
```

注册时必须校验：

```text
plugin_id 是否为空
API Version 是否兼容
plugin_type 是否正确
同名插件是否冲突
Factory 是否满足协议
Descriptor 是否有效
```

同一 plugin_id 重复注册时：

```text
相同 Factory 和相同 Descriptor：
    可以幂等忽略

不同实现或不同 Descriptor：
    拒绝
```

结构化错误：

```text
PLUGIN_ID_CONFLICT
PLUGIN_FACTORY_INVALID
PLUGIN_TYPE_MISMATCH
PLUGIN_NOT_FOUND
```

---

# 15. Entry Point 插件发现

使用 Python `importlib.metadata.entry_points()`。

支持：

```text
onlyalpha.data_sources
onlyalpha.brokers
```

外部插件示例：

```toml
[project.entry-points."onlyalpha.data_sources"]
test-external-data = "onlyalpha_test_plugin.data_source:factory"

[project.entry-points."onlyalpha.brokers"]
test-external-broker = "onlyalpha_test_plugin.broker:factory"
```

发现流程：

```text
注册核心内建 Factory
→ 扫描 Entry Points
→ 加载对象
→ 验证 Descriptor
→ 验证 API Version
→ 注册到对应 Registry
→ 输出发现报告
```

单个插件加载失败时，行为由策略控制：

```text
fail_fast=true：
    立即失败

fail_fast=false：
    记录结构化错误并继续加载其他插件
```

插件发现必须保证确定性：

```text
Entry Point 按 group 和 name 稳定排序
注册顺序稳定
冲突报告稳定
```

---

# 16. 配置模型调整

DataSource 配置统一为：

```yaml
data_sources:
  - source_id: synthetic-main
    plugin: synthetic
    enabled: true
    extensions:
      random_seed: 20260718
```

Broker 配置统一为：

```yaml
brokers:
  - gateway_id: virtual-main
    plugin: virtual
    enabled: true
    extensions:
      matching_model: NEXT_BAR
```

如果当前代码使用：

```text
type
factory
class_path
```

必须制定明确迁移方案。

推荐最终公共字段使用：

```text
plugin
```

允许短期兼容旧 `type`，但必须：

```text
内部统一规范化为 plugin_id
旧字段打印 deprecated 警告
禁止同时指定 plugin 和 type
文档明确删除版本
```

不得永久保留多套同义字段。

---

# 17. 核心内建插件迁移

将以下组件注册为核心内建 Factory：

```text
Synthetic DataSource
Virtual Broker
```

它们必须提供完整：

```text
Plugin Descriptor
API Version
Capabilities
Factory.parse_config()
Factory.validate_request()
Factory.create()
Lifecycle
Health
```

RuntimeAssembler 不得再直接 import 并实例化它们。

目标：

```python
data_factory = data_source_registry.resolve(config.plugin)
data_config = data_factory.parse_config(config.extensions)
data_source = data_factory.create(request)
```

Broker 同理。

---

# 18. RuntimeAssembler 和 Engine 修改

RuntimeAssembler 的职责必须变为：

```text
接收规范化配置
→ 从 Registry 查找 Factory
→ 解析插件扩展配置
→ 校验 Capability
→ 生成 CreateRequest
→ 创建实例
→ 注册到 Infrastructure Registry
```

RuntimeAssembler 不负责：

```text
扫描 Python Entry Points
决定插件兼容规则
解析供应商专用字段
管理插件全局生命周期
```

Entry Point 扫描应在应用组合根完成，例如：

```text
only_default_engine_services()
only_default_application()
```

Engine/Infrastructure Registry 负责：

```text
共享插件实例
引用计数
启动顺序
停止顺序
健康状态
```

---

# 19. 生命周期启动和停止顺序

建议启动顺序：

```text
Factory Registry 初始化
→ 插件发现
→ 配置和 Capability 校验
→ 创建 DataSource/Broker
→ initialize()
→ connect()
→ start()
→ Runtime 启动
→ Cluster 启动
```

停止顺序：

```text
停止 Cluster
→ 停止 Runtime
→ Broker.stop()
→ DataSource.stop()
→ Broker.close()
→ DataSource.close()
```

要求：

```text
stop() 幂等
close() 幂等
部分初始化失败时能够逆序回滚
任一插件失败必须记录 plugin_id 和 resource_id
```

---

# 20. Plugin Health

定义统一健康状态：

```python
@dataclass(frozen=True, slots=True)
class OnlyPluginHealth:
    status: OnlyPluginHealthStatus
    message: str | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    details: Mapping[str, object]
```

状态至少包括：

```text
UNKNOWN
HEALTHY
DEGRADED
UNHEALTHY
STOPPED
```

Engine Snapshot 应能够展示：

```text
DataSource plugin_id
Broker plugin_id
resource_id
lifecycle state
health
capabilities
reference count
```

本任务不要求自动重连，但接口必须能支持后续扩展。

---

# 21. 外部测试插件

创建真正独立的测试插件包，不能只是主包内部普通模块。

推荐：

```text
tests/fixtures/external_plugins/onlyalpha_test_plugin/
├── pyproject.toml
└── src/
    └── onlyalpha_test_plugin/
        ├── __init__.py
        ├── data_source.py
        └── broker.py
```

该包必须通过 Entry Points 注册：

```text
test-external-data
test-external-broker
```

测试插件实现：

```text
可重复产生固定历史 Bar
提供固定 seed
模拟订单接受和成交
通过 BrokerInboundQueue 发送标准事件
提供健康状态
完整执行生命周期
```

不得直接调用测试代码注册 Factory 来绕过 Entry Point。

测试必须验证安装后的插件发现路径。

可以在测试环境中构建并安装本地 wheel 或使用受控的 metadata 测试方式，但最终必须验证真实 `importlib.metadata.entry_points()` 发现行为。

---

# 22. 完整回测验收

创建测试配置：

```yaml
data_sources:
  - source_id: external-test-data
    plugin: test-external-data
    extensions:
      random_seed: 20260718

brokers:
  - gateway_id: external-test-broker
    plugin: test-external-broker
    extensions:
      fill_policy: NEXT_BAR
```

必须通过正式 CLI：

```bash
uv run onlyalpha run \
  --config <external-plugin-backtest.yaml> \
  --user-data ./user_data
```

完整链路必须是：

```text
CLI
→ OnlyEngine
→ Plugin Discovery
→ Factory Registry
→ DataSource Factory
→ Broker Factory
→ Capability Validation
→ RuntimeSession
→ ClusterSession
→ External Test DataSource
→ MarketData Pipeline
→ Indicator
→ Factor
→ Strategy
→ Order
→ External Test Broker
→ BrokerInboundQueue
→ ExecutionProcessor
→ Position
→ Ledger
→ Account
→ user_data
```

---

# 23. 核心内建回测回归

以下核心链路必须继续通过：

```text
Synthetic DataSource
Virtual Broker
```

命令：

```bash
uv run onlyalpha run \
  --config <synthetic-virtual-config.yaml> \
  --user-data ./user_data
```

验证：

```text
内建组件和外部插件使用同一 Registry 接口
RuntimeAssembler 不包含内建组件特殊分支
原有回测结果保持确定性
```

---

# 24. dry-run 验收

`--dry-run` 必须完成：

```text
扫描插件
加载 Descriptor
校验 API Version
解析 extensions
校验 Capability
检查插件名称冲突
生成资源创建计划
验证 Runtime 所需能力
```

不得：

```text
连接真实服务
启动数据回放
提交订单
创建正式运行结果
```

dry-run 输出至少包括：

```text
发现的插件
插件来源
插件版本
API 版本
Capabilities
DataSource/Broker 配置绑定
校验结果
```

---

# 25. 测试要求

至少新增：

```text
tests/plugin/
├── test_plugin_api_version.py
├── test_plugin_descriptor.py
├── test_plugin_compatibility.py
├── test_entry_point_discovery.py
├── test_plugin_id_conflict.py
├── test_plugin_discovery_fail_fast.py
├── test_plugin_discovery_non_fail_fast.py
├── test_data_source_factory_registry.py
├── test_broker_factory_registry.py
├── test_data_source_capability_validation.py
├── test_broker_capability_validation.py
└── test_plugin_lifecycle.py

tests/integration/
├── test_builtin_synthetic_registry_backtest.py
├── test_builtin_virtual_registry_backtest.py
├── test_external_plugin_cli_backtest.py
├── test_external_plugin_execution_pipeline.py
├── test_external_plugin_dry_run.py
├── test_plugin_shutdown_order.py
└── test_plugin_failure_rollback.py
```

必须覆盖：

```text
兼容 API 版本
不兼容 major
不兼容 minor
缺失 Descriptor
错误 plugin_type
重复 plugin_id
未知 plugin_id
缺失 Capability
extensions 解析失败
create() 失败回滚
connect() 失败回滚
start() 失败回滚
stop()/close() 幂等
外部 Broker 回报进入 ExecutionProcessor
```

运行：

```bash
uv run pytest
```

不得删除、跳过或放宽已有测试。

---

# 26. 文档

新增或更新：

```text
docs/plugin_system.md
docs/plugin_api_version.md
docs/data_source_plugin.md
docs/broker_plugin.md
docs/plugin_lifecycle.md
docs/plugin_entry_points.md
docs/plugin_configuration.md
docs/plugin_testing.md
```

文档必须明确：

```text
OnlyAlpha 核心与 onlyalpha-plugins 的依赖方向
允许插件使用的公共 API
禁止依赖的内部模块
Entry Point group
插件配置格式
API Version 兼容规则
Capability 校验
生命周期
错误处理
测试方法
```

---

# 27. ADR

创建：

```text
docs/adr/0020-data-source-and-broker-plugin-spi.md
```

至少记录：

## 背景

当前 DataSource 和 Broker 的 Factory、配置解析和实例创建边界不足以支持独立外部插件仓库，核心内建组件与未来真实连接器可能形成不同创建路径。

## 决策

```text
定义稳定插件 SPI
使用 Plugin API Version
使用 Entry Points 发现插件
核心与外部插件统一使用 Factory Registry
核心只解析公共字段
插件负责解析 extensions
Runtime 在启动前校验 Capability
Engine 管理插件生命周期
Broker 回报统一进入 BrokerInboundQueue 和 ExecutionProcessor
```

## 拒绝方案

```text
在 RuntimeAssembler 中硬编码 QMT/CTP
配置使用任意 class_path 创建 Broker
外部插件直接访问 Engine 私有状态
券商插件直接修改仓位和账户
数据源和券商分别使用完全不同的发现机制
核心依赖 onlyalpha-plugins
```

---

# 28. 实现顺序

严格按以下顺序执行：

1. 检查当前 DataSource/Broker 创建链；
2. 整理现有 Factory 和 Registry；
3. 定义 Plugin API Version；
4. 定义 Plugin Descriptor；
5. 定义统一错误类型；
6. 定义 Capability 模型；
7. 定义插件生命周期和 Health；
8. 定义 DataSource Factory SPI；
9. 定义 Broker Factory SPI；
10. 定义 CreateRequest；
11. 实现 DataSource Factory Registry；
12. 实现 Broker Factory Registry；
13. 实现 Entry Point Discovery；
14. 实现版本兼容校验；
15. 实现冲突检测；
16. 调整配置模型使用 `plugin`；
17. 迁移 Synthetic DataSource；
18. 迁移 Virtual Broker；
19. 修改 RuntimeAssembler；
20. 接入 Infrastructure Registry；
21. 实现启动和停止顺序；
22. 实现失败回滚；
23. 创建外部测试插件包；
24. 完成 Entry Point 发现测试；
25. 完成外部插件完整回测；
26. 完成内建回测回归；
27. 完成 dry-run；
28. 运行全部测试；
29. 更新文档；
30. 创建 ADR；
31. 生成最终报告。

---

# 29. 一票否决项

出现以下任一情况，任务判定为失败：

```text
RuntimeAssembler 硬编码外部插件类型
核心依赖 onlyalpha-plugins
插件依赖 Engine 或 Runtime 私有实现
外部插件通过任意 class_path 绕过 Registry
核心 Parser 解析 QMT/CTP 专用配置
Synthetic 和 Virtual 不走统一 Factory Registry
缺少 Plugin API Version
缺少 Capability 校验
缺少插件名称冲突检测
Broker 插件直接修改 Position/Ledger/Account
Broker 回报绕过 ExecutionProcessor
测试直接手工注册外部插件，未验证 Entry Point
外部插件回测不能通过正式 CLI 运行
插件生命周期失败时无法回滚
旧测试被删除或跳过
```

---

# 30. 最终验收标准

任务完成时必须满足：

```text
OnlyAlpha 提供稳定 DataSource/Broker 插件 SPI
外部插件只依赖公共接口
Entry Point 可以发现已安装插件
Plugin API Version 可以拒绝不兼容插件
Factory Registry 可以检测冲突
配置通过 plugin_id 引用插件
extensions 由插件 Factory 解析
Runtime 启动前完成 Capability 校验
Synthetic DataSource 通过统一 Registry 创建
Virtual Broker 通过统一 Registry 创建
外部测试 DataSource/Broker 通过 Entry Point 创建
外部 Broker 回报进入 ExecutionProcessor
完整外部插件回测通过
完整核心内建回测通过
dry-run 通过
全部测试通过
```

---

# 31. 最终报告

生成：

```text
docs/reports/plugin_spi_refactor_report.md
```

至少包含：

```text
修改前创建链
修改后创建链
公共插件 API
Plugin API Version
Plugin Descriptor
DataSource SPI
Broker SPI
Capabilities
Lifecycle
Health
Factory Registry
Entry Point Discovery
配置模型变化
Synthetic 迁移结果
Virtual Broker 迁移结果
外部测试插件
CLI 回测结果
dry-run 结果
失败回滚测试
全部测试结果
已知限制
后续 onlyalpha-plugins 仓库实施建议
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

不要只提交接口和文档。必须完成核心代码修改、外部测试插件、正式 CLI 回测和全部测试验证。
