# OnlyAlpha Agent 执行规范

## 1. 项目身份

本项目名称为 **OnlyAlpha**。

OnlyAlpha 是个人量化交易系统 **MyQuant** 的重构版本。MyQuant 位于：

```text
https://github.com/zongxin1993/MyQuant
```

MyQuant 已具备实盘交易与历史回测能力，但工程结构、模块边界、代码复用、回测与实盘一致性、资产模型、缓存、投研和 Web 扩展能力需要系统性重构。

OnlyAlpha 不是对 MyQuant 的简单复制、改名或目录重排，而是对其有效能力进行识别、抽象、重建和验证。

---

## 2. 必读文档

执行任何任务前，必须先阅读与任务相关的文档。

| 修改范围 | 必读文档 |
|---|---|
| 总体架构 | `docs/architecture.md` |
| MyQuant 分析与迁移 | `docs/migration.md` |
| Engine | `docs/engine.md` |
| Runtime / 回测 / 实盘 | `docs/runtime.md` |
| Cluster / 策略插件 | `docs/cluster.md` |
| Event Bus | `docs/event.md` |
| 资产、价格、金额、合约 | `docs/instrument_model.md` |
| NautilusTrader 借鉴 | `docs/nautilus_research.md` |
| Gateway | `docs/gateway.md` |
| Cache / Storage | `docs/storage.md` |
| 投研、因子、统计、绘图 | `docs/research.md` |
| Web/API | `docs/web_api.md` |
| 并发 | `docs/concurrency.md` |
| 编码规范 | `docs/coding_style.md` |
| 测试 | `docs/testing.md` |
| 路线图 | `docs/roadmap.md` |
| 架构决策 | `docs/adr/` |

若文档与代码冲突，应先确认当前行为，再修正文档或代码。不得让二者长期不一致。

---

## 3. 核心目标

OnlyAlpha 必须实现：

1. 一个统一的 `OnlyEngine`；
2. 一个 Engine 可同时管理多个 Runtime；
3. 同一 Engine 可同时运行实盘、模拟盘、回测和投研任务；
4. 一个 Runtime 可加载多个相互隔离的 Cluster；
5. 一个 Cluster 代表一个独立策略运行单元；
6. Cluster 支持静态注册和动态加载；
7. Cluster 中要预留好时序因子和截面因子的接口；
8. 一个 Cluster 中可以有多个不同的因子;
9. Cluster 中要预留好AI 模型及机器学习模型接口;
10. 回测与实盘尽量共用同一策略接口、领域模型和事件模型；
11. 交易、行情、风控、缓存、存储、投研和 Web API 相互解耦；
12. 第一阶段支持中国 A 股；
13. 架构从第一天起预留期货、港股、美股、外汇、期权和数字资产能力；
14. 核心交易数值必须具备明确精度和约束；
15. 关键行为必须可测试、可观测、可恢复。

---

## 4. 强制命名规则

OnlyAlpha 自定义的以下类型必须以 `Only` 开头：

- 类；
- 抽象类；
- 数据类；
- 结构体；
- 枚举；
- 协议；
- 事件；
- 配置类型；
- 异常类型；
- 标识符值对象。

示例：

```python
class OnlyEngine:
    pass

class OnlyCluster:
    pass

@dataclass(frozen=True)
class OnlyPrice:
    pass

class OnlyOrderStatus(Enum):
    pass

class OnlyEngineError(Exception):
    pass
```

禁止：

```python
class Engine:
    pass

class Cluster:
    pass
```

第三方库类型不受此约束。

方法与变量使用 `snake_case`，常量使用 `UPPER_SNAKE_CASE`。

---

## 5. 重构原则

### 5.1 先分析后实现

修改关键模块前，应先查阅 MyQuant 对应实现，至少确认：

- 实盘入口；
- 回测入口；
- 策略生命周期；
- 行情流；
- 订单流；
- 成交流；
- 账户和持仓状态；
- 缓存与数据库；
- 配置系统；
- 统计和绘图；
- 并发模型；
- 外部 SDK 行为。

不得在未理解旧行为时直接重写关键交易逻辑。

### 5.2 不修改 MyQuant

除非用户明确要求：

- 不修改 `https://github.com/zongxin1993/MyQuant`；
- 不删除或覆盖 MyQuant 文件；
- 不启动真实交易；
- 不使用真实账户做验证；
- 只将 MyQuant 作为分析、回归和迁移来源。

### 5.3 渐进式迁移

每次只完成一个边界清晰、可验证的任务。

每个阶段必须：

- 可运行；
- 可测试；
- 有明确输入输出；
- 有失败处理；
- 有文档；
- 不让主分支持续处于整体不可运行状态。

### 5.4 不大规模复制旧代码

复用旧代码前必须说明：

- 为什么复用；
- 依赖哪些旧行为；
- 如何封装；
- 如何测试；
- 未来是否替换。

---

## 6. 架构边界

推荐依赖方向：

```text
domain
  ↑
core
  ↑
event / cache / storage interfaces
  ↑
engine / runtime / cluster
  ↑
backtest / live / gateway / research
  ↑
application services
  ↑
web api / cli
```

强制规则：

- Domain 不依赖 Web、数据库、券商 SDK 或绘图库；
- Cluster 不直接依赖具体 Gateway；
- Cluster 不直接访问数据库；
- Web 不直接操作 Engine 内部对象；
- Engine 不实现具体策略；
- Engine 不实现具体券商 SDK；
- 图表层不访问交易网关；
- Cache 与 Storage 必须分离；
- 统计计算与绘图必须分离；
- 外部数据必须先标准化为 OnlyAlpha 领域对象。

---

## 7. Engine、Runtime、Cluster

### 7.1 Engine

`OnlyEngine` 是顶层协调者，不得成为上帝类。

负责：

- 生命周期；
- Runtime 管理；
- Cluster 管理；
- Event Bus 管理；
- Gateway 管理；
- Cache/Storage 管理；
- Application Service；
- 状态汇总；
- 优雅关闭；
- 系统级异常处理。

不负责：

- 策略逻辑；
- 具体撮合；
- 具体券商 API；
- 具体数据库 SQL；
- 具体因子公式；
- 具体图表实现。

### 7.2 Runtime

必须至少预留：

```text
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
```

不同 Runtime 必须隔离：

- 时钟；
- 账户；
- 持仓；
- 订单空间；
- 事件流；
- 缓存命名空间；
- 日志上下文；
- 统计结果。

### 7.3 Cluster

Cluster 是策略运行单元，默认相互隔离。

必须：

- 有唯一 `cluster_id`；
- 有独立配置；
- 有独立缓存命名空间；
- 有独立日志上下文；
- 不直接访问其他 Cluster 内部状态；
- 不共享可变全局变量；
- 异常不应直接导致其他 Cluster 停止；
- 单个 Cluster 内事件默认串行处理。

---

## 8. 资产模型强制要求

必须研究 NautilusTrader 对以下概念的实现思想：

- Price；
- Quantity；
- Money；
- Currency；
- Instrument；
- Equity；
- Future；
- Option；
- FX；
- Crypto Spot；
- Crypto Future；
- Crypto Perpetual；
- price precision；
- quantity precision；
- tick size；
- step size；
- contract multiplier；
- base / quote / settlement currency；
- linear / inverse / quanto；
- 强类型标识符；
- 不可变值对象；
- 定点数语义。

OnlyAlpha 不直接复制 NautilusTrader 源码，但应借鉴其领域约束思想。

核心交易逻辑禁止无约束使用 `float` 表示：

- 价格；
- 数量；
- 金额；
- 盈亏；
- 手续费；
- 保证金。

至少定义：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyInstrument
OnlyEquity
OnlyETF
OnlyFuture
OnlyOption
OnlyFxPair
OnlyCryptoSpot
OnlyCryptoFuture
OnlyCryptoPerpetual
OnlyAccountEquity
```

必须区分：

- 价格精度与最小价格变动；
- 数量精度与最小数量变动；
- 报价币种与结算币种；
- 股票类型 `OnlyEquity` 与账户权益 `OnlyAccountEquity`。

A 股规则不能写死在通用 Engine 或通用 Instrument 中。

---

## 9. 时间与事件

策略不得大量直接调用：

```python
datetime.now()
time.time()
```

必须通过：

```text
OnlyClock
OnlyLiveClock
OnlyBacktestClock
```

获取时间。

事件应统一建模，至少包含：

```text
event_id
event_type
timestamp
engine_id
runtime_id
cluster_id
source
sequence
payload
metadata
```

Event Bus 必须考虑：

- 顺序；
- 背压；
- 有界队列；
- 异常隔离；
- 关闭；
- 事件追踪；
- 性能统计。

---

## 10. Cache 与 Storage

Cache 用于加速，Storage 用于可靠保存。

禁止将二者混为同一接口。

缓存键至少考虑：

```text
engine_id
runtime_id
cluster_id
data_type
instrument_id
frequency
date_range
version
```

初始实现建议：

```text
OnlyMemoryCache
OnlySqliteStorage
```

后续可扩展：

```text
OnlyFileCache
OnlySqliteCache
OnlyRedisCache
OnlyPostgresStorage
```

---

## 11. Web 与远程调用

Web 层只能调用 Application Service，例如：

```text
OnlyEngineService
OnlyClusterService
OnlyBacktestService
OnlyResearchService
OnlyQueryService
```

Web 层不得：

- 直接提交 Gateway 订单；
- 直接修改 Cluster 状态；
- 直接操作数据库；
- 直接控制线程；
- 包含策略和撮合逻辑。

---

## 12. 测试要求

新增或修改功能必须同步增加测试。

至少包括：

- 单元测试；
- 集成测试；
- 回归测试；
- 生命周期测试；
- 资产精度测试；
- 订单状态测试；
- 缓存恢复测试；
- 多 Runtime 隔离测试；
- 多 Cluster 异常隔离测试。

关键交易行为必须使用固定输入、固定时钟和确定结果。

---

## 13. 代码质量要求

所有新增代码必须：

- 有完整类型标注；
- 有必要的文档字符串；
- 避免循环依赖；
- 避免超大类；
- 避免超长函数；
- 避免全局可变状态；
- 避免魔法字符串；
- 避免无含义字典；
- 通过格式化、静态检查和测试；
- 保持公共接口稳定。

Python 默认建议：

```text
ruff
mypy
pytest
```

不得为了让测试通过而降低测试有效性。

---

## 14. Codex 工作流程

每个任务按以下顺序执行：

1. 阅读相关文档；
2. 阅读相关代码；
3. 必要时分析 MyQuant 对应实现；
4. 明确变更边界；
5. 实现最小完整改动；
6. 增加或更新测试；
7. 运行相关测试；
8. 运行静态检查；
9. 更新文档；
10. 总结修改文件、测试结果、未完成内容和风险。

---

## 15. 禁止事项

未经明确要求，禁止：

- 修改 MyQuant；
- 启动真实交易；
- 使用真实账户下单；
- 删除不理解的旧逻辑；
- 直接复制大量 NautilusTrader 代码；
- 在核心交易逻辑中使用无约束 `float`；
- 在 Cluster 中直接调用券商 SDK；
- 在 Web 层直接操作 Engine 内部对象；
- 使用无限队列；
- 吞掉异常；
- 硬编码密码、Token、账户和密钥；
- 在持有锁时调用外部接口；
- 为追求“高性能”过早引入复杂分布式组件；
- 未经 ADR 记录进行重大架构改动。

---

## 16. ADR 要求

以下修改必须新增或更新 ADR：

- Engine/Runtime/Cluster 关系；
- 事件模型；
- 并发模型；
- 资产值对象；
- Instrument 层次；
- Cache/Storage 选择；
- 动态插件机制；
- Web 调用模型；
- 数据库或消息中间件引入；
- 影响公共接口的重大变更。

ADR 文件放在：

```text
docs/adr/
```

状态使用：

```text
Proposed
Accepted
Deprecated
Superseded
```

---

## 17. 初始化执行顺序

首次初始化必须按顺序执行：

### 阶段一：分析 MyQuant

输出：

```text
docs/myquant_analysis.md
```

### 阶段二：研究 NautilusTrader 资产模型

输出：

```text
docs/nautilus_research.md
docs/instrument_model.md
```

### 阶段三：完成架构设计

输出：

```text
docs/architecture.md
docs/engine.md
docs/runtime.md
docs/cluster.md
docs/event.md
docs/storage.md
docs/concurrency.md
docs/migration.md
```

### 阶段四：创建最小骨架

至少实现：

```text
OnlyEngine
OnlyRuntime
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
OnlyCluster
OnlyClusterRegistry
OnlyClusterLoader
OnlyEventBus
OnlyClock
OnlyCache
OnlyStorage
OnlyDemoCluster
```

### 阶段五：建立测试

覆盖：

- Engine 启停；
- 多 Runtime；
- 多 Cluster；
- 静态加载；
- 动态加载；
- 生命周期；
- 事件投递；
- 异常隔离；
- Cache；
- Storage；
- 资产值对象。

完成以上阶段后，才迁移真实策略和真实交易功能。

---

## 18. 最终原则

```text
策略与运行环境分离
回测与实盘接口统一
Cluster 默认隔离
Runtime 默认隔离
领域模型统一
金融数值强类型化
缓存与存储分离
统计与绘图分离
Web 与 Engine 分离
外部 SDK 与策略分离
系统状态有唯一可信来源
所有生命周期可观测、可测试、可恢复
新增市场不修改 Engine 核心
新增策略不修改 Runtime 核心
```
