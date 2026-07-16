# OnlyAlpha 通用运行配置、动态组件装配与多 Runtime 架构重构任务

## 1. 任务目标

当前配置和装配实现仍然以 Backtest 为中心：

```text
OnlyBacktestConfig
OnlyBacktestRuntimeAssembler
examples/backtest_macd/config.yaml
```

这会导致：

* 一个配置文件只能启动回测；
* 配置模型与 `OnlyBacktestRuntime` 强绑定；
* Paper、Live、Research 需要重复实现配置体系；
* Runtime 装配器需要识别具体子类配置；
* 上层代码容易调用 Backtest、Paper、Live 的子类专有接口；
* 动态组件加载能力无法在不同 Runtime 间复用。

本任务需要将配置、组件工厂、Runtime 装配和运行入口重构为通用体系，使同一种配置文档能够通过：

```text
runtime.type
```

选择不同的 Runtime。

目标支持：

```text
BACKTEST
PAPER
LIVE
SHADOW
RESEARCH
```

第一阶段必须完整支持：

```text
BACKTEST
```

并为：

```text
PAPER
LIVE
SHADOW
RESEARCH
```

建立正式抽象边界、配置模型、Factory 注册机制和明确的 Unsupported 结果。

不得让通用配置系统依赖任何具体 Runtime 子类。

---

# 2. 最重要的架构原则

必须遵守以下规则：

```text
配置文档属于 OnlyAlpha Engine，不属于 Backtest Runtime。

通用配置解析器不得依赖 Backtest、Paper、Live 子类。

Runtime 类型通过 runtime.type 动态选择。

Runtime 具体实现通过 Factory 或 Registry 创建。

上层只能调用 OnlyRuntime 抽象接口。

不得通过 isinstance 判断后调用子类专有运行接口。

不得让通用 Assembler 调用 OnlyBacktestRuntime 的私有或专有方法。

不同 Runtime 使用统一 Lifecycle、Run、Stop、Snapshot 和 Result 接口。

具体 Runtime 的实现文件放在对应父组件目录的子目录中。

具体配置子类必须通过抽象配置 Port 被使用。

Factory 返回抽象类型，而不是具体子类类型。

具体组件参数放在 extensions 中，由对应具体 Factory 或 Config Parser 解析。
```

---

# 3. 通用配置文件

配置文件不再命名为：

```text
backtest config
```

而是：

```text
OnlyRuntimeDocument
OnlyEngineRunConfig
OnlyRunConfig
```

建议顶层结构：

```yaml
schema_version: "1.0"

engine:
  engine_id: onlyalpha-demo

runtime:
  runtime_id: macd-demo
  type: BACKTEST

  start_time: "2026-01-05T01:30:00Z"
  end_time: "2026-01-08T07:01:00Z"
  base_currency: CNY

  extensions:
    replay:
      stop_on_data_error: true

reference_data:
  calendars: []
  instruments: []

universes: []

data_sources: []

accounts: []

brokers: []

strategies: []

output:
  directory: output/macd-demo
  formats:
    - json
    - csv
    - markdown
  overwrite: true
```

同一结构可用于 Paper：

```yaml
runtime:
  runtime_id: macd-paper
  type: PAPER

  start_time: null
  end_time: null
  base_currency: CNY

  extensions:
    lifecycle:
      graceful_stop_timeout_seconds: 30
```

也可用于 Live：

```yaml
runtime:
  runtime_id: macd-live
  type: LIVE
  base_currency: CNY

  extensions:
    recovery:
      required: true
    reconciliation:
      block_until_completed: true
```

通用 Parser 不应根据 Runtime 类型读取具体扩展字段。

---

# 4. 配置目录重新设计

当前：

```text
src/onlyalpha/runtime/backtest/config.py
```

不能继续作为所有运行配置的主入口。

建议目录改为：

```text
src/onlyalpha/config/
├── __init__.py
├── document.py
├── loader.py
├── normalizer.py
├── validation.py
├── fingerprint.py
├── errors.py
├── json_types.py
├── runtime.py
├── reference_data.py
├── universe.py
├── data_source.py
├── broker.py
├── account.py
├── strategy.py
├── output.py
├── registry.py
└── factory.py
```

通用类型放入：

```text
src/onlyalpha/config/
```

例如：

```text
OnlyRunConfig
OnlyRuntimeConfig
OnlyReferenceDataConfig
OnlyUniverseConfig
OnlyDataSourceConfig
OnlyBrokerConfig
OnlyAccountConfig
OnlyStrategyImportConfig
OnlyOutputConfig
```

具体 Runtime 的扩展配置放入对应 Runtime 子目录：

```text
src/onlyalpha/runtime/backtest/config.py
src/onlyalpha/runtime/paper/config.py
src/onlyalpha/runtime/live/config.py
src/onlyalpha/runtime/shadow/config.py
src/onlyalpha/runtime/research/config.py
```

但这些文件只定义对应 Runtime 的扩展配置解析，不负责解析完整配置文档。

---

# 5. Runtime 目录结构

遵循以下目录规则：

> 子类实现通常放在父类组件目录下的独立子目录中。

推荐：

```text
src/onlyalpha/runtime/
├── __init__.py
├── base.py
├── config.py
├── enums.py
├── lifecycle.py
├── result.py
├── snapshot.py
├── health.py
├── factory.py
├── registry.py
├── assembler.py
├── errors.py
│
├── backtest/
│   ├── __init__.py
│   ├── runtime.py
│   ├── config.py
│   ├── assembler.py
│   ├── lifecycle.py
│   ├── loop.py
│   ├── result.py
│   ├── run_plan.py
│   └── factory.py
│
├── paper/
│   ├── __init__.py
│   ├── runtime.py
│   ├── config.py
│   ├── assembler.py
│   ├── lifecycle.py
│   ├── loop.py
│   ├── result.py
│   └── factory.py
│
├── live/
│   ├── __init__.py
│   ├── runtime.py
│   ├── config.py
│   ├── assembler.py
│   ├── lifecycle.py
│   ├── loop.py
│   ├── result.py
│   └── factory.py
│
├── shadow/
│   └── ...
│
└── research/
    └── ...
```

禁止继续将所有 Runtime 实现堆积在：

```text
src/onlyalpha/runtime/runtime.py
```

通用父类和共享协议放在：

```text
runtime/base.py
runtime/lifecycle.py
runtime/result.py
```

具体行为放在对应子目录。

---

# 6. 其他组件同样遵循子目录规则

该规则不仅适用于 Runtime。

例如 Broker：

```text
src/onlyalpha/broker/
├── base.py
├── ports/
├── factory.py
├── registry.py
├── virtual/
│   ├── gateway.py
│   ├── config.py
│   ├── account_store.py
│   ├── order_store.py
│   ├── matching.py
│   └── factory.py
├── qmt/
├── xtp/
└── ibkr/
```

DataSource：

```text
src/onlyalpha/data/
├── base.py
├── ports/
├── factory.py
├── registry.py
├── synthetic/
│   ├── source.py
│   ├── config.py
│   ├── price_model.py
│   ├── volume_model.py
│   └── factory.py
├── parquet/
├── csv/
└── remote/
```

Strategy：

```text
src/onlyalpha/strategy/
├── base.py
├── config.py
├── factory.py
├── registry.py
└── examples/
    └── macd/
        ├── strategy.py
        ├── config.py
        └── result.py
```

Indicator：

```text
src/onlyalpha/indicator/
├── base.py
├── registry.py
├── context.py
├── macd/
│   ├── indicator.py
│   ├── config.py
│   └── snapshot.py
├── rsi/
└── atr/
```

禁止：

```text
indicator/macd.py
indicator/rsi.py
indicator/atr.py
```

在具体实现开始增加后继续平铺扩张。

---

# 7. 通用 Runtime 抽象接口

定义或重构：

```text
OnlyRuntime
```

建议抽象接口：

```python
class OnlyRuntime(Protocol):
    @property
    def runtime_id(self) -> OnlyRuntimeId:
        ...

    @property
    def runtime_type(self) -> OnlyRuntimeType:
        ...

    @property
    def status(self) -> OnlyRuntimeStatus:
        ...

    def initialize(self) -> OnlyRuntimeOperationResult:
        ...

    def start(self) -> OnlyRuntimeOperationResult:
        ...

    def run(self) -> OnlyRuntimeResult:
        ...

    def pause(self) -> OnlyRuntimeOperationResult:
        ...

    def resume(self) -> OnlyRuntimeOperationResult:
        ...

    def stop(self) -> OnlyRuntimeOperationResult:
        ...

    def close(self) -> OnlyRuntimeOperationResult:
        ...

    def snapshot(self) -> OnlyRuntimeSnapshot:
        ...
```

上层程序只能使用这些接口。

例如：

```python
config = OnlyRunConfig.load(path)
runtime = OnlyRuntimeFactory.create(config)
result = runtime.run()
```

禁止：

```python
if isinstance(runtime, OnlyBacktestRuntime):
    runtime.replay_historical_bars(...)
```

禁止：

```python
runtime._only_bind_product_runner(...)
```

禁止调用子类私有方法完成产品流程。

---

# 8. 统一 Runtime Result

定义：

```text
OnlyRuntimeResult
```

通用字段：

```text
runtime_id
runtime_type
status
started_at
completed_at
final_snapshot
quality_flags
failure
component_results
strategy_results
determinism_fingerprint
```

具体 Runtime 可以提供扩展结果：

```text
OnlyBacktestRuntimeResult
OnlyPaperRuntimeResult
OnlyLiveRuntimeResult
OnlyResearchRuntimeResult
```

但上层应通过统一接口访问：

```python
result.runtime_type
result.common
result.extensions
```

或：

```python
result.extension("backtest")
```

不得要求调用者直接依赖：

```python
OnlyBacktestResult.generated_bar_count
```

才能完成通用运行流程。

可以保留具体结果类型供可信内部代码使用，但通用入口返回类型必须是：

```text
OnlyRuntimeResult
```

---

# 9. 配置抽象接口

不同 Runtime 的配置不能由通用代码直接访问子类字段。

定义：

```python
class OnlyRuntimeExtensionConfig(Protocol):
    @property
    def runtime_type(self) -> OnlyRuntimeType:
        ...

    def validate(
        self,
        context: OnlyConfigValidationContext,
    ) -> OnlyConfigValidationResult:
        ...

    def to_json(self) -> Mapping[str, OnlyJsonValue]:
        ...
```

通用 Runtime 配置：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeConfig:
    runtime_id: OnlyRuntimeId
    runtime_type: OnlyRuntimeType
    base_currency: OnlyCurrency
    start_time: datetime | None
    end_time: datetime | None
    extensions: OnlyJsonMapping
```

具体 Runtime 配置 Factory：

```text
BACKTEST
→ OnlyBacktestRuntimeConfigFactory

PAPER
→ OnlyPaperRuntimeConfigFactory

LIVE
→ OnlyLiveRuntimeConfigFactory
```

通用 Parser 只生成：

```text
OnlyRuntimeConfig
```

然后：

```text
OnlyRuntimeExtensionConfigFactory
```

根据 `runtime.type` 创建扩展配置。

---

# 10. 禁止调用子类配置接口

错误示例：

```python
if config.runtime.runtime_type == "BACKTEST":
    source = config.runtime.backtest_source
    replay = config.runtime.replay_config
```

正确方式：

```python
runtime_factory = runtime_registry.require(
    config.runtime.runtime_type
)

runtime = runtime_factory.create(
    OnlyRuntimeBuildRequest(
        common_config=config,
        runtime_extension=config.runtime.extensions,
        component_registry=component_registry,
    )
)
```

通用代码不应知道：

```text
Backtest replay
Paper live clock
Live recovery
Research dataset
```

这些由具体 Runtime Factory 解析并装配。

---

# 11. Runtime Factory 与 Registry

新增：

```text
OnlyRuntimeFactory
OnlyRuntimeFactoryRegistry
OnlyRuntimeBuildRequest
OnlyRuntimeBuildResult
```

建议协议：

```python
class OnlyRuntimeFactory(Protocol):
    @property
    def runtime_type(self) -> OnlyRuntimeType:
        ...

    def create(
        self,
        request: OnlyRuntimeBuildRequest,
    ) -> OnlyRuntime:
        ...
```

注册：

```text
BACKTEST
→ OnlyBacktestRuntimeFactory

PAPER
→ OnlyPaperRuntimeFactory

LIVE
→ OnlyLiveRuntimeFactory
```

统一调用：

```python
runtime_factory = registry.require(
    config.runtime.runtime_type
)

runtime = runtime_factory.create(
    OnlyRuntimeBuildRequest(
        config=config,
        component_registry=components,
    )
)
```

返回类型必须是：

```text
OnlyRuntime
```

不是：

```text
OnlyBacktestRuntime
```

---

# 12. 通用 Engine 运行入口

新增或重构：

```text
OnlyEngineRunService
```

推荐入口：

```python
config = OnlyRunConfig.load(config_path)

run_service = OnlyEngineRunService(
    runtime_factory_registry=runtime_registry,
    component_factory_registry=component_registry,
)

result = run_service.run(config)
```

`run_service` 不得判断具体 Runtime 类型后调用子类方法。

只允许：

```python
runtime.initialize()
runtime.run()
runtime.close()
```

---

# 13. 动态组件配置

配置中的以下组件都必须支持动态 Factory 或 Registry：

```text
Runtime
DataSource
BrokerGateway
MatchingEngine
CommissionModel
SlippageModel
Strategy
RiskProfile
Indicator（由策略主持注册）
ResultExporter
```

统一配置形态建议：

```yaml
type: SYNTHETIC
factory_id: synthetic
extensions:
  ...
```

或者可信本地模式：

```yaml
factory_path: onlyalpha.data.synthetic.factory:OnlySyntheticDataSourceFactory
```

Web/生产环境优先使用：

```text
factory_id
```

禁止让 Web 任意提交 Python import path。

---

# 14. Component Factory 抽象

定义：

```python
class OnlyComponentFactory(Protocol):
    @property
    def component_type(self) -> str:
        ...

    def create(
        self,
        request: OnlyComponentBuildRequest,
    ) -> object:
        ...
```

更推荐针对不同组件定义强类型 Port：

```text
OnlyDataSourceFactory
OnlyBrokerGatewayFactory
OnlyStrategyFactory
OnlyCommissionModelFactory
OnlyMatchingEngineFactory
OnlyRuntimeFactory
```

不要用一个返回任意 `object` 的万能 Factory 替代所有类型安全接口。

---

# 15. DataSource 抽象调用

通用 Runtime 装配不得调用：

```python
OnlySyntheticHistoricalDataSourceConfig.from_mapping(...)
```

正确方式：

```python
source_factory = data_source_registry.require(
    source_config.source_type
)

source = source_factory.create(
    OnlyDataSourceBuildRequest(
        common_config=source_config,
        reference_data=reference_data,
        universes=universes,
        runtime_context=runtime_context,
    )
)
```

返回：

```text
OnlyHistoricalDataSource
```

或：

```text
OnlyMarketDataGateway
```

具体实现由 Runtime 类型和 Source Capability 决定。

通用装配器不得调用 Synthetic 子类专有接口。

---

# 16. Broker 抽象调用

通用装配不得直接：

```python
OnlyVirtualBrokerConfig(...)
OnlyVirtualBrokerGateway(...)
```

正确方式：

```python
broker_factory = broker_registry.require(
    broker_config.gateway_type
)

broker = broker_factory.create(
    OnlyBrokerBuildRequest(...)
)
```

返回：

```text
OnlyBrokerGateway
```

Runtime 和 ExecutionService 只使用 Broker Port。

---

# 17. Strategy 抽象调用

策略动态加载保持：

```text
strategy_path
config_path
```

但建议配置同时支持：

```yaml
strategy_type: macd-example
strategy_version: "1.0"
```

可信本地开发允许路径加载。

Web 和生产使用 Registry ID。

Strategy Factory 返回：

```text
OnlyCluster
```

上层不得调用：

```text
OnlyMacdExampleCluster.signals
OnlyMacdExampleCluster.macd_trace
```

策略专属结果通过统一接口：

```text
OnlyStrategyResultProvider
```

获取。

---

# 18. Indicator 生命周期

指标仍然由策略在：

```text
on_initialize()
```

中创建和注册。

通用 Runtime 不应根据配置实例化具体 Indicator。

`strategies.extensions.indicators` 属于策略私有配置。

Runtime 只提供：

```text
OnlyIndicatorContextView
OnlyIndicatorRegistry
OnlyIndicatorPipeline
```

禁止 Runtime Parser 读取：

```text
fast_period
slow_period
signal_period
rsi_period
atr_period
```

---

# 19. Assembly 分层

不再使用单个巨大：

```text
OnlyBacktestRuntimeAssembler
```

承担全部配置解析和组件构建。

建议分为：

```text
OnlyEngineRunAssembler
    解析通用组件关系

OnlyRuntimeFactoryRegistry
    选择 Runtime

OnlyBacktestRuntimeFactory
    组装 Backtest 专属驱动

OnlyDataSourceFactoryRegistry
OnlyBrokerFactoryRegistry
OnlyStrategyFactory
```

关系：

```text
OnlyRunConfig
→ OnlyEngineRunAssembler
→ OnlyRuntimeFactoryRegistry
→ OnlyBacktestRuntimeFactory
→ OnlyRuntime
```

`OnlyBacktestRuntimeFactory` 可以存在于：

```text
src/onlyalpha/runtime/backtest/factory.py
```

它可以了解 Backtest 的历史回放语义，但仍只能通过：

```text
OnlyHistoricalDataSource
OnlyHistoricalReplayService
OnlyBrokerGateway
OnlyCluster
```

等抽象接口组装。

---

# 20. Backtest 子类专有行为封装

Backtest 专有的：

```text
Historical Replay
Virtual Clock
Deterministic Fingerprint
Backtest Performance Result
```

应封装在：

```text
src/onlyalpha/runtime/backtest/
```

例如：

```text
OnlyBacktestRunPlan
OnlyBacktestRuntimeLoop
OnlyBacktestRuntimeResultBuilder
```

但外部只调用：

```python
runtime.run()
```

不应调用：

```python
runtime.replay_historical_bars(...)
runtime.drain_broker_inbound()
```

这些应成为 Backtest Runtime 内部流程。

---

# 21. Paper 与 Live 的未来扩展

本任务不要求完整实现 Paper 和 Live，但必须完成：

```text
OnlyRuntimeType.PAPER
OnlyRuntimeType.LIVE
OnlyPaperRuntimeFactory 占位
OnlyLiveRuntimeFactory 占位
```

未实现时返回明确：

```text
UNSUPPORTED_RUNTIME_TYPE
RUNTIME_FACTORY_NOT_AVAILABLE
```

不得抛普通 `NotImplementedError` 后继续运行。

不能让通用配置 Parser 拒绝 `PAPER` 或 `LIVE` 结构，只能由 Registry 判断当前是否有可用 Factory。

---

# 22. Result 输出目录重构

当前结果目录不应固定为：

```text
examples/backtest_macd/output
```

建议采用：

```text
output/
└── <engine_id>/
    └── <runtime_id>/
        └── <run_id>/
            ├── config/
            │   ├── normalized.json
            │   ├── source.yaml
            │   └── fingerprint.txt
            ├── runtime/
            │   ├── summary.json
            │   ├── snapshot.json
            │   └── health.json
            ├── market_data/
            │   ├── summary.json
            │   └── quality.json
            ├── execution/
            │   ├── orders.json
            │   ├── trades.json
            │   └── audit.json
            ├── portfolio/
            │   ├── positions.json
            │   ├── allocations.json
            │   ├── ledgers.json
            │   └── accounts.json
            ├── strategies/
            │   └── <cluster_id>/
            │       ├── summary.json
            │       └── extensions.json
            ├── reports/
            │   └── run_report.md
            └── logs/
```

`run_id` 必须稳定生成或明确记录。

回测确定性比较不应因输出路径不同而改变业务 Fingerprint。

---

# 23. Output Exporter 抽象

定义：

```text
OnlyRuntimeResultExporter
OnlyRuntimeOutputLayout
OnlyRuntimeOutputManifest
```

配置：

```yaml
output:
  root_directory: output
  layout: STANDARD
  formats:
    - JSON
    - CSV
    - MARKDOWN
  overwrite: false
```

通用 Runtime 不直接写文件。

正确流程：

```text
OnlyRuntimeResult
→ OnlyRuntimeResultExporter
→ Output Layout
```

Backtest Runtime 不应知道最终目录结构。

---

# 24. 需要重命名的配置类型

原：

```text
OnlyBacktestConfig
```

改为：

```text
OnlyRunConfig
```

或：

```text
OnlyEngineRunConfig
```

原：

```text
OnlyBacktestRuntimeConfig
```

需要拆分为：

```text
OnlyRuntimeConfig
OnlyBacktestRuntimeExtensionConfig
```

避免同名类型同时出现在：

```text
runtime/backtest/config.py
runtime/backtest/runtime.py
```

---

# 25. 示例配置目录

建议：

```text
examples/
├── configs/
│   ├── backtest/
│   │   └── macd/
│   │       ├── run.yaml
│   │       ├── run.json
│   │       └── synthetic_market.yaml
│   ├── paper/
│   ├── live/
│   └── research/
│
├── strategies/
│   └── macd/
│       ├── strategy.py
│       ├── config.py
│       └── README.md
│
└── run.py
```

统一运行命令：

```bash
onlyalpha run --config examples/configs/backtest/macd/run.json
```

而不是：

```bash
python examples/backtest_macd/run.py
```

可暂时保留兼容入口，但它应只调用统一 CLI。

---

# 26. 测试要求

新增：

```text
tests/config/
tests/runtime/factory/
tests/runtime/backtest/
tests/output/
```

至少验证：

```text
同一 Config Parser 可解析 BACKTEST/PAPER/LIVE

Runtime Factory 根据 runtime.type 选择实现

通用调用者只持有 OnlyRuntime

没有代码通过 isinstance 调用子类接口

Backtest 产品运行只调用 runtime.run()

通用 Config 不读取 Backtest 专有 extensions

DataSource 通过抽象 Factory 创建

Broker 通过抽象 Factory 创建

Strategy 通过抽象 Factory 创建

Factory 返回父接口类型

未注册 Runtime 类型返回结构化错误

子类文件位于父组件目录的对应子目录

输出目录符合标准布局

Strategy 专用结果进入 strategies/<cluster_id>

YAML 与 JSON 规范化结果一致
```

---

# 27. 静态架构检查

增加静态检查，禁止通用层导入具体实现。

例如：

```text
src/onlyalpha/config/
```

不得导入：

```text
runtime.backtest
runtime.paper
runtime.live
data.synthetic
broker.virtual
strategy.examples
indicator.macd
```

```text
src/onlyalpha/runtime/assembler.py
```

不得导入：

```text
OnlyBacktestRuntime
OnlyPaperRuntime
OnlyLiveRuntime
OnlyVirtualBrokerGateway
OnlySyntheticHistoricalDataSource
OnlyMacdExampleCluster
```

它只能使用 Registry 和抽象 Port。

---

# 28. 实现顺序

严格按以下顺序：

1. 扫描现有配置、Runtime 和装配实现；
2. 创建架构差距分析；
3. 设计通用 OnlyRunConfig；
4. 将通用配置移到 `src/onlyalpha/config/`；
5. 拆分 Runtime 通用配置与 Backtest 扩展配置；
6. 重构 Runtime 目录；
7. 定义 OnlyRuntime 抽象接口；
8. 定义统一 Lifecycle 和 Result；
9. 定义 Runtime Factory 和 Registry；
10. 将 Backtest 实现迁移到 `runtime/backtest/`；
11. 将 Backtest RunPlan 封装到 Runtime 内；
12. 删除外部调用 Backtest 子类接口；
13. 增加 DataSource Factory Registry；
14. 增加 Broker Factory Registry；
15. 增加 Strategy Factory；
16. 迁移 Synthetic 实现到 `data/synthetic/`；
17. 迁移 Virtual Broker 到 `broker/virtual/`；
18. 迁移 MACD Indicator 到 `indicator/macd/`；
19. 重构输出目录和 Exporter；
20. 更新 YAML 和 JSON 示例；
21. 更新统一 CLI；
22. 增加 Paper/Live Factory 占位；
23. 增加测试和静态检查；
24. 运行完整 Vertical Slice；
25. 运行确定性重放；
26. 更新文档和 ADR；
27. 生成最终报告。

---

# 29. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

```text
OnlyRunConfig 仍然只支持 Backtest

配置主入口仍放在 runtime/backtest/config.py

通用配置 Parser 导入 Backtest 子类

通用 Assembler 直接实例化 OnlyBacktestRuntime

通用 Assembler 直接实例化 Synthetic DataSource

通用 Assembler 直接实例化 Virtual Broker

调用者通过 isinstance 调用 Runtime 子类接口

产品流程调用 runtime._private_method

Backtest 外部代码调用 replay_historical_bars

Factory 返回具体子类作为上层依赖类型

通用代码读取 Backtest 专有配置字段

通用代码读取 Strategy extensions

子类实现继续堆积在父目录单文件中

Backtest、Paper、Live 各自维护一套完整配置模型

输出目录仍由 Backtest Runtime 硬编码

Runtime 直接写 Result 文件

YAML 与 JSON 语义不一致

历史 Vertical Slice 失败

确定性重放不一致
```

---

# 30. 最终报告

生成：

```text
docs/reports/runtime_configuration_and_factory_refactor_report.md
```

至少包含：

```text
原配置架构
新通用配置架构
Runtime 类型支持
通用 OnlyRuntime 接口
Runtime Factory Registry
Backtest Runtime 子目录
Paper/Live 扩展点
DataSource Factory
Broker Factory
Strategy Factory
抽象配置接口
子类接口隔离
目录重构
输出目录重构
统一 Result
统一 CLI
JSON/YAML 一致性
新增测试
静态架构检查
历史 Vertical Slice
确定性重放
已知限制
一票否决项
最终结论
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

---

# 31. Codex 启动指令

```text
严格执行通用运行配置、动态组件装配与多 Runtime 架构重构。

配置文件不得再属于 Backtest。将主配置模型迁移到 src/onlyalpha/config/，建立通用 OnlyRunConfig，通过 runtime.type 支持 BACKTEST、PAPER、LIVE、SHADOW 和 RESEARCH。第一阶段完整实现 BACKTEST，并为其他 Runtime 建立正式 Factory 注册和结构化 Unsupported 结果。

重构 Runtime 目录：通用父接口放在 src/onlyalpha/runtime/，Backtest 子类相关实现全部放入 src/onlyalpha/runtime/backtest/，Paper、Live、Shadow、Research 使用各自子目录。其他组件同样遵循父组件目录下建立具体实现子目录的规则，例如 data/synthetic、broker/virtual、indicator/macd。

定义统一 OnlyRuntime 抽象接口。上层只能调用 initialize、run、pause、resume、stop、close、snapshot 等父接口。禁止通过 isinstance 判断 Runtime 子类并调用 replay_historical_bars、drain_broker_inbound 或任何私有方法。Backtest 的 Replay 和 RunPlan 必须封装在 OnlyBacktestRuntime.run() 内部。

建立 OnlyRuntimeFactoryRegistry、OnlyDataSourceFactoryRegistry、OnlyBrokerFactoryRegistry 和 OnlyStrategyFactory。通用 Assembler 只能通过抽象 Factory 创建组件，不得直接实例化 OnlyBacktestRuntime、OnlySyntheticHistoricalDataSource、OnlyVirtualBrokerGateway 或具体策略。

通用 Config 只能解析公共字段和 extensions 容器，不得读取 Runtime 子类、DataSource 子类、Broker 子类或 Strategy 子类的专有参数。具体参数由具体 Factory 的配置解析器通过抽象接口处理。

将输出目录改为 engine_id/runtime_id/run_id 的标准布局，并通过 OnlyRuntimeResultExporter 输出。Runtime 不得直接写结果文件。

更新 YAML 和 JSON 示例，使同一配置结构可选择不同 runtime.type。运行所有历史测试、完整 Vertical Slice、静态架构检查和确定性重放。若配置仍绑定 Backtest、上层调用子类接口、通用层直接实例化具体组件、目录未按父类/子类结构整理或确定性失败，最终结论必须为 REJECTED。
```
