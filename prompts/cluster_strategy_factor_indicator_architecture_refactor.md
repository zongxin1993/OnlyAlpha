# OnlyAlpha Cluster、Strategy、Factor 与 Indicator 架构重构任务

## 1. 任务目标

本任务需要根据 OnlyAlpha 当前最新仓库实现，对策略运行体系进行一次完整架构重构。

最终目标模型必须是：

```text
OnlyEngine
└── 多个相互隔离的 OnlyCluster
    ├── 一个 OnlyStrategy
    └── 多个 OnlyFactor
        └── 每个 OnlyFactor 内部使用一个或多个 OnlyIndicator
```

各层语义必须固定为：

```text
OnlyIndicator
    最底层技术、统计或数据计算单元

OnlyFactor
    组合一个或多个 Indicator
    形成具有明确业务语义的因子结果和评分

OnlyStrategy
    读取一个或多个 Factor 的结果
    生成交易决策并通过 Context 下单

OnlyCluster
    独立策略运行容器
    持有一个 Strategy、多个 Factor 及其 Indicator

OnlyEngine
    持有和管理多个相互独立的 Cluster
```

本任务不是局部修改 MACD 示例。

本任务需要修正当前仓库中以下错误或不完整设计：

```text
OnlyCluster 被直接当作具体策略基类
Strategy Factory 同时创建 Strategy 和 Indicator
Runtime 或 Assembly 主持具体指标
StrategyBuildResult 返回 indicators
Bar Subscription 携带 indicator_ids
具体 MACD 策略和 MACD Factory 存放在 src/onlyalpha
Strategy、Factor、Indicator 的所有权和生命周期不清晰
Factor 模型尚未形成
时序因子和截面因子没有明确区分
Indicator 缺少统一 Factory Registry 和评分接口
```

---

# 2. 项目身份与执行依据

OnlyAlpha 是一个完全独立、从零设计的量化交易系统。

本任务只依据：

```text
AGENTS.md
当前 OnlyAlpha 最新仓库
docs/
docs/adr/
当前已批准的 Domain、Runtime、MarketData、Order、Risk、
Position、Ledger、Account、Broker 和 Execution 架构
```

开始任务前必须先读取仓库最新代码，不得依据旧版本和历史对话假设当前接口。

禁止：

* 参考其他旧工程；
* 引入迁移兼容层；
* 保留已经失去当前业务意义的 MACD 专用核心接口；
* 为了让旧测试通过而保留错误的层级关系；
* 在 Runtime 或 Assembly 中写死 MACD、RSI 等具体实现。

---

# 3. 最终架构模型

必须实现以下对象关系：

```text
OnlyEngine
├── OnlyCluster A
│   ├── OnlyStrategy A
│   ├── OnlyFactor A1
│   │   ├── OnlyIndicator A1-1
│   │   └── OnlyIndicator A1-2
│   └── OnlyFactor A2
│       └── OnlyIndicator A2-1
│
└── OnlyCluster B
    ├── OnlyStrategy B
    └── OnlyFactor B1
        ├── OnlyIndicator B1-1
        ├── OnlyIndicator B1-2
        └── OnlyIndicator B1-3
```

强制约束：

```text
一个 Cluster 只能有一个 Strategy

一个 Cluster 可以有零个或多个 Factor

一个 Factor 可以使用一个或多个 Indicator

Strategy 不直接拥有通用 Indicator

Factor 不允许下单

Indicator 不知道 Factor、Strategy、Cluster 或 Runtime

不同 Cluster 不共享可变 Strategy、Factor 或 Indicator 实例

所有组件通过明确 Context 使用系统能力
```

---

# 4. 各层职责

## 4.1 OnlyEngine

`OnlyEngine` 负责：

* 创建和管理多个 Runtime；
* 每个 Runtime 内管理多个 Cluster；
* Runtime 生命周期；
* Cluster 注册、启动、暂停、恢复和停止；
* 数据源、Broker、账户和基础设施装配；
* Cluster 隔离；
* 系统级 Snapshot 和 Health。

Engine 不负责：

* 指标计算；
* 因子算法；
* 策略买卖逻辑；
* 具体 MACD、RSI 或其他算法。

## 4.2 OnlyCluster

`OnlyCluster` 是独立策略运行容器，不是策略本身。

负责：

* 持有一个 `OnlyStrategy`；
* 持有多个 `OnlyFactor`；
* 持有 Cluster Scope 的 Indicator Registry；
* 管理 Strategy、Factor 和 Indicator 生命周期；
* 绑定 Account；
* 绑定 Risk Profile；
* 绑定 Strategy Ledger；
* 绑定 Position Allocation；
* 汇总数据订阅需求；
* 构建和暴露受限 Context；
* 调度 Indicator → Factor → Strategy；
* 生成 Cluster Snapshot；
* 保证不同 Cluster 的可变状态完全隔离。

Cluster 不负责：

* 实现具体买卖规则；
* 实现具体因子算法；
* 实现具体技术指标；
* 直接连接数据源或 Broker。

## 4.3 OnlyStrategy

`OnlyStrategy` 负责：

* 读取 Factor Snapshot；
* 组合多个 Factor；
* 生成交易决策；
* 通过 `ctx.orders` 提交订单；
* 维护策略私有决策状态；
* 处理 Bar、Timer、Order、Trade 等策略回调；
* 输出策略专有诊断结果。

Strategy 不负责：

* 创建或维护通用 Indicator；
* 直接修改 Position；
* 直接修改 Account；
* 直接访问 Manager；
* 连接 Broker；
* 连接 MarketDataGateway；
* 推进 Clock；
* 调度 Factor。

## 4.4 OnlyFactor

`OnlyFactor` 负责：

* 创建或注册一个或多个 Indicator；
* 读取 Indicator Snapshot；
* 组合、转换、归一化或解释指标结果；
* 输出 Factor Snapshot；
* 输出统一 Factor Score；
* 管理 Warmup；
* 声明数据需求；
* 可选依赖其他 Factor。

Factor 不负责：

* 下单；
* 修改账户；
* 修改仓位；
* 修改 Strategy Ledger；
* 调用 Broker；
* 决定最终交易动作。

## 4.5 OnlyIndicator

`OnlyIndicator` 是最底层计算单元。

负责：

* 接收标准化 Bar、Tick、Quote 或其他输入；
* 维护滚动状态；
* 计算具体指标；
* 管理 Warmup；
* 输出不可变 Snapshot；
* 可选输出统一 Canonical Score；
* Reset 和序列化。

Indicator 不负责：

* 组合其他业务 Factor；
* 下单；
* 产生最终策略动作；
* 访问账户、持仓或 Broker；
* 访问 Strategy Context。

---

# 5. 继承层级

建议建立：

```text
OnlyComponent
├── OnlyStrategy
├── OnlyFactor
│   ├── OnlyTimeSeriesFactor
│   └── OnlyCrossSectionFactor
└── OnlyIndicator
    ├── OnlyBarIndicator
    ├── OnlyQuoteIndicator
    ├── OnlyTradeIndicator
    └── Future specialized indicators
```

不要为了形式增加无业务意义的继承层。

具体实现：

```text
OnlyMacdIndicator
    继承 OnlyBarIndicator

OnlyRsiIndicator
    继承 OnlyBarIndicator

OnlyTrendFactor
    继承 OnlyTimeSeriesFactor

OnlyMomentumRankFactor
    继承 OnlyCrossSectionFactor

OnlyTrendStrategy
    继承 OnlyStrategy
```

---

# 6. 目录结构

将核心抽象和正式通用组件保留在 `src/onlyalpha`。

推荐结构：

```text
src/onlyalpha/
├── engine/
│   ├── base.py
│   ├── config.py
│   ├── factory.py
│   └── snapshot.py
│
├── cluster/
│   ├── base.py
│   ├── config.py
│   ├── context.py
│   ├── factory.py
│   ├── lifecycle.py
│   ├── registry.py
│   ├── pipeline.py
│   └── snapshot.py
│
├── strategy/
│   ├── base.py
│   ├── config.py
│   ├── context.py
│   ├── factory.py
│   ├── result.py
│   └── errors.py
│
├── factor/
│   ├── base.py
│   ├── config.py
│   ├── context.py
│   ├── factory.py
│   ├── registry.py
│   ├── pipeline.py
│   ├── dependency.py
│   ├── score.py
│   ├── snapshot.py
│   ├── errors.py
│   ├── time_series/
│   │   └── base.py
│   └── cross_section/
│       └── base.py
│
└── indicator/
    ├── base.py
    ├── config.py
    ├── context.py
    ├── factory.py
    ├── registry.py
    ├── score.py
    ├── snapshot.py
    ├── identifiers.py
    ├── enums.py
    ├── errors.py
    │
    ├── macd/
    │   ├── indicator.py
    │   ├── config.py
    │   ├── snapshot.py
    │   └── factory.py
    │
    ├── rsi/
    ├── ema/
    ├── sma/
    ├── atr/
    ├── bollinger/
    ├── rolling_return/
    ├── rolling_volatility/
    └── zscore/
```

子类实现放在父类组件目录下的独立子目录中。

禁止继续使用：

```text
src/onlyalpha/indicator/macd.py
src/onlyalpha/indicator/rsi.py
```

在具体实现增加后继续平铺。

---

# 7. Demo 和业务示例目录

MACD Strategy、MACD Factor 等示例不属于 OnlyAlpha 核心库。

必须迁移到：

```text
examples/
├── strategies/
│   ├── macd/
│   │   ├── strategy.py
│   │   ├── config.py
│   │   ├── result.py
│   │   └── README.md
│   └── cross_section/
│
├── factors/
│   ├── macd_signal/
│   │   ├── factor.py
│   │   ├── config.py
│   │   ├── snapshot.py
│   │   └── README.md
│   ├── trend/
│   ├── momentum/
│   ├── liquidity/
│   └── rank/
│
├── configs/
│   ├── backtest/
│   │   ├── macd/
│   │   │   ├── run.yaml
│   │   │   ├── run.json
│   │   │   └── synthetic_market.yaml
│   │   └── cross_section/
│   ├── paper/
│   └── live/
│
└── run.py
```

需要删除或迁移：

```text
src/onlyalpha/strategies/macd.py
src/onlyalpha/strategy/macd.py
```

如果其中存在通用可复用能力，应提取到正式抽象模块；MACD 业务策略和因子本身必须迁移至 `examples`。

---

# 8. Strategy 抽象接口

定义正式抽象基类：

```python
class OnlyStrategy(ABC):
    def __init__(self, config: OnlyStrategyConfig) -> None:
        ...

    @property
    def strategy_id(self) -> OnlyStrategyId:
        ...

    @property
    def context(self) -> OnlyStrategyContext:
        ...

    @abstractmethod
    def on_initialize(self) -> None:
        ...

    def on_start(self) -> None:
        pass

    @abstractmethod
    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        ...

    def on_timer(self, context: OnlyStrategyTimerContext) -> None:
        pass

    def on_order_update(self, update: OnlyOrderSnapshot) -> None:
        pass

    def on_trade(self, trade: OnlyTradeSnapshot) -> None:
        pass

    def on_pause(self) -> None:
        pass

    def on_resume(self) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def build_result_extension(self) -> Mapping[str, OnlyJsonValue]:
        return {}
```

要求：

* Context 只允许绑定一次；
* 生命周期外访问 Context 抛出明确异常；
* Strategy 只能使用 Strategy Context；
* Strategy 不继承 OnlyCluster；
* Strategy 不能直接访问 Indicator Registry 的可变接口；
* Strategy 主要读取 Factor Snapshot。

---

# 9. Factor 抽象接口

定义：

```python
class OnlyFactor(ABC):
    def __init__(self, config: OnlyFactorConfig) -> None:
        ...

    @property
    def factor_id(self) -> OnlyFactorId:
        ...

    @property
    def factor_type(self) -> OnlyFactorType:
        ...

    @property
    def ready(self) -> bool:
        ...

    @property
    def context(self) -> OnlyFactorContext:
        ...

    @abstractmethod
    def on_initialize(self) -> None:
        ...

    @abstractmethod
    def snapshot(self) -> OnlyFactorSnapshot:
        ...

    @abstractmethod
    def score(self) -> OnlyFactorScore:
        ...

    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass
```

## 9.1 OnlyTimeSeriesFactor

```python
class OnlyTimeSeriesFactor(OnlyFactor):
    @abstractmethod
    def on_bar(self, context: OnlyFactorBarContext) -> None:
        ...
```

用途：

* 单资产时间序列；
* 单资产趋势；
* 动量；
* 波动率；
* 流动性；
* 均值回复。

## 9.2 OnlyCrossSectionFactor

```python
class OnlyCrossSectionFactor(OnlyFactor):
    @abstractmethod
    def on_cross_section(
        self,
        context: OnlyCrossSectionFactorContext,
    ) -> None:
        ...
```

用途：

* 多资产排名；
* 分位数；
* 标准化；
* 行业中性；
* 多因子评分；
* 截面选股。

---

# 10. Indicator 抽象接口

定义：

```python
OnlyIndicatorSnapshotT = TypeVar(
    "OnlyIndicatorSnapshotT",
    bound=OnlyIndicatorSnapshot,
)


class OnlyIndicator(
    ABC,
    Generic[OnlyIndicatorSnapshotT],
):
    @property
    @abstractmethod
    def indicator_id(self) -> OnlyIndicatorId:
        ...

    @property
    @abstractmethod
    def indicator_type(self) -> OnlyIndicatorTypeId:
        ...

    @property
    @abstractmethod
    def ready(self) -> bool:
        ...

    @property
    @abstractmethod
    def warmup_progress(self) -> OnlyWarmupProgress:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...

    @abstractmethod
    def snapshot(self) -> OnlyIndicatorSnapshotT:
        ...

    def canonical_score(self) -> OnlyIndicatorScore | None:
        return None
```

Bar 指标：

```python
class OnlyBarIndicator(
    OnlyIndicator[OnlyIndicatorSnapshotT],
    ABC,
):
    @abstractmethod
    def update_bar(self, bar: OnlyBar) -> None:
        ...
```

Indicator 必须保持：

* 强类型配置；
* 强类型 Snapshot；
* 确定性；
* 可 Reset；
* Warmup 明确；
* 不使用系统时间；
* 不使用裸 float 表示金融真值。

---

# 11. Indicator 标准库

在：

```text
src/onlyalpha/indicator/
```

建立标准指标实现。

第一阶段至少整理或实现：

```text
MACD
RSI
EMA
SMA
ATR
Bollinger Bands
Rolling Return
Rolling Volatility
Rolling Z-Score
```

每个指标均应包含：

```text
indicator.py
config.py
snapshot.py
factory.py
```

统一要求：

* Config 中提供默认参数；
* Config 自己完成参数校验；
* Factory 不写死默认值；
* Snapshot 提供专有结果；
* 可选 `canonical_score()` 提供标准评分；
* 默认参数可直接创建；
* 特殊参数可覆盖默认值。

---

# 12. Indicator Snapshot 和专有输出

每个指标通过统一：

```python
snapshot()
```

提供专有结果。

例如 MACD：

```python
@dataclass(frozen=True, slots=True)
class OnlyMacdSnapshot(OnlyIndicatorSnapshot):
    dif: Decimal
    dea: Decimal
    histogram: Decimal
    cross_state: OnlyMacdCrossState
    ready: bool
```

RSI：

```python
@dataclass(frozen=True, slots=True)
class OnlyRsiSnapshot(OnlyIndicatorSnapshot):
    value: Decimal
    zone: OnlyRsiZone
    ready: bool
```

ATR：

```python
@dataclass(frozen=True, slots=True)
class OnlyAtrSnapshot(OnlyIndicatorSnapshot):
    atr: Decimal
    normalized_atr: Decimal | None
    ready: bool
```

禁止给每个指标增加大量任意方法：

```text
get_dif()
get_dea()
get_histogram()
get_rsi()
get_atr()
```

统一通过：

```text
snapshot()
canonical_score()
```

获取结果。

---

# 13. Indicator 统一评分

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyIndicatorScore:
    indicator_id: OnlyIndicatorId
    dimension: OnlyIndicatorScoreDimension
    value: Decimal
    confidence: Decimal
    ready: bool
    ts_event: OnlyTimestamp | None
    quality_flags: frozenset[OnlyIndicatorQualityFlag]
```

建议评分数值范围：

```text
[-1, 1]
```

但必须保留 Dimension。

例如：

```text
MACD
    dimension = MOMENTUM
    value = +0.7

RSI
    dimension = POSITION
    value = +0.8

ATR
    dimension = VOLATILITY
    value = +0.6
```

不得将 ATR 的正评分解释为“看涨”。

建议 Dimension：

```text
DIRECTION
MOMENTUM
POSITION
VOLATILITY
LIQUIDITY
RISK
QUALITY
CUSTOM
```

`canonical_score()` 是可选的。

Indicator 原始 Snapshot 才是权威计算结果。

Factor 决定如何解释和组合 Indicator Score。

---

# 14. Factor Score

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyFactorScore:
    factor_id: OnlyFactorId
    value: Decimal
    dimension: OnlyFactorScoreDimension
    confidence: Decimal
    ready: bool
    ts_event: OnlyTimestamp | None
    quality_flags: frozenset[OnlyFactorQualityFlag]
```

Factor 的最终评分才是 Strategy 主要消费的评分。

层级必须是：

```text
Indicator Snapshot
→ 可选 Indicator Canonical Score
→ Factor Snapshot
→ Factor Score
→ Strategy
```

---

# 15. Indicator Factory Registry

实现：

```text
OnlyIndicatorFactory
OnlyIndicatorFactoryRegistry
OnlyIndicatorCreateRequest
OnlyIndicatorRegistrationResult
```

创建请求：

```python
@dataclass(frozen=True, slots=True)
class OnlyIndicatorCreateRequest:
    indicator_type: OnlyIndicatorTypeId
    indicator_id: OnlyIndicatorId
    parameters: Mapping[str, OnlyJsonValue]
```

Factory：

```python
class OnlyIndicatorFactory(Protocol):
    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        ...

    def create(
        self,
        request: OnlyIndicatorCreateRequest,
    ) -> OnlyIndicator:
        ...
```

Registry：

```python
class OnlyIndicatorFactoryRegistry:
    def register(self, factory: OnlyIndicatorFactory) -> None:
        ...

    def create(
        self,
        request: OnlyIndicatorCreateRequest,
    ) -> OnlyIndicator:
        ...
```

必须支持：

```python
create(
    indicator_type="MACD",
    parameters={},
)
```

使用默认参数。

也必须支持：

```python
create(
    indicator_type="MACD",
    parameters={
        "fast_period": 6,
        "slow_period": 13,
        "signal_period": 5,
    },
)
```

使用特殊参数。

---

# 16. Indicator Type ID

不要只使用固定 Enum 限制未来扩展。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyIndicatorTypeId:
    value: str
```

内置常量：

```text
MACD
RSI
EMA
SMA
ATR
BOLLINGER
ROLLING_RETURN
ROLLING_VOLATILITY
ZSCORE
```

第三方扩展可使用：

```text
vendor.custom.indicator
```

Registry Key 必须统一大小写和命名规范。

---

# 17. Factor 创建 Indicator

Factor 在 `on_initialize()` 中根据配置创建并注册 Indicator。

推荐：

```python
class OnlyTrendFactor(OnlyTimeSeriesFactor):
    def on_initialize(self) -> None:
        self._macd_id = self.context.indicators.create_for_bars(
            indicator_type=OnlyIndicatorTypeId("MACD"),
            indicator_id=OnlyIndicatorId(
                f"{self.factor_id}-macd"
            ),
            bar_type=self.config.bar_type,
            parameters=self.config.macd_parameters,
        )

        self._rsi_id = self.context.indicators.create_for_bars(
            indicator_type=OnlyIndicatorTypeId("RSI"),
            indicator_id=OnlyIndicatorId(
                f"{self.factor_id}-rsi"
            ),
            bar_type=self.config.bar_type,
            parameters=self.config.rsi_parameters,
        )
```

使用默认参数时：

```python
parameters={}
```

Factor 读取：

```python
macd_score = context.indicators.score(self._macd_id)

macd_snapshot = context.indicators.require_snapshot(
    self._macd_id,
    OnlyMacdSnapshot,
)
```

Runtime 不得从 YAML 直接创建具体 Indicator。

YAML 的指标配置由 Factor Config 解析，再由 Factor 初始化。

---

# 18. Indicator Scope

每个 Indicator 实例必须绑定：

```text
runtime_id
cluster_id
factor_id
indicator_id
```

建议定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyIndicatorInstanceKey:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    factor_id: OnlyFactorId
    indicator_id: OnlyIndicatorId
```

不同 Cluster 或 Factor 可以使用相同局部 Indicator ID，但完整 Key 必须唯一。

禁止不同 Cluster 共享同一个可变 Indicator 实例。

---

# 19. Factor Dependency Graph

实现：

```text
OnlyFactorDependencyGraph
OnlyFactorDependency
OnlyFactorExecutionPlan
```

必须验证：

* Factor ID 唯一；
* 依赖 Factor 存在；
* 无循环依赖；
* 时序因子和截面因子顺序合法；
* Required Factor 必须 READY；
* Strategy 引用的 Factor 必须存在；
* Factor 的 Indicator 必须注册成功。

推荐顺序：

```text
MarketData
→ Indicator
→ TimeSeries Factor
→ CrossSection Factor
→ Strategy
```

---

# 20. Cluster Pipeline

实现：

```text
OnlyClusterPipeline
OnlyClusterExecutionPlan
OnlyClusterCallbackContext
```

每个逻辑时间点固定流程：

```text
1. MarketData Pipeline 已完成
2. 更新匹配 BarType 的 Indicator
3. 检查 Indicator Warmup
4. 更新时序 Factor
5. 汇总同时间截面数据
6. 更新截面 Factor
7. 构建 Factor Snapshot Bundle
8. 检查 Required Factor Ready
9. 构建 Strategy Callback Context
10. 调用 Strategy
11. Strategy 通过 ctx.orders 下单
```

禁止依赖：

* EventBus 订阅顺序；
* Factor 注册顺序；
* dict 顺序；
* Strategy 自己更新 Indicator；
* Factor 临时拉取未来数据。

---

# 21. Context 分层

必须分开 Strategy Context、Factor Context 和 Indicator Context。

## 21.1 OnlyStrategyContext

允许：

```text
clock
market_data
factors
instruments
orders
positions
ledger
accounts
risk
logger
timers
```

不允许：

```text
factor_registry_mutation
indicator_registry_mutation
broker_gateway
event_bus
manager
data_source
runtime
```

Strategy 主要读取：

```python
ctx.factors.require(...)
ctx.factors.score(...)
```

## 21.2 OnlyFactorContext

允许：

```text
clock
market_data
indicators
dependent_factors
instruments
logger
```

不允许：

```text
orders
positions mutation
ledger mutation
accounts mutation
risk approval
broker
```

Factor 不能下单。

## 21.3 OnlyIndicatorContext

如果确实需要 Context，只允许：

```text
clock read-only
instrument read-only
logger
```

大多数 Indicator 应只接收明确输入，不直接访问完整 Context。

---

# 22. Cluster 生命周期

建议：

```text
CREATED
→ CONFIGURING
→ INITIALIZING_FACTORS
→ INITIALIZING_STRATEGY
→ WARMING_UP
→ READY
→ RUNNING
→ PAUSED
→ STOPPING
→ STOPPED
→ FAILED
```

初始化顺序：

```text
1. 创建 Cluster
2. 创建 Strategy
3. 创建 Factors
4. 构建 Factor Dependency Graph
5. 绑定 Factor Context
6. 调用 Factor.on_initialize()
7. Factor 注册 Indicator
8. 绑定 Strategy Context
9. 调用 Strategy.on_initialize()
10. 汇总数据订阅
11. Runtime 批准订阅
12. Warmup
13. Cluster READY
```

Strategy 只有在 Required Factor READY 后才接收正式交易回调。

---

# 23. Factory 分层

实现三个 Factory。

## 23.1 OnlyStrategyFactory

负责：

* 动态加载 Strategy Class；
* 动态加载 Strategy Config Class；
* 调用 Config `from_mapping()`；
* 创建 Strategy。

返回：

```text
OnlyStrategy
```

不创建 Factor，不创建 Indicator。

## 23.2 OnlyFactorFactory

负责：

* 动态加载 Factor Class；
* 动态加载 Factor Config Class；
* 调用 Config `from_mapping()`；
* 创建 TimeSeries 或 CrossSection Factor。

返回：

```text
OnlyFactor
```

不创建 Strategy。

具体 Indicator 在 Factor 生命周期中创建。

## 23.3 OnlyClusterFactory

负责：

* 解析 Cluster Common Config；
* 创建一个 Strategy；
* 创建多个 Factors；
* 验证 Factor Dependency；
* 将 Strategy 和 Factors 组装进 Cluster。

关系：

```text
OnlyClusterFactory
├── OnlyStrategyFactory
└── OnlyFactorFactory
```

---

# 24. 配置结构

配置必须改为 Cluster 主导。

推荐：

```yaml
clusters:
  - cluster_id: trend-cluster
    account_id: backtest-account
    enabled: true
    risk_profile_id: cn-equity-default

    strategy:
      class_path: examples.strategies.trend.strategy:OnlyTrendStrategy
      config_path: examples.strategies.trend.config:OnlyTrendStrategyConfig

      extensions:
        trend_factor_id: trend-factor
        liquidity_factor_id: liquidity-factor
        trade_quantity: "1000"

    factors:
      - factor_id: trend-factor
        factor_type: TIME_SERIES

        class_path: examples.factors.trend.factor:OnlyTrendFactor
        config_path: examples.factors.trend.config:OnlyTrendFactorConfig

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
          - indicator_id: trend-macd
            type: MACD

            parameters:
              fast_period: 12
              slow_period: 26
              signal_period: 9
              price_field: CLOSE

          - indicator_id: trend-rsi
            type: RSI

            parameters:
              period: 14
              price_field: CLOSE

        extensions:
          scoring:
            macd_weight: "0.65"
            rsi_weight: "0.35"

      - factor_id: liquidity-factor
        factor_type: TIME_SERIES

        class_path: examples.factors.liquidity.factor:OnlyLiquidityFactor
        config_path: examples.factors.liquidity.config:OnlyLiquidityFactorConfig

        indicators:
          - indicator_id: average-volume
            type: SMA

            parameters:
              period: 20
              price_field: VOLUME
```

---

# 25. YAML 中 Indicator 的语义

YAML 可以声明 Indicator，但 Runtime 不直接创建 Indicator。

正确流程：

```text
YAML Factor Indicator Specs
→ Factor Config.from_mapping()
→ Factor 实例
→ Factor.on_initialize()
→ ctx.indicators.create_for_bars()
→ Indicator Factory Registry
→ Concrete Indicator
```

禁止：

```text
YAML
→ Runtime Assembler
→ OnlyMacdIndicator()
```

---

# 26. MACD Demo 重构

原 MACD Demo 应拆成：

```text
OnlyMacdIndicator
    核心标准指标
    保留在 src/onlyalpha/indicator/macd/

OnlyMacdSignalFactor
    示例因子
    放在 examples/factors/macd_signal/

OnlyMacdStrategy
    示例策略
    放在 examples/strategies/macd/

OnlyMacdBacktestConfig
    示例运行配置
    放在 examples/configs/backtest/macd/
```

## 26.1 MACD Indicator

输出：

```text
dif
dea
histogram
cross_state
warmup
canonical momentum score
```

不得下单。

## 26.2 MACD Signal Factor

内部可以只使用一个 MACD Indicator，也符合：

```text
一个 Factor 使用一个或多个 Indicator
```

输出：

```text
signal
trend_score
confidence
macd_snapshot
factor_score
```

## 26.3 MACD Strategy

只读取 MACD Signal Factor：

```python
signal = ctx.factors.require(
    self.config.signal_factor_id,
    OnlyMacdSignalFactorSnapshot,
)
```

负责：

```text
GOLDEN_CROSS → 下单
DEATH_CROSS → 退出
```

Strategy 不创建或计算 MACD。

---

# 27. Backtest、Paper 和 Live 一致性

Cluster、Strategy、Factor 和 Indicator 必须在：

```text
BACKTEST
PAPER
LIVE
SHADOW
```

中使用相同抽象接口。

不同 Runtime 只改变：

```text
Clock
MarketData Source
Broker Gateway
Runtime Loop
Persistence/Recovery
```

不能为 Backtest 单独实现一套 Strategy/Factor 生命周期。

---

# 28. 结果模型

通用 Runtime Result 不得直接依赖具体 Strategy、Factor 或 Indicator 类型。

建议：

```text
OnlyClusterResult
├── strategy_result_extension
├── factor_results
└── indicator_diagnostics
```

策略、因子和指标专有结果通过：

```text
Mapping[str, OnlyJsonValue]
```

或正式扩展协议输出。

通用结果不应写死：

```text
golden_cross
death_cross
macd_trace
rsi_count
```

---

# 29. 需要删除或修改的现有设计

检查并移除：

```text
OnlyStrategyBuildResult.indicators
Strategy Factory 创建 Indicator
Runtime Assembly 注册具体 Indicator
Bar Subscription.indicator_ids
OnlyCluster 直接作为具体策略父类
OnlyMacdExampleCluster 存放在 src
OnlyMacdStrategyFactory 存放在 src
Strategy 直接读取 Indicator
Factor 可以调用 orders
Indicator 可以访问 RuntimeContext
```

需要迁移旧功能，但不得保留两套同时运行的策略模型。

---

# 30. 测试要求

新增：

```text
tests/indicator/
tests/factor/
tests/strategy/
tests/cluster/
tests/integration/
```

至少覆盖：

## 30.1 Indicator

```text
默认参数创建 MACD
特殊参数创建 MACD
默认参数创建 RSI
未知指标类型失败
重复 Factory 注册失败
指标 Warmup
指标 Reset
指标 Snapshot
Canonical Score
不同 Cluster Indicator 隔离
```

## 30.2 Factor

```text
Factor 创建一个 Indicator
Factor 创建多个 Indicator
Factor 使用默认参数
Factor 使用特殊参数
Factor Snapshot
Factor Score
Factor 无下单权限
Indicator 未 Ready 时 Factor 未 Ready
Factor 依赖检查
Factor 循环依赖失败
```

## 30.3 Strategy

```text
Strategy 读取 Factor
Strategy 不能访问 Indicator 可变接口
Strategy 通过 ctx.orders 下单
Strategy 不直接计算 MACD
Strategy 不直接访问 Manager
```

## 30.4 Cluster

```text
一个 Cluster 只能有一个 Strategy
一个 Cluster 可有多个 Factor
Cluster 初始化顺序
Indicator → Factor → Strategy 顺序
Required Factor 未 Ready 时不调用 Strategy
不同 Cluster 完全隔离
Cluster Pause
Cluster Stop
Cluster Failure
```

## 30.5 截面因子

```text
同一时点多 Instrument 汇总
Universe Snapshot
Point-in-Time Universe
稳定排序
缺失资产质量标记
截面排名确定性
```

---

# 31. 完整 MACD 回测场景

必须更新 Product-Style MACD Demo，完整链路：

```text
Run Config
→ Runtime Factory
→ Cluster Factory
→ Strategy Factory
→ Factor Factory
→ MACD Signal Factor
→ MACD Indicator Factory
→ Historical Data Source
→ Replay
→ MarketData Pipeline
→ MACD Indicator
→ MACD Signal Factor
→ MACD Strategy
→ Order
→ Risk
→ Virtual Broker
→ Execution Processor
→ Position
→ Allocation
→ Strategy Ledger
→ Account
→ Runtime Result
```

不得：

* Demo 直接创建 MACD Indicator；
* Runtime 创建 MACD Indicator；
* Strategy 计算 MACD；
* Factor 下单；
* 手工调用多个 Manager；
* 绕过正式 Factory 和 Context。

---

# 32. 确定性要求

相同：

```text
Config
Historical Data
Seed
Runtime
Cluster
Strategy
Factor
Indicator
Risk
Virtual Broker
```

至少重复运行 100 次。

比较：

```text
Indicator Snapshot 序列
Indicator Score 序列
Factor Snapshot 序列
Factor Score 序列
Strategy 回调顺序
Order
Trade
Position
Allocation
Ledger
Account
Event Sequence
Final Result
```

必须完全一致。

---

# 33. 文档

创建或更新：

```text
docs/cluster.md
docs/strategy.md
docs/factor.md
docs/indicator.md
docs/indicator_registry.md
docs/factor_pipeline.md
docs/cluster_lifecycle.md
docs/runtime_context.md
docs/backtest.md
docs/integration_vertical_slice.md
docs/architecture_principles.md
examples/strategies/macd/README.md
examples/factors/macd_signal/README.md
```

必须明确：

```text
Cluster 不是 Strategy

Cluster 持有一个 Strategy 和多个 Factor

Factor 持有或使用一个或多个 Indicator

Indicator 是最底层计算单元

Strategy 读取 Factor，而不是直接维护通用指标

Factor 不允许下单

MACD Indicator 属于核心标准指标库

MACD Factor 和 MACD Strategy 属于 examples
```

---

# 34. ADR

创建：

```text
docs/adr/0018-cluster-strategy-factor-indicator-model.md
```

至少记录：

## 背景

当前实现中 Cluster、Strategy、Indicator 的职责混合，Strategy Factory 创建 Indicator，无法表达一个 Cluster 内一个 Strategy 和多个 Factor 的目标架构。

## 决策

* Engine 管理多个 Cluster；
* Cluster 持有一个 Strategy 和多个 Factor；
* Factor 使用一个或多个 Indicator；
* Strategy 读取 Factor；
* Indicator 提供 Snapshot 和可选 Canonical Score；
* Factor 提供 Factor Snapshot 和 Factor Score；
* Factor 在初始化阶段创建 Indicator；
* Runtime 只托管 Indicator；
* MACD 等通用指标保留在核心库；
* MACD Factor 和 Strategy 迁移至 Examples；
* 时序因子与截面因子分开建模。

## 拒绝方案

* Cluster 直接等于 Strategy；
* Strategy Factory 创建 Indicator；
* Strategy 直接管理所有通用 Indicator；
* Factor 直接下单；
* Runtime 按 YAML 创建具体 Indicator；
* 每个指标提供不统一的任意 getter；
* MACD 示例策略留在核心 src。

---

# 35. Architecture Principles 新增规则

加入：

```text
Rule: OnlyEngine 管理多个相互隔离的 OnlyCluster。

Rule: 一个 OnlyCluster 只能持有一个 OnlyStrategy。

Rule: 一个 OnlyCluster 可以持有多个 OnlyFactor。

Rule: 一个 OnlyFactor 可以使用一个或多个 OnlyIndicator。

Rule: OnlyStrategy 主要读取 Factor Snapshot，不主持通用 Indicator。

Rule: OnlyFactor 不得提交订单或修改交易状态。

Rule: OnlyIndicator 是最底层无交易副作用计算单元。

Rule: Indicator 的专有结果必须通过强类型 Snapshot 输出。

Rule: Indicator 可选提供带 Dimension 的 Canonical Score。

Rule: Factor 输出 Factor Snapshot 和 Factor Score。

Rule: Indicator 实例必须按 Runtime、Cluster、Factor 和 Indicator Scope 隔离。

Rule: Factor 在 on_initialize 中通过 Indicator Factory Registry 创建指标。

Rule: Runtime 不得识别 MACD、RSI 等具体指标。

Rule: 通用指标实现可以放在 src/onlyalpha/indicator。

Rule: 示例 Factor 和 Strategy 必须放在 examples。

Rule: MarketData → Indicator → Factor → Strategy → Order 的顺序必须固定。
```

---

# 36. 实现顺序

严格按以下顺序：

1. 读取当前最新仓库；
2. 创建策略体系差距分析；
3. 明确 Engine、Cluster、Strategy、Factor、Indicator 边界；
4. 新增 Strategy 抽象基类；
5. 将 Cluster 改为容器；
6. 新增 Factor 抽象体系；
7. 新增 TimeSeries Factor；
8. 新增 CrossSection Factor；
9. 重构 Indicator 抽象接口；
10. 增加 Indicator Snapshot 和 Score；
11. 增加 Indicator Factory Registry；
12. 整理 MACD、RSI 等标准指标目录；
13. 增加 Factor Context；
14. 增加 Strategy Context；
15. 增加 Factor Registry；
16. 增加 Factor Dependency Graph；
17. 增加 Cluster Pipeline；
18. 增加 Cluster Factory；
19. 重构 Strategy Factory；
20. 增加 Factor Factory；
21. 修改 YAML/JSON Cluster 配置；
22. 迁移 MACD Factor 到 examples；
23. 迁移 MACD Strategy 到 examples；
24. 删除 StrategyBuildResult.indicators；
25. 删除 Runtime 具体指标注册；
26. 删除 Bar Subscription.indicator_ids；
27. 更新 Backtest 装配；
28. 更新 Product-Style Demo；
29. 增加单元测试；
30. 增加完整集成测试；
31. 运行历史 Vertical Slice；
32. 运行 100 次确定性重放；
33. 更新文档；
34. 创建 ADR；
35. 生成最终报告。

---

# 37. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

```text
OnlyCluster 仍然直接作为具体策略实现

一个 Cluster 可以直接包含多个独立 Strategy

Strategy Factory 仍然创建 Indicator

OnlyStrategyBuildResult 仍返回 indicators

Runtime 或 Assembly 仍实例化 MACD/RSI

Bar Subscription 仍携带 indicator_ids

Strategy 直接维护通用 MACD/RSI 指标

Factor 可以调用 ctx.orders

Factor 可以修改 Position、Ledger 或 Account

Indicator 可以访问 Broker 或 Manager

Indicator 专有结果通过大量任意 getter 输出

不同 Cluster 共享可变 Indicator 实例

Factor Dependency Graph 不检查循环

Required Factor 未 Ready 时仍调用 Strategy

MACD Strategy 或 MACD Factor 仍留在 src/onlyalpha

MACD Indicator 被错误迁移出核心指标库

Demo 绕过 Factory、Context 或正式 Runtime

历史 Vertical Slice 失败

确定性重放不一致

旧测试被删除、Skip 或放宽
```

---

# 38. 最终报告

生成：

```text
docs/reports/cluster_strategy_factor_indicator_refactor_report.md
```

至少包含：

```text
修改前架构
修改后架构
Engine 与 Cluster
Cluster 与 Strategy
Cluster 与 Factor
Factor 与 Indicator
Strategy 抽象接口
Factor 抽象接口
Indicator 抽象接口
TimeSeries Factor
CrossSection Factor
Indicator Snapshot
Indicator Canonical Score
Factor Snapshot
Factor Score
Indicator Factory Registry
默认参数
特殊参数
Indicator Scope
Factor Dependency Graph
Cluster Pipeline
Context 权限
目录重构
MACD Indicator 结果
MACD Factor 迁移
MACD Strategy 迁移
配置结构
动态加载
新增测试
完整 MACD 回测
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

# 39. Codex 启动指令

```text
严格执行 Cluster、Strategy、Factor 和 Indicator 架构重构。

最终架构必须是：

OnlyEngine 管理多个相互隔离的 OnlyCluster；
每个 OnlyCluster 持有且只持有一个 OnlyStrategy；
每个 OnlyCluster 持有多个 OnlyFactor；
每个 OnlyFactor 内部使用一个或多个 OnlyIndicator。

OnlyIndicator 是最底层计算单元，提供统一生命周期、Warmup、强类型 Snapshot 和可选带 Dimension 的 Canonical Score。MACD、RSI、EMA、SMA、ATR 等标准指标实现保留在 src/onlyalpha/indicator，并通过 OnlyIndicatorFactoryRegistry 根据名称和参数创建。默认参数由具体 Indicator Config 定义，特殊参数由 Factor Config 传入。

OnlyFactor 分为 OnlyTimeSeriesFactor 和 OnlyCrossSectionFactor。Factor 在 on_initialize 中通过 Factor Context 创建和注册 Indicator，读取 Indicator Snapshot 或 Canonical Score，输出 Factor Snapshot 和 Factor Score。Factor 不得下单、修改仓位、账本或账户。

OnlyStrategy 只读取 Factor Snapshot 和 Factor Score，并通过 Strategy Context 下单。Strategy 不得主持通用 Indicator。OnlyCluster 负责 Indicator → Factor → Strategy 的固定调度、依赖图、Warmup、Context、生命周期和隔离。

重构配置，使 Cluster 下分别声明一个 Strategy 和多个 Factors。Factor 配置可以包含一个或多个 Indicator Spec。YAML 中的 Indicator Spec 必须由 Factor Config 解析，并由 Factor 在初始化阶段通过 Indicator Factory Registry 创建；Runtime 和 Assembly 不得直接实例化具体 Indicator。

将当前 MACD 业务示例拆分为：
- 核心 OnlyMacdIndicator，保留在 src/onlyalpha/indicator/macd；
- OnlyMacdSignalFactor，迁移到 examples/factors/macd_signal；
- OnlyMacdStrategy，迁移到 examples/strategies/macd。

删除当前 Strategy Factory 创建 Indicator、OnlyStrategyBuildResult.indicators、Bar Subscription.indicator_ids 和 Runtime 具体指标注册流程。

完整回测链必须经过：

Config
→ Runtime
→ Cluster Factory
→ Strategy Factory
→ Factor Factory
→ Factor 创建 MACD Indicator
→ MarketData
→ Indicator
→ Factor
→ Strategy
→ Order
→ Risk
→ Virtual Broker
→ Execution Processor
→ Position
→ Allocation
→ Ledger
→ Account
→ Result。

运行全部历史测试、完整 Vertical Slice 和至少 100 次确定性重放。若 Cluster 仍等于 Strategy、Strategy Factory 仍创建指标、Factor 可以下单、Runtime 识别具体指标、示例策略仍位于 src 或重放结果不一致，最终结论必须为 REJECTED。
```
