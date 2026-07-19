你现在负责实现 OnlyAlpha 的“MiniQMT 真实历史数据缓存与真实回测纵切面”。

当前 Workspace 包含三个独立仓库：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
```

本任务需要同时修改三个仓库，但必须严格维持三仓职责：

```text
OnlyAlpha
    核心框架、公共接口、通用历史数据缓存能力、时间语义、
    Parquet Cache Store、数据验证、Historical Replay 和回测运行时

OnlyAlpha-plugins
    MiniQMT 供应商适配、xtquant 数据读取、供应商字段映射、
    MiniQMT 时间戳解释、原始数据验证和标准 HistoricalDataProvider

OnlyAlpha-examples
    MiniQMT 真实历史数据回测示例、配置、运行说明和结果验证说明
```

本任务不是实现完整 A 股交易规则，也不是实现 MiniQMT 实盘交易。

本任务的核心目标是：

> 通过 OnlyAlpha 提供的标准历史数据缓存接口，让 MiniQMT 插件获取真实历史数据、完成时间标准化和数据验证，将标准化结果缓存为 Parquet，并由 OnlyAlpha-examples 通过正式产品链运行一个可重复、可离线重放的真实历史数据回测示例。

---

# 一、最终产品链

最终必须形成以下正式链路：

```text
OnlyAlpha-examples YAML 配置
    ↓
OnlyAlpha CLI
    ↓
OnlyEngine
    ↓
OnlyRuntimePlanner
    ↓
OnlyRuntimeSession
    ↓
MiniQMT DataSource Plugin
    ↓
OnlyHistoricalCacheService
    ├── 检查 Parquet Cache
    ├── 检查 Schema、Manifest 和 Coverage
    ├── 计算缺失时间范围
    ├── 调用 MiniQMT HistoricalDataProvider 下载缺口
    ├── 验证并标准化数据
    ├── 原子写入 Parquet Cache
    └── 从 Cache 读取完整请求范围
    ↓
Historical Replay
    ↓
MarketData Pipeline
    ↓
Factor / Strategy
    ↓
Risk / Order
    ↓
Virtual Broker
    ↓
ExecutionProcessor
    ↓
Position / Allocation / Ledger / Account
    ↓
user_data/runs/<run-id>/
```

关键不变量：

```text
下载只负责填充缓存；
回测始终从校验后的 Parquet 缓存读取。
```

第一次和第二次回测必须使用相同的缓存读取路径。

---

# 二、开始前必须完成的检查

在修改前完整阅读三个仓库中的：

```text
OnlyAlpha/AGENTS.md
OnlyAlpha/README.md
OnlyAlpha/pyproject.toml
OnlyAlpha/docs/architecture.md
OnlyAlpha/docs/runtime.md
OnlyAlpha/docs/plugin_system.md
OnlyAlpha/docs/data_source_plugin.md
OnlyAlpha/docs/workspace_structure.md
OnlyAlpha/docs/testing.md

OnlyAlpha-plugins/AGENTS.md
OnlyAlpha-plugins/README.md
OnlyAlpha-plugins/pyproject.toml
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/pyproject.toml
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/src/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/tests/
OnlyAlpha-plugins/docs/reports/miniqmt_plugin_implementation_report.md
OnlyAlpha-plugins/docs/reports/miniqmt_open_market_verification.md

OnlyAlpha-examples/AGENTS.md
OnlyAlpha-examples/README.md
OnlyAlpha-examples/pyproject.toml
OnlyAlpha-examples/examples/
```

重点检查现有定义和引用：

```text
OnlyDataSourceCreateRequest
OnlyHistoricalDataSource
OnlyHistoricalDataRequest
OnlyHistoricalDataResult
OnlyHistoricalReplay
OnlyBar
OnlyBarType
OnlyInstrumentId
OnlyTradingCalendar
OnlyTradingDay
OnlyUserDataLayout
OnlyRuntimeContext
OnlyClusterRunConfig
OnlyPluginDescriptor
MiniQmtHistoricalDataSource
MiniQmtDataSourceFactory
MiniQmtConfig
xtdata.get_market_data
xtdata.get_market_data_ex
user_data
cache
Parquet
pyarrow
```

修改前先输出简短分析：

1. 当前 MiniQMT Historical Source 的调用链；
2. 当前历史数据接口是否支持传递缓存服务；
3. 当前 `user_data` 目录如何创建和传入 Runtime；
4. 当前 Bar 时间字段及其语义；
5. 当前 MiniQMT 日线、分钟线时间戳如何映射；
6. 当前是否已有通用时间范围、数据验证或 Parquet 工具；
7. 当前真实 MiniQMT 集成测试如何启用；
8. OnlyAlpha-examples 当前正式运行方式。

不要在未确认现有接口的情况下重复创建同义模型。

---

# 三、任务范围

本任务必须完成以下内容：

```text
1. OnlyAlpha 核心历史数据缓存公共接口
2. 标准时间范围和 Coverage 算法
3. 标准缓存策略
4. 标准 Cache Key 和 Manifest
5. 通用历史 Bar 数据验证
6. 通用 Parquet Historical Cache Store
7. 原子写、文件锁和损坏缓存处理
8. 数据内容指纹
9. MiniQMT HistoricalDataProvider
10. MiniQMT 原始数据验证
11. MiniQMT 时间语义标准化
12. Cache 缺失范围自动下载
13. 回测统一从 Cache 读取
14. OnlyAlpha-examples 真实回测示例
15. 首次下载与第二次离线重放验证
16. 单元测试、集成测试和文档
```

本任务不包括：

```text
完整涨跌停规则
ST 每日状态
停牌 Reference Data
完整手续费模型
印花税和过户费
成交量参与率
复杂部分成交
MiniQMT 实盘下单
Paper Runtime 完整实现
Live Runtime 完整实现
Web
数据库
分布式缓存
Redis
DuckDB
通用对象缓存框架
```

---

# 四、OnlyAlpha 核心实现

## 4.1 模块边界

在 OnlyAlpha 中新增或完善历史数据缓存能力。

建议结构：

```text
src/onlyalpha/
├── cache/
│   └── historical/
│       ├── __init__.py
│       ├── api.py
│       ├── models.py
│       ├── policies.py
│       ├── coverage.py
│       ├── service.py
│       ├── validation.py
│       ├── fingerprint.py
│       ├── locking.py
│       └── parquet/
│           ├── __init__.py
│           ├── schema.py
│           ├── partition.py
│           └── store.py
└── time/
    ├── ranges.py
    └── semantics.py
```

具体目录必须结合现有结构调整。

不要为了符合建议结构而进行无关目录重构。

只实现：

```text
Historical Market Data Cache
```

不要创建：

```text
OnlyUniversalCache[T]
GenericObjectCache
ModelCache
OrderCache
AccountCache
```

---

## 4.2 标准时间范围

核心定义统一的 timezone-aware 半开区间：

```python
@dataclass(frozen=True, order=True)
class OnlyTimeRange:
    start: datetime
    end: datetime
```

语义：

```text
[start, end)
```

必须验证：

* `start` 和 `end` 都是 timezone-aware；
* 内部统一转为 UTC 或要求调用者传 UTC；
* `start < end`；
* 不接受 naive datetime。

提供通用操作：

```text
contains
overlaps
intersection
subtract
merge_ranges
missing_ranges
```

实现时保持纯函数、确定性和不可变。

必须覆盖以下情况：

```text
完全未缓存
完全覆盖
左侧缺口
右侧缺口
两侧缺口
中间缺口
重叠 Coverage
相邻 Coverage
重复 Coverage
空 Coverage
```

---

## 4.3 时间语义

核心定义标准 Bar 时间协议。

至少明确：

```text
OnlyAlpha 内部绝对时间：UTC
datetime：必须 timezone-aware
Bar event_time：标准事件时间
trading_day：市场交易日，不从 UTC 日期临时推断
查询范围：[start, end)
Replay：按 event_time 排序和推进
```

根据现有 Domain 模型复用或补充：

```python
class OnlyBarTimestampSemantics(Enum):
    BAR_OPEN = "bar_open"
    BAR_CLOSE = "bar_close"
```

标准化后的 Historical Bar 应至少能够表达：

```text
event_time_utc
trading_day
source_time
```

不要破坏现有 `OnlyBar` 公共构造方式。

如果现有 `OnlyBar` 不适合直接增加供应商审计字段，应通过缓存记录模型或 Metadata 保存，不要污染核心交易 Domain。

---

## 4.4 Cache Policy

核心定义：

```python
class OnlyCachePolicy(Enum):
    CACHE_ONLY = "cache_only"
    PREFER_CACHE = "prefer_cache"
    REFRESH_MISSING = "refresh_missing"
    FORCE_REFRESH = "force_refresh"
```

语义必须固定：

### CACHE_ONLY

```text
只允许读取已有有效缓存；
缓存不存在、损坏或覆盖不足时立即失败；
不得访问 MiniQMT。
```

### PREFER_CACHE

```text
缓存完整有效则直接读取；
缓存不完整时只下载缺口；
默认策略。
```

### REFRESH_MISSING

```text
显式检查 Coverage 并补齐缺失范围；
已有完整区间不重新下载。
```

`PREFER_CACHE` 和 `REFRESH_MISSING` 如果当前实现无法体现实质区别，可以只保留一个，避免同义枚举。

不要为了满足文字要求保留重复语义。

### FORCE_REFRESH

```text
重新下载请求范围；
验证成功后替换对应缓存范围；
原缓存写入成功前必须保持可用。
```

---

## 4.5 Historical Cache Key

核心定义通用缓存身份。

建议：

```python
@dataclass(frozen=True)
class OnlyHistoricalCacheKey:
    source_id: str
    dataset_type: str
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    adjustment: str
    schema_version: int
    time_semantics_version: int
```

缓存 Key 不得包含：

```text
绝对缓存路径
下载时间
ingest_time
临时文件名
当前进程 ID
```

MiniQMT 专属字段不能成为核心强类型字段。

供应商特有内容通过：

```text
metadata
```

保存。

---

## 4.6 Manifest

核心定义通用 Manifest，至少包括：

```python
@dataclass(frozen=True)
class OnlyCacheManifest:
    key: OnlyHistoricalCacheKey
    coverage: tuple[OnlyTimeRange, ...]
    row_count: int
    partition_hashes: Mapping[str, str]
    content_fingerprint: str
    schema_version: int
    time_semantics_version: int
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, JsonValue]
```

其中：

```text
created_at / updated_at
```

仅用于审计，不参与业务数据指纹。

MiniQMT Metadata 可以包括：

```text
vendor
vendor_symbol
plugin_version
xtquant_version
source_timestamp_semantics
source_timezone
adjustment
requested_fields
```

Manifest 必须有 Schema 版本。

读取未知新版本时必须明确失败，不得静默猜测。

---

## 4.7 Cache Inspection

核心定义缓存检查结果：

```python
@dataclass(frozen=True)
class OnlyCacheInspection:
    exists: bool
    valid: bool
    key: OnlyHistoricalCacheKey
    coverage: tuple[OnlyTimeRange, ...]
    missing_ranges: tuple[OnlyTimeRange, ...]
    manifest: OnlyCacheManifest | None
    issues: tuple[OnlyDataQualityIssue, ...]
```

“文件存在”不代表 Cache 命中。

有效命中必须满足：

```text
Key 兼容
Schema 兼容
time_semantics_version 兼容
Instrument 一致
Bar Type 一致
Adjustment 一致
Manifest 有效
Parquet 可读取
Hash 有效
Coverage 完整覆盖请求
```

---

## 4.8 Historical Data Provider 接口

核心定义供应商无关接口：

```python
class OnlyHistoricalDataProvider(Protocol):
    @property
    def descriptor(self) -> OnlyHistoricalProviderDescriptor:
        ...

    def build_cache_key(
        self,
        request: OnlyHistoricalDataRequest,
    ) -> OnlyHistoricalCacheKey:
        ...

    def fetch(
        self,
        request: OnlyHistoricalDataRequest,
        time_range: OnlyTimeRange,
    ) -> OnlyHistoricalFetchResult:
        ...
```

Fetch Result 至少包含：

```python
@dataclass(frozen=True)
class OnlyHistoricalFetchResult:
    records: tuple[OnlyBar, ...]
    actual_coverage: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, JsonValue]
```

注意：

```text
actual_coverage 不能直接等于 requested range。
```

无交易日、停牌、供应商数据缺失时，实际覆盖需要根据真实返回数据和交易时间语义计算。

---

## 4.9 Cache Store 接口

核心定义：

```python
class OnlyHistoricalCacheStore(Protocol):
    def inspect(
        self,
        key: OnlyHistoricalCacheKey,
        requested_range: OnlyTimeRange,
    ) -> OnlyCacheInspection:
        ...

    def read(
        self,
        key: OnlyHistoricalCacheKey,
        time_range: OnlyTimeRange,
    ) -> OnlyHistoricalDataResult:
        ...

    def write(
        self,
        key: OnlyHistoricalCacheKey,
        result: OnlyHistoricalFetchResult,
    ) -> OnlyCacheWriteResult:
        ...

    def invalidate(
        self,
        key: OnlyHistoricalCacheKey,
        time_range: OnlyTimeRange | None = None,
    ) -> None:
        ...
```

接口名称可以结合现有命名风格调整。

不要暴露 PyArrow 对象给 DataSource 插件。

---

## 4.10 Parquet Store

OnlyAlpha 内建：

```python
OnlyParquetHistoricalCacheStore
```

默认根目录：

```text
<user_data>/cache/market_data/
```

MiniQMT 分区建议：

```text
user_data/
└── cache/
    └── market_data/
        └── miniqmt/
            └── v1/
                ├── bars/
                │   └── <bar-type>/
                │       └── <venue>/
                │           └── <instrument>/
                │               └── <year>.parquet
                ├── manifests/
                ├── locks/
                └── quarantine/
```

分区策略应由核心通用实现基于 Cache Key 计算。

不能将 MiniQMT 类直接 import 到核心。

不要使用：

```text
一个股票一个无限增长的大文件
每个 Bar 一个文件
每个交易日一个小文件
```

第一版：

```text
日线按年分区
分钟线先按年或按月分区
```

如果统一按年会导致现有测试或分钟数据明显不可控，可实现可配置的通用分区策略：

```text
YEAR
MONTH
```

但不要为 MiniQMT 创建专属 Store 子类。

---

## 4.11 Parquet Schema

缓存保存标准化后的 OnlyAlpha 数据，而不是原始 MiniQMT DataFrame。

结合现有 Domain 类型定义稳定 Schema。

至少包含：

```text
schema_version
instrument_id
venue
symbol
bar_type
event_time_utc
trading_day
open
high
low
close
volume
turnover
currency
source_id
source_time_raw
source_sequence
adjustment
```

价格和数量必须避免普通浮点带来的不稳定。

优先使用：

```text
Domain raw integer + precision
```

或者：

```text
Arrow Decimal + 固定 scale
```

如果现有 Domain 已有稳定序列化格式，直接复用。

禁止因为实现方便将所有价格转换成 `float64`，除非现有 Domain 本身就是 float，并且有明确精度测试。

---

## 4.12 通用数据验证

OnlyAlpha 提供标准化 Historical Bar 验证。

至少验证：

```text
event_time timezone-aware
event_time 为 UTC
instrument_id 不为空
bar_type 一致
open > 0
high > 0
low > 0
close > 0
high >= open
high >= close
high >= low
low <= open
low <= close
volume >= 0
turnover >= 0（如存在）
同一 key 不重复
序列稳定排序
时间不倒退
```

定义结构化结果：

```python
@dataclass(frozen=True)
class OnlyDataQualityIssue:
    code: str
    severity: OnlyDataQualitySeverity
    message: str
    instrument_id: OnlyInstrumentId | None
    timestamp: datetime | None
    metadata: Mapping[str, JsonValue]
```

```python
@dataclass(frozen=True)
class OnlyDataQualityReport:
    valid: bool
    issues: tuple[OnlyDataQualityIssue, ...]
```

严格模式下：

```text
ERROR 阻止写入缓存和回测
WARNING 写入报告但允许继续
```

不能静默修改非法 OHLC 数据。

---

## 4.13 缓存服务

核心实现高层：

```python
OnlyHistoricalCacheService
```

它组合：

```text
Store
Coverage Calculator
Validator
Fingerprint Strategy
Lock Manager
```

调用示意：

```python
result = service.load(
    request=request,
    provider=provider,
    policy=OnlyCachePolicy.PREFER_CACHE,
)
```

内部流程必须是：

```text
1. Provider 构造 Cache Key
2. Store inspect
3. 校验 Manifest 和缓存内容
4. 计算 Missing Ranges
5. 根据 Policy 决定是否访问 Provider
6. 对每个缺口调用 Provider.fetch
7. 合并 Fetch Quality Report
8. 执行核心标准 Bar 验证
9. 原子写入 Cache
10. 重新 inspect
11. 从 Cache 读取完整请求范围
12. 再次执行稳定排序和边界过滤
13. 返回 Data Result、Manifest、Quality Report 和 Cache Statistics
```

必须保证：

```text
首次下载后也从 Parquet Cache 重新读取；
不能直接使用 fetch 返回的内存对象进入回测。
```

---

## 4.14 Cache Statistics

结果中增加可诊断信息：

```python
@dataclass(frozen=True)
class OnlyCacheStatistics:
    cache_hit: bool
    partitions_read: int
    partitions_written: int
    rows_read: int
    rows_fetched: int
    missing_ranges: tuple[OnlyTimeRange, ...]
    content_fingerprint: str
```

这些信息用于示例和诊断。

它们不得改变业务结果。

---

## 4.15 缓存指纹

定义确定性数据指纹：

```text
SHA-256(
    canonical cache key
    + canonical schema version
    + canonical time semantics version
    + sorted partition content hashes
    + canonical request parameters
)
```

不得包含：

```text
created_at
updated_at
下载时间
ingest_time
绝对路径
临时文件名
进程 ID
文件 inode
```

同一标准化数据重新下载后，内容指纹必须一致。

---

## 4.16 原子写

Parquet 更新必须使用：

```text
写临时文件
→ 关闭文件
→ 重新读取验证
→ 计算 Hash
→ 写临时 Manifest
→ 原子替换正式 Parquet
→ 原子替换 Manifest
```

任何步骤失败：

* 原缓存保持可用；
* 临时文件清理；
* 不留下半更新 Manifest；
* 不把失败数据作为有效 Coverage。

---

## 4.17 文件锁

实现跨进程或至少跨本机进程的缓存分区锁。

目标：

* 两个回测不能同时写同一分区；
* 读取不应无意义阻塞其他分区；
* 锁具有超时；
* 异常退出后的旧锁可以检测并恢复；
* 不依赖 Linux-only API，需兼顾 Windows。

优先使用成熟、轻量、跨平台依赖。

如果项目不希望新增依赖，可实现基于原子创建锁文件的最小方案，但必须有 PID、创建时间、超时和测试。

不要引入 Redis 或数据库。

---

## 4.18 损坏缓存与 quarantine

如果出现：

```text
Manifest 不存在
Manifest JSON 损坏
Parquet 无法读取
Schema 不兼容
Hash 不一致
数据验证失败
```

不能静默当作正常 Cache Miss。

应：

1. 生成结构化 Quality Issue；
2. 将损坏分区移动到：

```text
user_data/cache/market_data/miniqmt/v1/quarantine/
```

3. `CACHE_ONLY` 模式直接失败；
4. `PREFER_CACHE` 模式可以重新下载；
5. 保留可诊断文件名和原因；
6. 不允许损坏数据进入 Replay。

---

## 4.19 user_data 集成

缓存根目录必须由 OnlyAlpha 核心提供，不能由 MiniQMT 使用：

```python
Path.cwd()
```

查找现有 `OnlyUserDataLayout` 或同义组件。

标准布局：

```text
user_data/
├── cache/
└── runs/
```

DataSource 创建上下文应获得公共缓存服务或缓存根路径。

推荐优先传递：

```python
OnlyHistoricalCacheService
```

而不是让插件自行实例化 Store。

如果现有 Plugin SPI 不适合传服务，可扩展公共 CreateRequest，但必须保持：

* 核心不依赖 MiniQMT；
* 插件不访问 Runtime 私有容器；
* 不暴露 Engine 私有状态；
* 不允许插件使用当前工作目录猜路径。

---

# 五、MiniQMT 插件实现

## 5.1 Provider 结构

在 `onlyalpha-plugin-miniqmt` 中实现：

```python
MiniQmtHistoricalDataProvider
```

它实现核心：

```python
OnlyHistoricalDataProvider
```

MiniQMT Historical DataSource 本身调用核心 Cache Service：

```python
class MiniQmtHistoricalDataSource:
    def load_bars(
        self,
        request: OnlyHistoricalDataRequest,
    ) -> OnlyHistoricalDataResult:
        return self._historical_cache.load(
            request=request,
            provider=self._provider,
            policy=self._config.cache_policy,
        )
```

禁止 MiniQMT 插件重复实现：

```text
Coverage 算法
Parquet Store
Manifest 基础格式
原子写
文件锁
Fingerprint
通用 Bar 验证
```

---

## 5.2 MiniQMT 原始数据验证

Provider 获取 xtquant 数据后，在转换前检查：

```text
返回对象类型
请求股票代码是否存在
必需字段是否存在
时间字段是否存在
OHLC 字段是否可转换
volume 是否可转换
amount/turnover 是否可转换
返回是否为空
返回代码是否与请求一致
原始时间是否可解析
```

定义 MiniQMT 专属错误码，例如：

```text
MINIQMT_EMPTY_RESPONSE
MINIQMT_SYMBOL_MISSING
MINIQMT_REQUIRED_COLUMN_MISSING
MINIQMT_TIMESTAMP_INVALID
MINIQMT_PRICE_INVALID
MINIQMT_VOLUME_INVALID
MINIQMT_RESPONSE_TYPE_INVALID
```

这些错误映射到核心 `OnlyDataQualityIssue`，供应商细节放在 metadata。

---

## 5.3 Exchange 和 Instrument 映射

复用现有 MiniQMT exchange mapping。

必须稳定映射：

```text
600000.SH → 600000.XSHG 或项目当前标准
000001.SZ → 000001.XSHE 或项目当前标准
```

不要在本任务中修改既有 Domain Instrument ID 规范，除非发现明确错误。

映射后要验证：

* 请求 Instrument 和返回 Vendor Symbol 一致；
* 多股票结果不串数据；
* Venue 正确；
* 标准排序稳定。

---

## 5.4 MiniQMT 时间戳解释

这是本任务的关键部分。

必须通过：

* 当前 xtquant 文档；
* 现有测试；
* 实际 MiniQMT 返回样本；

确认以下内容：

```text
日线 timestamp 的单位
分钟线 timestamp 的单位
返回值时区
日线 timestamp 表示日期、开盘还是收盘
分钟线 timestamp 表示 Bar Open 还是 Bar Close
```

不要凭经验猜测。

实现：

```python
MiniQmtTimestampNormalizer
```

职责：

```text
解析原始时间
识别周期
识别供应商标签语义
映射到 OnlyAlpha event_time
生成 trading_day
保留 source_time_raw
转换为 UTC
```

### 日线规则

建议目标语义：

```text
trading_day = 对应中国市场交易日
event_time = 当日市场收盘时刻转换为 UTC
```

但必须与现有 Historical Replay 和 Domain Bar 约定一致。

如果当前系统已统一使用其他日线 event_time 规则，应复用现有规则，并在文档中明确。

不得直接通过：

```python
event_time_utc.date()
```

推导中国市场 trading day。

### 分钟线规则

确认 MiniQMT 标签是 Bar Open 还是 Bar Close。

如果供应商为 Bar Open：

```text
09:30 的 1m Bar
→ OnlyAlpha event_time = 09:31 Asia/Shanghai
→ 再转 UTC
```

如果供应商已经返回 Bar Close，则不能重复加周期。

必须测试：

```text
上午开盘
上午收盘
下午开盘
下午收盘
午休边界
跨 UTC 日期显示
```

---

## 5.5 查询边界

用户配置可能传：

```yaml
start: "2025-01-01"
end: "2025-03-31"
```

对外语义：

```text
包含起始交易日
包含结束交易日
```

内部统一转换为：

```text
[start, end)
```

MiniQMT Provider 查询时需正确转换供应商要求的边界格式。

必须测试：

* 起始日非交易日；
* 结束日非交易日；
* 单个交易日；
* 跨年；
* 分钟级范围；
* 时区转换后不丢首尾 Bar。

---

## 5.6 MiniQMT 配置

扩展现有配置，建议支持：

```yaml
extensions:
  mode: historical
  period: 1d
  adjustment: none
  cache:
    enabled: true
    policy: prefer_cache
    root: null
    strict_validation: true
```

要求：

* `root: null` 使用核心标准 user_data cache root；
* 显式路径只作为高级覆盖；
* 相对路径必须有稳定解析基准；
* 默认不能基于 `Path.cwd()`；
* 默认策略 `prefer_cache`；
* 配置解析仅在 MiniQMT 插件中；
* 核心不理解 xtquant 特有字段。

如果核心统一缓存服务要求缓存始终开启，可以移除 `enabled`，不要保留无效配置。

---

## 5.7 数据获取和下载

根据当前 MiniQMT SDK 接口正确处理：

```text
本地已有数据
需要先下载数据
查询数据
下载失败
查询为空
SDK 未安装
MiniQMT 路径无效
```

如果 xtquant 的“下载”和“查询”是分开的：

```text
Provider.fetch
    ↓
确认缺失范围
    ↓
download_history_data
    ↓
get_market_data_ex
```

不要把整个请求范围每次重新下载。

对无交易日缺口不能无限重复下载。

需要区分：

```text
缺少缓存
供应商返回合法空区间
供应商数据确实缺失
SDK 下载失败
```

必要时在 Manifest Metadata 中记录合法空区间，但必须谨慎，避免把供应商短暂失败永久登记为“无数据”。

---

# 六、缓存行为

## 6.1 第一次运行

```text
Cache 不存在
→ inspect 返回缺失范围
→ Provider 下载缺口
→ 原始数据验证
→ 时间标准化
→ Domain 转换
→ 核心数据验证
→ 原子写 Parquet
→ 写 Manifest
→ 从 Parquet 重新读取
→ Historical Replay
```

## 6.2 第二次运行

```text
Cache 完整
→ 不访问 MiniQMT SDK
→ 从 Parquet 读取
→ Historical Replay
```

需要通过 Mock 或 Spy 验证第二次运行 `Provider.fetch()` 没有被调用。

## 6.3 部分覆盖

已有：

```text
2025-01-01 ～ 2025-06-30
```

请求：

```text
2025-01-01 ～ 2025-07-31
```

只能补：

```text
2025-07-01 ～ 2025-08-01
```

内部半开区间。

## 6.4 CACHE_ONLY

缓存覆盖完整：

```text
成功运行
```

缓存缺失、损坏或不兼容：

```text
立即结构化失败
不得访问 MiniQMT
```

## 6.5 FORCE_REFRESH

重新获取请求范围，但必须：

* 新数据验证成功后才替换旧数据；
* 写入失败时旧缓存仍可使用；
* 不影响请求范围外缓存。

---

# 七、OnlyAlpha-examples 真实回测示例

## 7.1 示例目录

新增：

```text
OnlyAlpha-examples/
└── examples/
    └── miniqmt_real_history_backtest/
        ├── README.md
        ├── config.yaml
        ├── config_cache_only.yaml
        ├── run.py 或项目正式入口
        └── expected/
            └── README.md
```

优先使用现有 OnlyAlpha CLI。

不要为了示例创建绕过 Engine 的 Python 入口。

如果现有 examples 统一使用 Python 入口，则仍必须调用正式 `OnlyEngine` 产品链，不能直接创建 Runtime 或 DataSource。

---

## 7.2 示例场景

第一版保持简单：

```text
市场：一只普通 A 股
数据源：MiniQMT Historical
周期：日线
历史区间：固定、较短、可配置
策略：现有简单策略或 MACD
Broker：Virtual Broker
成交：现有确定性 Next-Bar 模型
初始资金：固定
输出：标准 user_data/runs
```

建议默认股票：

```text
600000.SH / 对应 OnlyAlpha 标准 Instrument ID
```

但应允许用户通过配置修改。

不要在示例中加入尚未实现的完整 A 股规则。

---

## 7.3 示例配置

必须使用当前正式 `OnlyClusterRunConfig` 语法。

示意：

```yaml
cluster_id: miniqmt-real-history-demo

runtime:
  type: backtest
  start: "2025-01-01"
  end: "2025-03-31"

data_sources:
  - source_id: miniqmt-history
    plugin: miniqmt
    coverage:
      instrument_ids:
        - 600000.XSHG
    extensions:
      mode: historical
      period: 1d
      adjustment: none
      cache:
        policy: prefer_cache
        strict_validation: true

broker:
  plugin: virtual

strategy:
  plugin: <现有可用策略插件>
  extensions:
    ...
```

实际字段必须根据当前配置模型修正，不允许另造不兼容 YAML。

---

## 7.4 示例 README

README 必须写清：

### 环境要求

```text
Windows
MiniQMT 已安装
xtquant 可导入
本地行情目录可访问
OnlyAlpha、OnlyAlpha-plugins、OnlyAlpha-examples 已安装
```

### 第一次运行

说明：

```text
MiniQMT 获取缺失历史数据
→ 验证
→ 写入 user_data/cache
→ 从 Cache 读取
→ 回测
```

### 第二次运行

使用：

```text
cache_only
```

证明：

```text
不访问 MiniQMT SDK
仍可完成相同回测
```

### 缓存位置

说明标准位置，但不能硬编码特定用户绝对路径：

```text
<user_data>/cache/market_data/miniqmt/
```

### 运行输出

```text
<user_data>/runs/<run-id>/
```

### 预期结果

包括：

* Cache Hit/Miss；
* 数据范围；
* Bar 数量；
* Data Fingerprint；
* 回测结果位置；
* 第二次运行结果应与第一次一致。

不得提交虚构的具体收益率作为固定断言。

---

# 八、运行结果集成

每次回测输出中至少记录：

```text
data source plugin
plugin version
cache policy
cache hit
requested range
actual range
instrument IDs
bar type
row count
content fingerprint
schema version
time semantics version
quality report summary
```

建议写入：

```text
user_data/runs/<run-id>/data_manifest.json
```

或复用当前已有运行 Manifest。

不要复制同一信息到多个不一致文件。

回测确定性 Fingerprint 应纳入：

```text
数据内容 fingerprint
标准化配置
插件版本
策略配置
运行时关键配置
```

不得纳入：

```text
缓存创建时间
绝对缓存路径
下载时间
运行目录随机 ID
```

---

# 九、测试要求

## 9.1 OnlyAlpha 单元测试

至少覆盖：

### Time Range

```text
naive datetime 拒绝
UTC 区间
合并区间
重叠区间
相邻区间
左缺口
右缺口
中间缺口
两侧缺口
空覆盖
```

### Cache Policy

```text
CACHE_ONLY 完整命中
CACHE_ONLY 缺失失败
PREFER_CACHE 完整命中不 Fetch
PREFER_CACHE 缺失只 Fetch 缺口
FORCE_REFRESH 替换请求范围
```

### Manifest

```text
序列化往返
未知 Schema 失败
Key 不匹配失败
Hash 不匹配失败
```

### Parquet Store

```text
写入和读取
时间过滤
稳定排序
分区
原子写失败保留旧缓存
损坏文件进入 quarantine
```

### Validation

```text
非法 OHLC
负 volume
重复 Bar
时间倒退
非 UTC event_time
Instrument 不一致
Bar Type 不一致
```

### Fingerprint

```text
相同数据 hash 相同
行顺序标准化后 hash 相同
数据变化 hash 改变
created_at 不影响 hash
绝对路径不影响 hash
```

### Locking

```text
同分区互斥
不同分区不冲突
超时
旧锁恢复
```

---

## 9.2 MiniQMT 插件单元测试

不依赖真实 MiniQMT：

```text
原始字段验证
symbol mapping
exchange mapping
日线时间标准化
分钟线时间标准化
UTC 转换
trading_day
查询边界
空响应
缺字段
重复时间
多股票稳定排序
Cache Key 构造
Metadata
```

使用假的 Provider SDK Adapter，不直接 Mock 深层 xtquant 全局函数。

建议将 SDK 调用封装为明确 Adapter，方便测试。

---

## 9.3 缓存纵切面测试

使用 Fake Provider：

第一次：

```text
无缓存
→ Fetch 被调用
→ Parquet 写入
→ 返回数据来自 Parquet
```

第二次：

```text
Cache 完整
→ Fetch 调用次数不增加
→ 返回相同 Bar
→ Fingerprint 相同
```

部分缺口：

```text
只 Fetch 缺失范围
```

CACHE_ONLY：

```text
Provider 抛错或不可用也可完成缓存回放
```

---

## 9.4 固定样本测试

使用结构与 MiniQMT 返回一致的小型测试样本。

不要提交大规模真实行情。

如真实行情数据受许可限制，构造合成但供应商格式一致的 Fixture。

验证：

```text
MiniQMT Raw Sample
→ Timestamp Normalizer
→ OnlyBar
→ Parquet
→ OnlyBar
```

往返结果一致。

---

## 9.5 真实 MiniQMT 集成测试

扩展现有真实 xtquant 历史测试。

测试标记：

```text
integration
requires_miniqmt
windows_only
```

验证：

1. 获取一个股票的小区间；
2. 写入临时 user_data Cache；
3. 记录 Bar 序列和 Fingerprint；
4. 禁止 Provider 再访问 SDK；
5. 使用 CACHE_ONLY 重新读取；
6. 两次 Bar 序列相同；
7. 两次 Fingerprint 相同。

常规 Linux/macOS CI 不应因为缺少 MiniQMT 失败。

测试跳过必须给出明确环境原因。

---

## 9.6 Workspace 端到端测试

在三仓 Workspace 验证：

```text
OnlyAlpha
OnlyAlpha-plugins
OnlyAlpha-examples
```

必须通过真实 Entry Point 加载：

```text
MiniQMT DataSource Plugin
Strategy Plugin
Virtual Broker
```

不允许：

```text
手工 registry 注册
sys.path 插入兄弟仓库
直接 import 插件私有类绕过 Entry Point
```

---

# 十、质量门禁

修改前记录基线。

修改后分别在三个仓库执行其现有质量命令。

至少包括：

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

对于真实 MiniQMT 测试，使用项目定义的显式命令。

验证 Python：

```text
Python 3.12
Python 3.13
```

如果 xtquant 只支持某个 Python 版本，必须：

* 在文档中明确；
* 核心测试仍覆盖 3.12 和 3.13；
* MiniQMT 真实环境测试只在受支持版本执行；
* 不降低 OnlyAlpha 核心最低版本。

---

# 十一、不可破坏的不变量

本任务不得破坏：

```text
CLI → OnlyEngine → RuntimePlanner → RuntimeSession 正式链路
核心不依赖 OnlyAlpha-plugins
核心不依赖 OnlyAlpha-examples
插件不访问 Engine/Runtime 私有容器
Broker 回报只通过 BrokerInboundQueue
ExecutionProcessor 是执行回报唯一业务入口
相同输入产生相同回测结果
事件只在状态成功修改后发布
多 Cluster Runtime 分组
user_data 运行输出隔离
stop/close 幂等
失败时资源逆序回滚
```

缓存还必须满足：

```text
缓存损坏不能进入 Replay
缓存写失败不能破坏旧缓存
CACHE_ONLY 不能访问供应商
首次运行和后续运行都从 Parquet 读取
相同标准化数据 Fingerprint 相同
缓存路径不参与业务 Fingerprint
```

---

# 十二、禁止事项

不要：

```text
在 MiniQMT 插件中重复实现整套 Cache
在核心中 import MiniQMT
通过 Path.cwd() 猜 user_data
直接缓存原始 DataFrame 作为唯一数据格式
把价格无条件存成 float64
把 created_at 纳入内容 Fingerprint
文件存在就视为缓存有效
整个请求范围每次重新下载
缺失交易日自动补造 Bar
没有 Bar 就认定为停牌
静默修复非法 OHLC
真实 MiniQMT 测试阻塞普通 CI
手工注册插件绕过 Entry Point
为示例直接创建 Runtime
开始完整 A 股市场规则开发
引入 Redis、数据库或分布式缓存
创建通用万能缓存框架
使用深层继承覆盖整个 Cache Service
```

扩展机制优先：

```text
Protocol
组合
策略注入
```

不要形成：

```text
BaseCache
→ HistoricalCache
→ BarCache
→ ParquetBarCache
→ MiniQmtParquetBarCache
```

---

# 十三、推荐实施顺序

严格按以下阶段执行：

```text
1. 阅读三仓源码并输出差距分析
2. 运行现有测试并记录基线
3. 确认 MiniQMT 时间戳真实语义
4. 在 OnlyAlpha 实现 OnlyTimeRange 和 Coverage
5. 实现 Cache Key、Policy、Manifest 和 Inspection
6. 实现通用 Historical Bar Validation
7. 实现 Parquet Cache Store
8. 实现 Fingerprint、Atomic Write、Lock 和 Quarantine
9. 实现 OnlyHistoricalCacheService
10. 将 Cache Service 接入 DataSource Create Context
11. 在 MiniQMT 实现 HistoricalDataProvider
12. 实现 Raw Validator 和 Timestamp Normalizer
13. 重构 MiniQMT Historical DataSource 使用 Cache Service
14. 补充核心和插件测试
15. 在 OnlyAlpha-examples 增加真实回测示例
16. 完成首次下载和 CACHE_ONLY 二次运行验证
17. 运行三个仓库完整质量门禁
18. 输出最终实现报告
```

每完成一个阶段运行相关测试。

不要将所有改动堆积到最后。

---

# 十四、最终交付报告

任务完成后输出中文报告，包含：

## 1. 修改前分析

* 当前 MiniQMT Historical 链路；
* 当前时间语义；
* 当前 user_data 注入方式；
* 当前缺失能力。

## 2. OnlyAlpha 核心新增内容

列出：

* 公共接口；
* 时间范围模型；
* Coverage；
* Cache Policy；
* Cache Key；
* Manifest；
* Validation；
* Parquet Store；
* Cache Service；
* Lock；
* Atomic Write；
* Quarantine；
* Fingerprint。

## 3. MiniQMT 插件修改

列出：

* Provider；
* Raw Validator；
* Timestamp Normalizer；
* SDK Adapter；
* Cache 集成；
* 配置变化；
* Entry Point 是否变化。

## 4. 时间语义结论

明确写出：

```text
MiniQMT 日线时间戳含义
MiniQMT 分钟线时间戳含义
OnlyAlpha 标准 event_time
trading_day 生成规则
UTC 转换规则
查询 start/end 语义
```

不得含糊描述。

## 5. Cache 行为

说明：

* Cache 命中条件；
* 分区方式；
* Missing Range 算法；
* 第一次运行；
* 第二次运行；
* CACHE_ONLY；
* FORCE_REFRESH；
* 损坏缓存；
* 并发写。

## 6. Examples

说明：

* 示例目录；
* 示例股票和周期；
* 启动命令；
* 第一次运行结果；
* 第二次离线运行结果；
* 输出目录；
* Data Fingerprint。

## 7. 测试结果

给出实际执行结果：

```text
OnlyAlpha pytest
OnlyAlpha Ruff
OnlyAlpha format check
OnlyAlpha Mypy

OnlyAlpha-plugins pytest
OnlyAlpha-plugins Ruff
OnlyAlpha-plugins format check
OnlyAlpha-plugins Mypy

OnlyAlpha-examples tests
Workspace end-to-end test
真实 MiniQMT integration test
Python 3.12
Python 3.13
```

不得虚构通过结果。

## 8. 确定性结果

说明：

* 两次标准化 Bar 序列是否一致；
* 两次数据 Fingerprint 是否一致；
* 两次回测结果是否一致；
* 第二次是否完全未调用 MiniQMT SDK。

## 9. 未完成项

只列本任务范围内仍未完成的事项。

不要把完整 A 股规则、Paper、Live 或 Web 扩展进当前报告。

---

# 十五、完成判定

只有满足以下条件才算完成：

```text
OnlyAlpha 定义标准 Historical Cache 接口
OnlyAlpha 提供通用 Parquet Store
OnlyAlpha 提供 Time Range 和 Coverage 算法
OnlyAlpha 提供 Manifest、Validation 和 Fingerprint
OnlyAlpha 提供原子写、锁和损坏缓存处理
MiniQMT 只实现 Provider、供应商验证和时间解释
MiniQMT 不重复实现 Cache 基础设施
缓存位于标准 user_data/cache 下
缓存路径不依赖当前工作目录
缓存不只根据文件存在判断
缓存支持缺口补齐
首次运行下载后从 Parquet 读取
第二次 CACHE_ONLY 不访问 MiniQMT
两次 Bar 序列和 Fingerprint 一致
OnlyAlpha-examples 提供正式真实回测示例
示例通过正式 CLI/Engine 产品链
普通 CI 不依赖 MiniQMT 环境
三个仓库质量门禁通过
```

本任务的核心原则是：

> OnlyAlpha 负责标准、缓存语义和通用实现；MiniQMT 负责供应商数据获取与解释；Examples 只负责展示正式产品链。

最终要得到的不是一个“能把 DataFrame 写成 Parquet”的临时代码，而是一套可供未来其他 Historical DataSource 复用的标准历史行情缓存边界，同时用 MiniQMT 真实历史回测证明该边界能够工作。
