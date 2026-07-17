# OnlyAlpha Engine、Cluster 配置、CLI 与 user_data 架构重构任务

## 1. 任务目标

本任务需要基于当前 OnlyAlpha 最新代码，完成产品运行入口和工程目录的系统性重构。

最终产品使用方式必须是：

```bash
uv run onlyalpha run \
  --config <cluster-config-1> \
  --config <cluster-config-2>
```

核心运行流程必须是：

```text
CLI
→ 初始化 OnlyEngine
→ 加载一个或多个 Cluster 配置
→ engine.add_cluster(config)
→ engine.run()
```

必须实现以下目标：

```text
一个配置文件对应一个 Cluster

一次 CLI 命令可以加载多个 Cluster 配置

OnlyEngine 是整个项目唯一的产品级运行入口

Engine 可以在启动前加载多个 Cluster

Engine 必须预留运行时动态加载和卸载 Cluster 的能力

所有运行产物统一进入 user_data

user_data 默认位于当前项目工作目录下

用户可以通过命令行指定 user_data 路径

examples 目录只保留按 Cluster 分类的配置文件

示例 Strategy 和 Factor 不得放在 src/onlyalpha

合成历史数据 + 虚拟券商的完整回测必须通过
```

本任务不是简单修改 CLI 参数，而是需要同步重构：

```text
CLI
Engine
Cluster 配置模型
配置加载器
Cluster Factory
Runtime 分组与创建
基础设施复用
输出目录
示例目录
动态加载与卸载接口
回测成品 Demo
测试与文档
```

---

# 2. 项目执行依据

开始修改前必须先读取当前最新代码，重点检查：

```text
pyproject.toml
src/onlyalpha/cli.py

src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/cluster/
src/onlyalpha/config/

src/onlyalpha/data/
src/onlyalpha/broker/
src/onlyalpha/output/

src/onlyalpha/strategy/
src/onlyalpha/factor/
src/onlyalpha/indicator/

examples/
tests/
docs/
docs/adr/
```

所有修改必须以当前仓库真实接口为准。

禁止：

```text
依据历史对话假设接口仍然存在

重新建立一套与当前架构平行的 Engine

为了 Demo 绕过现有 Cluster/Runtime/Factory

保留错误的旧运行入口作为主要产品入口

直接在 CLI 中手工装配 Runtime、Broker、DataSource 或 Manager
```

---

# 3. 最终产品架构

目标结构：

```text
OnlyEngine
├── Cluster Registry
│   ├── OnlyCluster A
│   │   ├── OnlyStrategy
│   │   └── OnlyFactor[]
│   ├── OnlyCluster B
│   └── OnlyCluster N
│
├── Runtime Registry
│   ├── OnlyBacktestRuntime
│   ├── OnlyPaperRuntime
│   └── OnlyLiveRuntime
│
├── Infrastructure Registry
│   ├── DataSources
│   ├── BrokerGateways
│   ├── Accounts
│   ├── Instruments
│   └── TradingCalendars
│
├── Output Service
├── State/Cache Service
└── Engine Lifecycle
```

核心原则：

```text
CLI 只负责参数解析和调用 Engine

Engine 负责 Cluster 生命周期和资源协调

Cluster 配置决定 Cluster 需要什么

Engine 决定基础设施如何创建、复用和关闭

Runtime 决定具体运行模式如何执行

Cluster 不直接创建或连接 DataSource/Broker

一个配置文件只定义一个 Cluster
```

---

# 4. CLI 目标

当前命令必须重构为：

```bash
uv run onlyalpha run --config <path>
```

必须支持重复参数：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --config examples/clusters/momentum/config.yaml
```

建议支持：

```bash
uv run onlyalpha run \
  --config-dir examples/clusters
```

可选支持：

```bash
uv run onlyalpha run \
  --config-glob "examples/clusters/*/config.yaml"
```

但第一优先级必须是：

```text
--config 可重复
```

不要使用逗号分隔文件路径。

## 4.1 CLI 参数

至少支持：

```text
run

--config PATH
    可重复
    至少一个配置

--config-dir DIRECTORY
    可选
    搜索目录中的配置文件

--user-data DIRECTORY
    可选
    指定 user_data 根目录

--engine-id ID
    可选
    默认 onlyalpha

--log-level LEVEL
    可选
    默认 INFO

--dry-run
    只校验配置和装配计划，不启动 Engine

--fail-fast
    任一 Cluster 配置失败时禁止启动整个 Engine

--no-fail-fast
    允许跳过失败 Cluster
```

第一阶段默认：

```text
fail_fast = true
```

## 4.2 CLI 配置路径处理

路径处理顺序：

```text
收集重复 --config
→ 展开 --config-dir
→ 展开 --config-glob
→ 转为绝对路径
→ 去重
→ 保持显式 --config 的顺序
→ 目录和 Glob 结果稳定排序
```

禁止依赖文件系统枚举顺序。

## 4.3 CLI 主流程

最终 `main()` 应接近：

```python
def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    engine = OnlyEngine(
        OnlyEngineConfig(
            engine_id=OnlyEngineId(args.engine_id),
            user_data_root=resolve_user_data_root(args.user_data),
            fail_fast=args.fail_fast,
        ),
        services=only_default_engine_services(),
    )

    for config_path in resolve_config_paths(args):
        engine.add_cluster_from_file(config_path)

    if args.dry_run:
        validation = engine.validate()
        print(validation.render())
        return validation.exit_code

    result = engine.run()
    return result.exit_code
```

CLI 不得：

```text
直接创建 OnlyBacktestRuntime

直接创建 OnlyVirtualBrokerGateway

直接创建 Synthetic DataSource

直接创建 Strategy、Factor 或 Indicator

直接调用 Runtime 子类专用方法

直接写结果文件
```

---

# 5. 一个配置文件对应一个 Cluster

当前如果配置顶层仍包含：

```yaml
clusters:
  - ...
```

必须重构为：

```yaml
cluster:
  ...
```

配置文件自身就是一个 Cluster 定义。

建议结构：

```yaml
schema_version: "1.0"

cluster:
  cluster_id: macd-demo
  enabled: true
  runtime_type: BACKTEST
  account_id: backtest-account
  risk_profile_id: cn-equity-default

runtime:
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

strategy:
  class_path: onlyalpha_examples.strategies.macd:OnlyMacdStrategy
  config_path: onlyalpha_examples.strategies.macd:OnlyMacdStrategyConfig
  extensions: {}

factors: []

output:
  enabled: true
```

建议配置类型命名：

```text
OnlyClusterRunConfig
OnlyClusterConfigDocument
```

不再使用一个文件中定义多个 Cluster 的主模型。

---

# 6. 配置模型重构

通用 Cluster 配置至少包含：

```text
OnlyClusterRunConfig
├── schema_version
├── cluster
├── runtime
├── reference_data
├── universes
├── data_sources
├── accounts
├── brokers
├── strategy
├── factors
└── output
```

## 6.1 Cluster Common

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyClusterCommonConfig:
    cluster_id: OnlyClusterId
    enabled: bool
    runtime_type: OnlyRuntimeType
    account_id: OnlyAccountId
    risk_profile_id: OnlyRiskProfileId | None
    metadata: Mapping[str, str]
```

## 6.2 配置解析职责

通用 Parser 解析：

```text
Cluster 公共字段
Runtime 公共字段
基础设施引用
Strategy/Factor 导入描述
Output 公共字段
```

具体组件的 `extensions` 由其 Factory 解析。

禁止通用 Parser 读取：

```text
Synthetic 价格模型
Virtual Broker 专用参数
具体 Strategy 参数
具体 Factor 参数
具体 Indicator 参数
```

---

# 7. OnlyEngine 产品接口

当前 OnlyEngine 必须从“Runtime 注册器”提升为：

> Cluster 生命周期和共享基础设施协调器。

建议正式接口：

```python
class OnlyEngine:
    def add_cluster_from_file(
        self,
        path: str | Path,
    ) -> OnlyClusterHandle:
        ...

    def add_cluster(
        self,
        config: OnlyClusterRunConfig,
    ) -> OnlyClusterHandle:
        ...

    def remove_cluster(
        self,
        cluster_id: OnlyClusterId,
        *,
        policy: OnlyClusterRemovalPolicy,
    ) -> OnlyClusterRemovalResult:
        ...

    def start_cluster(
        self,
        cluster_id: OnlyClusterId,
    ) -> OnlyClusterOperationResult:
        ...

    def pause_cluster(
        self,
        cluster_id: OnlyClusterId,
    ) -> OnlyClusterOperationResult:
        ...

    def resume_cluster(
        self,
        cluster_id: OnlyClusterId,
    ) -> OnlyClusterOperationResult:
        ...

    def validate(self) -> OnlyEngineValidationResult:
        ...

    def run(self) -> OnlyEngineRunResult:
        ...

    def stop(self) -> OnlyEngineOperationResult:
        ...

    def snapshot(self) -> OnlyEngineSnapshot:
        ...
```

## 7.1 add_cluster_from_file

只负责：

```text
读取文件
→ 解析 OnlyClusterRunConfig
→ 调用 add_cluster(config)
```

核心业务必须在：

```text
add_cluster(config)
```

这样未来 Web 可以直接提交 JSON Mapping：

```python
config = OnlyClusterRunConfig.from_mapping(payload)
engine.add_cluster(config)
```

无需创建临时配置文件。

---

# 8. Engine 状态与动态加载

建议 Engine 状态：

```text
CREATED
CONFIGURING
READY
RUNNING
STOPPING
STOPPED
FAILED
```

## 8.1 启动前 add_cluster

在：

```text
CREATED
CONFIGURING
READY
```

状态下：

```text
解析配置
→ 校验
→ 创建或规划基础设施
→ 创建 Runtime 绑定
→ 创建 Cluster
→ 注册到 Engine
```

Cluster 暂不执行策略。

## 8.2 运行时 add_cluster

在：

```text
RUNNING
```

状态下必须支持未来动态加载。

流程：

```text
进入 LOADING
→ 配置校验
→ 资源兼容性检查
→ 创建或复用基础设施
→ 创建 Runtime 或选择兼容 Runtime
→ 创建 Cluster
→ 初始化 Factor/Indicator/Strategy
→ 建立订阅
→ Warmup
→ READY
→ RUNNING
```

必须保证事务性。

任何步骤失败：

```text
撤销订阅
停止已创建组件
释放资源引用
不注册到活动 Cluster 集合
返回结构化失败
```

不能留下半初始化状态。

---

# 9. 动态卸载 Cluster

实现：

```text
OnlyClusterRemovalPolicy
```

至少支持：

```text
STOP_ONLY
CANCEL_OPEN_ORDERS
CANCEL_AND_WAIT
FAIL_IF_OPEN_ORDERS
KEEP_EXTERNAL_ORDERS
```

第一阶段 Backtest 推荐：

```text
STOP_ONLY
```

未来 Paper/Live 默认建议：

```text
CANCEL_AND_WAIT
```

卸载流程：

```text
阻止新 Strategy 决策
→ 停止新订单提交
→ Broker Update 继续处理
→ 根据策略处理未完成订单
→ 等待安全状态
→ 停止 Strategy
→ 停止 Factor
→ 释放 Indicator
→ 取消 MarketData Subscription 引用
→ 保存最终 Snapshot
→ 释放基础设施引用
→ 从 Engine Registry 移除
```

不得直接：

```python
del clusters[cluster_id]
```

---

# 10. Cluster Handle

建议定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyClusterHandle:
    cluster_id: OnlyClusterId
    runtime_id: OnlyRuntimeId
    status: OnlyClusterStatus
    config_fingerprint: str
```

外部不应直接持有 Cluster 内部可变对象。

后续 Web/CLI 使用 Handle 进行管理。

---

# 11. Runtime 选择与复用

一个 Engine 可以管理多个 Runtime：

```text
OnlyEngine
├── Backtest Runtime A
├── Backtest Runtime B
├── Paper Runtime
└── Live Runtime
```

Cluster 根据配置绑定 Runtime。

Engine 不应仅根据：

```text
runtime_type
```

判断是否复用 Runtime。

必须定义：

```text
OnlyRuntimeCompatibilityKey
```

至少包含：

```text
runtime_type
start_time
end_time
clock_policy
replay_policy
data_version
broker_environment
account_environment
```

两个 Backtest Cluster 只有运行环境兼容时才可共享 Runtime。

不兼容时必须创建独立 Runtime。

禁止：

```text
所有 BACKTEST Cluster 强制使用同一个 Runtime
```

---

# 12. 共享基础设施 Registry

实现或完善：

```text
OnlyInfrastructureRegistry
OnlyResourceCompatibilityChecker
OnlyResourceReferenceCounter
```

Engine 按 ID 管理：

```text
TradingCalendar
Instrument
DataSource
BrokerGateway
Account
Runtime
```

## 12.1 相同配置复用

例如两个 Cluster：

```text
gateway_id = virtual-main
type = OnlyVirtualBrokerGateway
```

且配置 Fingerprint 相同，可以复用。

## 12.2 配置冲突

同一个 ID 对应不同配置时必须失败：

```text
RESOURCE_CONFIGURATION_CONFLICT
```

禁止后加载配置覆盖先前配置。

## 12.3 引用计数

Cluster 卸载时：

```text
reference_count -= 1
```

只有引用数归零时才允许关闭资源。

---

# 13. user_data 根目录

所有与源码无关的产物必须进入：

```text
user_data/
```

默认值：

```text
当前工作目录 / user_data
```

支持环境变量：

```text
ONLYALPHA_USER_DATA
```

优先级：

```text
--user-data
→ ONLYALPHA_USER_DATA
→ ./user_data
```

禁止：

```text
输出文件写入 examples
输出文件写入 src
输出文件写入 tests
运行状态写入代码目录
缓存文件散落在项目根目录
```

---

# 14. user_data 目录设计

推荐：

```text
user_data/
├── runs/
│   └── <engine_id>/
│       └── <run_id>/
│           ├── manifest.json
│           ├── engine/
│           ├── clusters/
│           ├── runtimes/
│           ├── shared/
│           └── logs/
│
├── state/
│   ├── engine/
│   ├── clusters/
│   ├── runtimes/
│   └── checkpoints/
│
├── cache/
│   ├── market_data/
│   ├── reference_data/
│   ├── factors/
│   └── indicators/
│
├── data/
│   ├── historical/
│   ├── imports/
│   └── synthetic/
│
├── logs/
└── tmp/
```

## 14.1 单次运行结果

```text
user_data/runs/<engine_id>/<run_id>/
├── manifest.json
├── engine/
│   ├── config.json
│   ├── summary.json
│   ├── snapshot.json
│   └── health.json
│
├── clusters/
│   └── <cluster_id>/
│       ├── source_config.yaml
│       ├── normalized_config.json
│       ├── fingerprint.txt
│       ├── summary.json
│       ├── strategy/
│       ├── factors/
│       ├── indicators/
│       ├── orders/
│       ├── portfolio/
│       └── report.md
│
├── runtimes/
│   └── <runtime_id>/
│
├── shared/
│   ├── accounts/
│   └── brokers/
│
└── logs/
```

一份配置对应一个 Cluster，因此 Cluster 必须是结果目录的一级业务边界。

---

# 15. Output 抽象

Runtime、Cluster 和 Engine 不应直接拼接文件路径。

实现或完善：

```text
OnlyUserDataLayout
OnlyRunDirectory
OnlyRuntimeResultExporter
OnlyEngineResultExporter
OnlyOutputManifest
```

推荐：

```python
class OnlyUserDataLayout:
    def run_root(
        self,
        engine_id: OnlyEngineId,
        run_id: OnlyRunId,
    ) -> Path:
        ...

    def cluster_root(
        self,
        engine_id: OnlyEngineId,
        run_id: OnlyRunId,
        cluster_id: OnlyClusterId,
    ) -> Path:
        ...
```

所有路径生成必须集中管理。

禁止每个组件自行：

```python
Path("output") / ...
```

---

# 16. examples 目录重构

最终 `examples/` 只保留配置文件和说明文档。

推荐：

```text
examples/
├── clusters/
│   ├── macd/
│   │   ├── config.yaml
│   │   ├── config.json
│   │   └── synthetic_market.yaml
│   │
│   ├── trend/
│   │   └── config.yaml
│   │
│   ├── cross_section/
│   │   └── config.yaml
│   │
│   └── paper_demo/
│       └── config.yaml
│
└── README.md
```

清理：

```text
examples/*_demo/*.py
examples/integration_demo/
examples/account_demo/
examples/clock_demo/
examples/execution_processor_demo/
examples/backtest_macd/run.py
```

这些能力应转为：

```text
tests
文档
配置示例
```

而不是保留大量手工运行 Python 脚本。

---

# 17. 示例 Strategy 和 Factor 插件

因为 `examples` 只保留配置，示例 Python Strategy/Factor 不能继续放在 `examples`。

同时它们也不应放在：

```text
src/onlyalpha
```

建议建立独立插件包：

```text
plugins/
└── onlyalpha_examples/
    ├── pyproject.toml
    └── src/
        └── onlyalpha_examples/
            ├── __init__.py
            ├── strategies/
            │   └── macd/
            │       ├── strategy.py
            │       ├── config.py
            │       └── result.py
            │
            └── factors/
                └── macd_signal/
                    ├── factor.py
                    ├── config.py
                    └── snapshot.py
```

配置路径：

```yaml
strategy:
  class_path: onlyalpha_examples.strategies.macd.strategy:OnlyMacdStrategy
  config_path: onlyalpha_examples.strategies.macd.config:OnlyMacdStrategyConfig
```

Factor：

```yaml
factors:
  - factor_id: macd-signal
    class_path: onlyalpha_examples.factors.macd_signal.factor:OnlyMacdSignalFactor
    config_path: onlyalpha_examples.factors.macd_signal.config:OnlyMacdSignalFactorConfig
```

必须确保：

```bash
uv sync
```

或开发安装后可以导入该插件包。

---

# 18. MACD Cluster 示例配置

创建：

```text
examples/clusters/macd/config.yaml
```

要求：

* 一个文件对应一个 Cluster；
* Runtime 类型为 BACKTEST；
* 使用合成历史数据；
* 使用虚拟券商；
* 使用 MACD Signal Factor；
* 使用 MACD Strategy；
* Factor 内创建核心 OnlyMacdIndicator；
* 策略只读取 Factor；
* 输出进入 user_data。

示例结构：

```yaml
schema_version: "1.0"

cluster:
  cluster_id: macd-demo
  enabled: true
  runtime_type: BACKTEST
  account_id: backtest-account
  risk_profile_id: cn-equity-default

runtime:
  start_time: "2026-01-05T01:30:00Z"
  end_time: "2026-01-08T07:01:00Z"
  base_currency: CNY

reference_data:
  calendars:
    - calendar_id: CN_XSHG
      venue: XSHG
      timezone: Asia/Shanghai
      sessions:
        - name: morning
          opens_at: "09:30:00"
          closes_at: "11:30:00"
          session_type: CONTINUOUS
        - name: afternoon
          opens_at: "13:00:00"
          closes_at: "15:00:00"
          session_type: CONTINUOUS
      holidays: []

  instruments:
    - instrument_id: TESTETF.XSHG
      symbol: TESTETF
      venue: XSHG
      asset_class: ETF
      timezone: Asia/Shanghai
      trading_calendar_id: CN_XSHG
      settlement_rule_id: CN_EQUITY_T_PLUS_1
      price_precision: 2
      quantity_precision: 0
      price_increment: "0.01"
      quantity_increment: "100"
      lot_size: "100"
      minimum_quantity: "100"
      maximum_quantity: "100000000"

universes:
  - universe_id: macd-demo-universe
    type: STATIC
    instruments:
      - TESTETF.XSHG

data_sources:
  - source_id: synthetic-cn-etf
    type: SYNTHETIC
    data_version: macd-engine-demo-v1
    random_seed: 20260715
    batch_size: 128

    coverage:
      universe_ids:
        - macd-demo-universe

    extensions:
      market_config: synthetic_market.yaml

accounts:
  - account_id: backtest-account
    gateway_id: virtual-macd-demo

    initial_cash:
      value: "1000000.00"
      currency: CNY

brokers:
  - gateway_id: virtual-macd-demo
    type: OnlyVirtualBrokerGateway

    matching:
      type: NEXT_BAR

    commission:
      type: FIXED
      fixed_amount:
        value: "1.00"
        currency: CNY

    slippage:
      type: NONE

strategy:
  class_path: onlyalpha_examples.strategies.macd.strategy:OnlyMacdStrategy
  config_path: onlyalpha_examples.strategies.macd.config:OnlyMacdStrategyConfig

  extensions:
    signal_factor_id: macd-signal
    trade_quantity: "1000"
    allow_reentry: false
    exit_mode: FULL_AVAILABLE

factors:
  - factor_id: macd-signal
    factor_type: TIME_SERIES
    class_path: onlyalpha_examples.factors.macd_signal.factor:OnlyMacdSignalFactor
    config_path: onlyalpha_examples.factors.macd_signal.config:OnlyMacdSignalFactorConfig
    required: true

    subscriptions:
      instrument_bars:
        - instrument_id: TESTETF.XSHG
          bar_specification:
            step: 1
            aggregation: MINUTE
            price_type: LAST
            source: EXTERNAL
          role: PRIMARY

    indicators:
      - indicator_id: macd
        type: MACD
        parameters:
          fast_period: 12
          slow_period: 26
          signal_period: 9
          price_field: CLOSE

    extensions:
      scoring:
        histogram_scale: "1.0"

output:
  enabled: true
```

---

# 19. 回测完整链路验收

必须通过以下完整链路：

```text
CLI
→ OnlyEngine
→ add_cluster_from_file
→ OnlyClusterRunConfig
→ Infrastructure Registry
→ Runtime Factory
→ OnlyBacktestRuntime
→ Cluster Factory
→ Strategy Factory
→ Factor Factory
→ Indicator Factory Registry
→ OnlySyntheticHistoricalDataSource
→ OnlyHistoricalReplayService
→ OnlyBacktestClock
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
→ OnlyMacdIndicator
→ OnlyMacdSignalFactor
→ OnlyMacdStrategy
→ Order
→ Risk
→ OnlyVirtualBrokerGateway
→ MatchingEngine
→ BrokerInboundQueue
→ OnlyExecutionProcessor
→ Position
→ Allocation
→ StrategyLedger
→ Account
→ OnlyEngineRunResult
→ user_data
```

正常回测不得：

```text
CLI 直接创建 Runtime

Engine 直接创建 MACD

Strategy 直接计算 MACD

Factor 下单

Demo 手工调用 Manager

手工构造成交

绕过 Virtual Broker

绕过 Execution Processor

写结果到 examples
```

---

# 20. Engine.run() 语义

建议：

```python
def run(self) -> OnlyEngineRunResult:
    self.initialize()
    self.start()

    try:
        return self._coordinate_runtime_execution()
    finally:
        self.stop()
```

Backtest Runtime：

```text
历史回放完成后自动完成
```

Paper/Live Runtime：

```text
运行到收到停止命令或系统信号
```

Engine 统一汇总 Runtime 结果。

---

# 21. 多 Cluster 回测测试

新增至少两个配置：

```text
examples/clusters/macd/config.yaml
examples/clusters/macd_fast/config.yaml
```

命令：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --config examples/clusters/macd_fast/config.yaml \
  --user-data ./user_data
```

验证：

```text
两个 Cluster 均被加载
Cluster ID 不重复
运行结果相互隔离
策略状态相互隔离
Factor 状态相互隔离
Indicator 状态相互隔离
输出目录相互隔离
共享资源配置一致时正确复用
引用计数正确
一个 Cluster 失败时 fail-fast 行为正确
```

---

# 22. dry-run 测试

命令：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --dry-run
```

必须完成：

```text
文件读取
Schema 校验
动态类加载
Strategy/Factor 配置校验
Instrument/Universe 引用校验
Broker/DataSource 能力校验
资源冲突校验
Runtime Compatibility 分组
输出目录计划
```

不得：

```text
启动 Runtime
生成订单
推进 Clock
写入正式运行结果
```

可以在：

```text
user_data/tmp
```

写临时诊断，但默认最好只输出终端报告。

---

# 23. 动态加载和卸载测试

即使第一阶段 CLI 主要在启动前加载 Cluster，也必须实现并测试 Engine API：

```python
engine.add_cluster(config)
engine.remove_cluster(cluster_id, policy=...)
```

测试：

```text
Engine CREATED 时 add_cluster

Engine READY 时 add_cluster

Engine RUNNING 时动态 add_cluster

重复 Cluster ID 被拒绝

动态加载失败完整回滚

动态卸载成功

卸载后资源引用减少

共享资源仍被其他 Cluster 使用时不关闭

最后一个引用释放后资源关闭
```

Backtest Runtime 如果无法在历史回放中途动态加入 Cluster，必须返回明确结构化结果：

```text
DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE
```

但 Engine API 和状态机必须存在。

---

# 24. 结果与 user_data 测试

至少验证：

```text
默认 user_data = cwd/user_data

--user-data 覆盖默认值

ONLYALPHA_USER_DATA 可作为默认值

命令行优先级最高

所有产出位于 user_data

examples 目录无运行产出

src 目录无运行产出

Cluster 结果目录按 cluster_id 分离

run_id 唯一

manifest 记录所有 Cluster 配置

normalized_config 和 fingerprint 正确

输出路径不影响业务确定性 fingerprint
```

---

# 25. 示例目录清理

删除或迁移所有非配置型 Examples。

任何仍有验证价值的 Python Demo 应改为：

```text
tests
```

任何属于用户使用说明的内容应改为：

```text
docs
```

任何示例 Strategy/Factor 应改为：

```text
plugins/onlyalpha_examples
```

最终 `examples` 中不得保留产品运行 Python 脚本。

统一入口只能是：

```bash
uv run onlyalpha run --config ...
```

---

# 26. 测试目录建议

新增或更新：

```text
tests/cli/
├── test_run_single_config.py
├── test_run_multiple_configs.py
├── test_config_dir.py
├── test_user_data_option.py
├── test_dry_run.py
└── test_fail_fast.py

tests/engine/
├── test_add_cluster.py
├── test_add_cluster_from_file.py
├── test_duplicate_cluster.py
├── test_dynamic_add_cluster.py
├── test_remove_cluster.py
├── test_resource_reference_count.py
├── test_resource_conflict.py
└── test_engine_run.py

tests/config/
├── test_single_cluster_document.py
├── test_cluster_config_yaml_json_equivalence.py
└── test_cluster_reference_validation.py

tests/output/
├── test_user_data_layout.py
├── test_cluster_output_layout.py
└── test_manifest.py

tests/integration/
├── test_cli_synthetic_virtual_broker_backtest.py
├── test_engine_two_cluster_backtest.py
├── test_engine_cluster_isolation.py
├── test_engine_user_data_output.py
└── test_engine_deterministic_replay.py
```

---

# 27. 确定性验证

使用固定：

```text
Cluster Config
Synthetic Market Config
Random Seed
Instrument
Calendar
Data Version
Strategy
Factor
Indicator
Risk
Virtual Broker
Matching Model
Commission
```

至少重复执行 100 次。

比较：

```text
Engine Runtime 分组
Cluster 加载顺序
Generated Bars
Clock Sequence
Indicator Snapshot
Factor Snapshot
Strategy Callback
OrderId
TradeId
Order State
Position
Allocation
Ledger
Account
Engine Result
Cluster Result
Manifest
业务 Determinism Fingerprint
```

必须完全一致。

以下内容可以不同，但不得进入业务 Fingerprint：

```text
绝对 user_data 路径
操作系统临时路径
实际日志文件路径
进程 ID
墙钟运行时间
```

---

# 28. 文档更新

创建或更新：

```text
docs/cli.md
docs/engine.md
docs/cluster_configuration.md
docs/user_data.md
docs/output_layout.md
docs/runtime.md
docs/cluster.md
docs/plugin_examples.md
docs/backtest.md
docs/integration_vertical_slice.md
docs/architecture_principles.md
examples/README.md
plugins/onlyalpha_examples/README.md
```

必须说明：

```text
一个配置文件对应一个 Cluster

CLI 可重复使用 --config

OnlyEngine 是唯一产品入口

Engine.add_cluster 接收强类型配置

add_cluster_from_file 只属于文件适配层

Engine 支持动态加载和卸载

user_data 是所有产出的统一根目录

examples 只包含配置

示例 Python 组件位于独立插件包

回测使用 Synthetic DataSource 和 Virtual Broker
```

---

# 29. ADR

创建：

```text
docs/adr/0019-engine-cluster-cli-and-user-data-layout.md
```

至少记录：

## 背景

当前 CLI 以单个完整 Run Config 直接调用 RunService；Engine 主要管理 Runtime；Examples 中存在大量 Python Demo；输出目录缺少统一 user_data 边界。

## 决策

* 一个配置文件定义一个 Cluster；
* CLI 支持多个 `--config`；
* OnlyEngine 成为唯一产品入口；
* Engine 管理 Cluster 生命周期；
* Engine 协调 Runtime 和共享基础设施；
* Engine 提供动态加载与卸载接口；
* 所有产出统一进入 user_data；
* Examples 只保留配置；
* 示例 Strategy/Factor 放入独立插件包；
* 回测通过合成数据和虚拟券商验证。

## 拒绝方案

* CLI 直接调用 Backtest RunService；
* 一个文件定义整个 Engine 的所有 Cluster；
* 每个 Cluster 独占重复 Gateway；
* Examples 保留大量 Python Demo；
* 运行结果写入 Examples；
* Engine 仅作为 Runtime 字典；
* 动态卸载直接删除对象；
* Web 未来通过 CLI 加载 Cluster。

---

# 30. Architecture Principles 新增规则

加入：

```text
Rule: OnlyEngine 是 OnlyAlpha 唯一产品级运行入口。

Rule: CLI 只能调用 OnlyEngine 公共接口。

Rule: 一个配置文档只能定义一个 OnlyCluster。

Rule: 多 Cluster 通过多个配置文件加载。

Rule: Engine.add_cluster 接收强类型 Cluster 配置。

Rule: 文件路径解析必须由 add_cluster_from_file 适配。

Rule: Engine 必须提供动态加载和卸载 Cluster 的正式接口。

Rule: Cluster 动态加载必须具备事务性和失败回滚。

Rule: 共享基础设施必须通过 Registry 和引用计数管理。

Rule: 同一资源 ID 对应不同配置必须拒绝。

Rule: 所有非源码运行产物必须写入 user_data。

Rule: Examples 目录只能包含配置文件和说明文档。

Rule: 示例 Strategy 和 Factor 必须位于独立插件包。

Rule: 产品运行必须使用 onlyalpha CLI，不使用示例 Python 脚本。

Rule: 回测必须通过 Synthetic DataSource、Virtual Broker 和完整交易链。
```

---

# 31. 实现顺序

严格按以下顺序执行：

1. 拉取并检查当前最新代码；
2. 创建架构差距分析；
3. 检查当前 CLI 和 pyproject entry point；
4. 设计单 Cluster 配置文档；
5. 重构配置模型；
6. 支持 YAML/JSON 单 Cluster 配置；
7. 修改 CLI 支持多个 `--config`；
8. 增加 `--user-data`；
9. 增加 `--dry-run`；
10. 重构 OnlyEngine 公共接口；
11. 实现 `add_cluster_from_file()`；
12. 实现 `add_cluster(config)`；
13. 实现 Cluster Registry；
14. 实现 Runtime Compatibility Key；
15. 实现 Runtime 创建和复用；
16. 实现 Infrastructure Registry；
17. 实现资源配置冲突检查；
18. 实现资源引用计数；
19. 实现 Engine.run()；
20. 实现动态 Cluster 加载状态机；
21. 实现动态 Cluster 卸载接口；
22. 实现 user_data 根目录解析；
23. 实现标准 user_data Layout；
24. 修改 Output Exporter；
25. 建立 onlyalpha_examples 插件包；
26. 迁移 MACD Strategy 和 Factor；
27. 清理 src 中的 MACD Demo；
28. 清理 Examples Python Demo；
29. 创建 MACD Cluster 配置；
30. 跑通单 Cluster 回测；
31. 跑通多 Cluster 回测；
32. 验证 Synthetic DataSource；
33. 验证 Virtual Broker；
34. 验证完整 Execution 链；
35. 增加 CLI/Engine/Output 测试；
36. 运行全部历史测试；
37. 运行完整 Vertical Slice；
38. 运行 100 次确定性重放；
39. 更新文档；
40. 创建 ADR；
41. 生成最终报告。

---

# 32. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

```text
CLI 仍然只能加载一个配置

一个配置仍然定义多个 Cluster

CLI 直接创建 Runtime

CLI 直接创建 Broker 或 DataSource

CLI 绕过 OnlyEngine

OnlyEngine 仍然只管理 Runtime 而不管理 Cluster

Engine.add_cluster 只接受文件路径

不存在强类型 add_cluster(config)

Engine 不提供 remove_cluster

动态加载失败不回滚

Cluster 卸载直接删除对象

共享资源没有冲突检查

共享资源没有引用计数

运行产物写入 examples

运行产物写入 src

默认输出路径不是 user_data

--user-data 无效

Examples 仍包含产品运行 Python 脚本

MACD Strategy 或 Factor 仍在 src/onlyalpha

回测绕过 Synthetic HistoricalDataSource

回测绕过 Virtual Broker

成交绕过 ExecutionProcessor

完整回测无法通过 CLI 启动

多 Cluster 状态互相污染

历史测试被删除、Skip 或放宽

完整 Vertical Slice 失败

确定性重放结果不一致
```

---

# 33. 最终验收命令

以下命令必须成功：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --user-data ./user_data
```

多 Cluster：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --config examples/clusters/macd_fast/config.yaml \
  --user-data ./user_data
```

Dry Run：

```bash
uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --dry-run
```

测试：

```bash
uv run pytest
```

所有命令必须使用正式接口，不允许使用临时脚本。

---

# 34. 最终报告

生成：

```text
docs/reports/engine_cluster_cli_userdata_refactor_report.md
```

至少包含：

```text
修改前 CLI
修改后 CLI
单 Cluster 配置模型
多配置加载
OnlyEngine 公共接口
add_cluster
add_cluster_from_file
remove_cluster
Engine 状态机
Cluster 动态加载
Cluster 动态卸载
Runtime Compatibility
Runtime Registry
Infrastructure Registry
资源冲突检查
资源引用计数
user_data 根目录
Output Layout
Examples 清理
示例插件包
MACD Strategy 迁移
MACD Factor 迁移
Synthetic DataSource
Virtual Broker
单 Cluster 回测
多 Cluster 回测
完整交易链
CLI 测试
Engine 测试
历史测试结果
Vertical Slice
100 次确定性重放
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

# 35. Codex 启动指令

严格按照本任务执行 OnlyAlpha 的 Engine、Cluster 配置、CLI、user_data 和 Examples 架构重构。

最终产品入口必须是：

```bash
uv run onlyalpha run --config <cluster-config>
```

`--config` 必须支持重复使用，一次命令可以加载多个 Cluster 配置。一个配置文件只能定义一个 Cluster，不得再通过一个配置文件定义整个 Engine 的多个 Cluster。

CLI 必须只初始化 OnlyEngine，然后逐个加载配置：

```text
OnlyEngine()
→ engine.add_cluster(config)
→ engine.run()
```

必须同时提供：

```text
engine.add_cluster_from_file(path)
engine.add_cluster(config)
engine.remove_cluster(cluster_id, policy)
```

其中 `add_cluster(config)` 是核心接口，文件路径只是适配层。Engine 必须预留并实现运行时动态加载和安全卸载 Cluster 的正式状态机，加载失败必须完整回滚。

OnlyEngine 必须从 Runtime 注册器重构为 Cluster 生命周期和共享基础设施协调器。Engine 负责创建或复用 Runtime、DataSource、BrokerGateway、Account、Instrument 和 Calendar。相同资源 ID 且配置相同可以复用；相同 ID 但配置不同必须拒绝。共享资源必须使用引用计数管理。

所有运行结果、状态、缓存、日志、合成数据和临时文件必须进入统一 user_data 根目录。默认根目录是当前工作目录下的 `user_data`，支持 `--user-data` 和 `ONLYALPHA_USER_DATA` 覆盖。任何运行产物不得写入 src、examples 或 tests。

重构 examples，使其只保留按照 Cluster 分类的 YAML/JSON 配置和 README。将示例 Strategy 和 Factor 迁移到独立的 `plugins/onlyalpha_examples` Python 包。核心 MACD Indicator 保留在 `src/onlyalpha/indicator/macd`，MACD Strategy 和 MACD Factor 不得留在核心 src。

必须通过正式 CLI 跑通完整 MACD 回测：

```text
CLI
→ Engine
→ Cluster
→ Synthetic HistoricalDataSource
→ Historical Replay
→ Backtest Clock
→ MarketData Pipeline
→ MACD Indicator
→ MACD Factor
→ MACD Strategy
→ Order
→ Risk
→ Virtual Broker
→ Matching
→ ExecutionProcessor
→ Position
→ Allocation
→ Ledger
→ Account
→ Engine Result
→ user_data
```

同时必须跑通两个 Cluster 的并行/协调回测，验证 Cluster、Strategy、Factor、Indicator 和输出状态完全隔离。

实现 `--dry-run`，在不启动 Runtime 的情况下完成配置解析、动态类加载、引用校验、资源冲突检查、Runtime 分组和输出计划。

运行所有历史测试、完整 Vertical Slice 和至少 100 次确定性重放。若 CLI 绕过 Engine、一个配置仍含多个 Cluster、Engine 不支持动态加载/卸载、产物未进入 user_data、Examples 仍包含运行 Python 脚本、MACD Demo 仍在核心 src、回测绕过 Synthetic DataSource/Virtual Broker/ExecutionProcessor，或确定性结果不一致，最终结论必须为 REJECTED。
