你现在负责在 OnlyAlpha 三仓 Workspace 中实现正式的 Tushare Historical DataSource 插件，并完成真实 A 股日线回测纵切面。

Workspace 包含：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
```

主要参考实现：

```text
https://github.com/vnpy/vnpy_tushare
```

官方接口文档：

```text
https://tushare.pro/document/2
```

本任务必须以 `vnpy_tushare` 当前稳定成品库使用的 Tushare API 调用方式为主要参考，尤其参考：

```text
tushare.set_token()
tushare.pro_api()
tushare.pro_bar()
ts_code 映射
asset 映射
freq 映射
trade_date 解析
返回结果排序
```

但只能参考 Tushare SDK 的调用方式和字段语义，不得复制 VeighNa 的框架模型、配置模型或运行架构。

不得引入：

```text
BaseDatafeed
HistoryRequest
BarData
SETTINGS
Exchange
Interval
```

OnlyAlpha 必须继续使用自己的 Domain、SPI、Cache、Runtime 和 Replay。

---

# 一、最终目标

实现以下正式链路：

```text
OnlyAlpha CLI
    ↓
OnlyEngine
    ↓
Backtest Runtime
    ↓
Tushare DataSource Entry Point
    ↓
OnlyHistoricalCacheService
    ├── Cache Inspect
    ├── Coverage Check
    ├── Missing Range Calculation
    ├── Tushare Provider Fetch
    ├── Raw Validation
    ├── Time Normalization
    ├── Domain Validation
    ├── Parquet Write
    └── Parquet Read
    ↓
Historical Replay
    ↓
Strategy
    ↓
Virtual Broker
    ↓
完整日线回测
```

第一阶段必须支持：

```text
Tushare Token 输入
沪市 A 股日线
深市 A 股日线
北交所日线（仅在核心 Venue 已支持时）
场内 ETF 日线
none 不复权
qfq 前复权
hfq 后复权
PREFER_CACHE
CACHE_ONLY
FORCE_REFRESH
Parquet Cache
真实日线回测
离线 Cache 重放
```

第一阶段不实现：

```text
分钟线
实时行情
Broker
下单
期货
期权
港股
美股
财务数据
因子接口
指数回测
可转债
基金净值
```

---

# 二、执行原则

必须严格遵守以下原则：

```text
1. OnlyAlpha 定义公共接口和 Cache 语义
2. Tushare 插件只实现供应商适配
3. OnlyAlpha 核心不能依赖 tushare
4. 插件不能重复实现 Parquet Cache
5. Examples 不能绕过 CLI 和 OnlyEngine
6. Cache 命中不能只根据文件存在
7. 首次下载后必须重新从 Parquet 读取
8. CACHE_ONLY 不得调用 Tushare SDK
9. Token 不得进入日志、Manifest、Fingerprint
10. 时间范围统一使用 UTC aware [start, end)
```

不得为了快速完成而破坏现有接口。

不得创建现有模型的同义类型。

---

# 三、开始前必须阅读

完整阅读：

```text
OnlyAlpha/AGENTS.md
OnlyAlpha/HANDOFF.md
OnlyAlpha/README.md
OnlyAlpha/docs/
OnlyAlpha/src/onlyalpha/cache/historical/
OnlyAlpha/src/onlyalpha/core/ranges.py
OnlyAlpha/src/onlyalpha/data/
OnlyAlpha/src/onlyalpha/domain/
OnlyAlpha/src/onlyalpha/runtime/
OnlyAlpha/src/onlyalpha/plugins/
OnlyAlpha/tests/

OnlyAlpha-plugins/AGENTS.md
OnlyAlpha-plugins/README.md
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/tests/
OnlyAlpha-plugins/pyproject.toml

OnlyAlpha-examples/AGENTS.md
OnlyAlpha-examples/examples/miniqmt_real_history_backtest/
OnlyAlpha-examples/pyproject.toml
```

重点确认现有接口：

```text
OnlyHistoricalDataProvider
OnlyHistoricalCacheStore
OnlyHistoricalCacheService
OnlyHistoricalDataRequest
OnlyHistoricalFetchResult
OnlyHistoricalCacheKey
OnlyHistoricalDataResult
OnlyCachePolicy
OnlyCacheManifest
OnlyCacheInspection
OnlyCacheStatistics
OnlyTimeRange
OnlyBar
OnlyBarType
OnlyInstrumentId
OnlyVenue
OnlyTradingDay
OnlyDataSourceCreateRequest
OnlyDataSourceFactory
OnlyPluginDescriptor
OnlyTradingCalendar
```

实现前先输出简短分析：

1. 当前 Historical Cache 调用链；
2. 当前 Provider 接口定义；
3. 当前 `OnlyHistoricalFetchResult` 的 Coverage 语义；
4. 当前 Cache Store 的 Manifest 和 Fingerprint 规则；
5. 当前 MiniQMT 插件如何接入 Cache Service；
6. 当前 Equity 与 ETF 配置支持；
7. 当前日线 `ts_event` 和 `trading_day` 规则；
8. 当前 Examples 的正式运行方式。

---

# 四、仓库边界

## 4.1 OnlyAlpha

原则上不因 Tushare 增加供应商特有代码。

只有在现有公共接口无法正确表达通用历史数据语义时，才允许修改核心。

允许修改的供应商无关问题包括：

```text
resolved coverage 和 observed range 未分离
合法空交易区间无法表达
Cache 诊断信息不足
通用 Adjustment 定义不足
通用 Secret 配置边界不足
Equity 配置解析缺失
```

核心中禁止出现：

```text
import tushare
pro_bar
ts_code
token
qfq
hfq
Tushare
```

通用的价格复权枚举可存在，但不得使用供应商命名污染核心。

## 4.2 OnlyAlpha-plugins

新增独立插件包：

```text
packages/onlyalpha-plugin-tushare/
```

负责：

```text
SDK 延迟加载
Token 解析
Tushare Client Adapter
ts_code 映射
asset 映射
日线查询
供应商响应验证
时间语义转换
OnlyBar 映射
Historical Provider
DataSource Factory
Doctor
测试
```

## 4.3 OnlyAlpha-examples

新增：

```text
examples/tushare_daily_backtest/
```

只提供配置、README 和正式运行示例。

---

# 五、插件包结构

建议结构：

```text
OnlyAlpha-plugins/
└── packages/
    └── onlyalpha-plugin-tushare/
        ├── pyproject.toml
        ├── README.md
        ├── src/
        │   └── onlyalpha_plugin_tushare/
        │       ├── __init__.py
        │       ├── config.py
        │       ├── errors.py
        │       ├── doctor.py
        │       ├── sdk/
        │       │   ├── loader.py
        │       │   └── adapter.py
        │       └── data_source/
        │           ├── factory.py
        │           ├── resource.py
        │           ├── provider.py
        │           ├── historical.py
        │           ├── mapping.py
        │           ├── time_semantics.py
        │           └── validation.py
        └── tests/
            ├── test_config.py
            ├── test_mapping.py
            ├── test_validation.py
            ├── test_historical.py
            ├── test_provider.py
            ├── test_factory.py
            └── test_real_tushare.py
```

实际目录风格优先遵循现有 MiniQMT 插件。

---

# 六、依赖和 Entry Point

`pyproject.toml` 至少包含：

```toml
[project]
name = "onlyalpha-plugin-tushare"
requires-python = ">=3.12"
dependencies = [
    "onlyalpha>=0.1.0",
    "tushare>=1.4.21",
]

[project.entry-points."onlyalpha.data_sources"]
tushare = "onlyalpha_plugin_tushare.data_source.factory:factory"

[project.scripts]
onlyalpha-tushare = "onlyalpha_plugin_tushare.doctor:main"
```

不得注册 Broker Entry Point。

插件 ID 固定：

```text
tushare
```

---

# 七、Tushare API 调用规范

Tushare SDK 的主要调用方式必须参考 `vnpy_tushare` 的稳定实现。

标准初始化：

```python
import tushare as ts

ts.set_token(token)
pro = ts.pro_api()
```

标准日线查询：

```python
df = ts.pro_bar(
    ts_code=ts_code,
    start_date=start_date,
    end_date=end_date,
    asset=asset,
    freq="D",
    adj=adjustment,
)
```

或者由 Adapter 封装后调用完全等价的方法。

不得自行发明非官方调用方式。

不得优先改用未在参考实现中验证的其他接口，除非官方文档明确要求且有测试证明。

第一阶段以：

```text
pro_bar
```

作为唯一 Bar 查询入口。

---

# 八、SDK Adapter

Provider 不能直接依赖 Tushare 全局模块。

定义协议：

```python
class OnlyTushareClient(Protocol):
    def pro_bar(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
        asset: str,
        freq: str,
        adj: str | None,
    ) -> object:
        ...
```

真实实现：

```python
class OnlyTushareSdkClient:
    def __init__(self, token: str) -> None:
        ts.set_token(token)
        self._pro = ts.pro_api()

    def pro_bar(...):
        return ts.pro_bar(...)
```

如果 `pro_bar()` 必须使用全局函数而不是 `pro` 实例，这一细节只允许存在于 SDK Adapter 内。

Provider、DataSource 和 Factory 不得直接散落调用：

```python
tushare.pro_bar()
tushare.set_token()
```

测试使用 Fake Client，不 Mock Tushare 深层全局实现。

---

# 九、SDK 延迟加载

参考 MiniQMT Loader 模式：

```python
@dataclass(frozen=True, slots=True)
class OnlyTushareModules:
    package: ModuleType
```

```python
def load_tushare() -> OnlyTushareModules:
    ...
```

错误分类：

```text
TUSHARE_SDK_NOT_INSTALLED
TUSHARE_IMPORT_FAILED
```

SDK 只在需要访问供应商时加载。

必须满足：

```text
CACHE_ONLY 模式在缓存完整时不创建 Tushare Client
CACHE_ONLY 模式不读取 Token
CACHE_ONLY 模式不调用 SDK
```

如果当前 Factory 架构会无条件初始化 SDK，必须调整为延迟创建 Provider Client。

---

# 十、Token 配置

必须支持：

```text
环境变量
配置字段
```

推荐配置：

```yaml
extensions:
  token_env: ONLYALPHA_TUSHARE_TOKEN
```

允许：

```yaml
extensions:
  token: "..."
```

优先级：

```text
1. token_env 指定的环境变量
2. token 字段
```

如果项目已有统一 Secret Resolver，则严格复用。

Token 规则：

```text
Token 不能为空
Token 前后空格清理
Token 不打印
Token 不写入日志
Token 不写入异常
Token 不写入 Cache Key
Token 不写入 Manifest
Token 不写入 Metadata
Token 不写入 Fingerprint
Token 不进入 repr
```

错误码：

```text
TUSHARE_TOKEN_MISSING
TUSHARE_AUTH_FAILED
TUSHARE_PERMISSION_DENIED
TUSHARE_RATE_LIMITED
TUSHARE_REQUEST_FAILED
```

示例配置不得包含真实 Token。

---

# 十一、配置模型

建议配置：

```yaml
data_sources:
  - source_id: tushare-history
    plugin: tushare
    coverage:
      instrument_ids:
        - 600000.XSHG
    extensions:
      mode: historical
      token_env: ONLYALPHA_TUSHARE_TOKEN
      frequency: 1d
      adjustment: none
      cache_policy: prefer_cache
      strict_validation: true
```

实际字段必须遵守当前 OnlyAlpha 配置模型。

不要创建与现有 Cache Policy 重复的字符串体系。

配置中只允许第一阶段真正生效的字段。

不要加入未实现的：

```text
minute
live
broker
account
realtime
```

---

# 十二、证券代码映射

参考 `vnpy_tushare`：

```text
SSE → SH
SZSE → SZ
BSE → BJ
```

OnlyAlpha 映射至少支持：

```text
600000.XSHG → 600000.SH
000001.XSHE → 000001.SZ
```

北交所仅在核心 Venue 已存在时支持：

```text
xxxxxx.XBSE → xxxxxx.BJ
```

实现：

```python
def only_to_tushare_symbol(
    instrument_id: OnlyInstrumentId,
) -> str:
    ...
```

可选实现反向映射：

```python
def only_from_tushare_symbol(
    ts_code: str,
) -> OnlyInstrumentId:
    ...
```

必须验证：

```text
Venue 必须已知
Symbol 必须合法
返回 ts_code 必须与请求一致
未知后缀明确失败
不得仅通过股票代码首位推断交易所
```

Venue 是交易所真值。

---

# 十三、资产类型映射

参考 `vnpy_tushare` 的资产类型：

```text
E  股票
FD ETF/基金
I  指数
FT 期货
```

本任务仅支持：

```text
OnlyEquity → E
OnlyETF → FD
```

不得支持指数和期货。

实现：

```python
def only_to_tushare_asset(
    instrument: OnlyInstrument,
) -> str:
    ...
```

普通股票必须映射为：

```text
E
```

不得继续使用 MiniQMT 示例中的临时 ETF 替代 Equity。

如果当前配置解析不支持 Equity，应修复通用配置层。

---

# 十四、Bar 周期

第一阶段只接受日线。

Tushare 参数：

```text
freq = "D"
```

其他周期必须结构化失败：

```text
TUSHARE_UNSUPPORTED_BAR_TYPE
```

不要声称支持 1m、60m 等未测试周期。

---

# 十五、复权

支持：

```text
NONE
QFQ
HFQ
```

Tushare 映射：

```text
NONE → adj=None
QFQ  → adj="qfq"
HFQ  → adj="hfq"
```

必须使用核心通用复权类型。

Cache Key 必须包含复权语义。

特别注意：

```text
QFQ 结果可能受查询 end_date 影响
```

因此不能让不同查询终点的前复权数据错误共用相同缓存身份。

必须选择并实现明确策略：

方案 A：

```text
QFQ Cache Key 包含 adjustment_anchor
adjustment_anchor = 请求结束日
```

方案 B：

```text
禁止对同一 QFQ Key 增量拼接不同 end_date 数据
每个请求终点形成独立数据版本
```

推荐方案 A。

核心中不得出现 `qfq` 或 `hfq` 字符串作为供应商专用逻辑。

可以增加供应商无关字段：

```text
price_adjustment
price_adjustment_reference
normalization_version
```

必须增加测试证明：

```text
none/qfq/hfq 不共用缓存
不同 qfq anchor 不错误共用缓存
```

---

# 十六、时间范围转换

OnlyAlpha 请求统一：

```text
UTC aware
[start, end)
```

Tushare 日线接口使用：

```text
start_date 包含
end_date 包含
YYYYMMDD
```

转换规则：

```text
OnlyAlpha start
→ 转 Asia/Shanghai
→ 取起始自然日

OnlyAlpha end
→ 转 Asia/Shanghai
→ 减去最小时间单位或按交易日边界计算
→ 取最后一个包含日
```

日线示例：

```text
OnlyAlpha:
[2025-01-01 00:00 Asia/Shanghai,
 2025-04-01 00:00 Asia/Shanghai)

Tushare:
start_date=20250101
end_date=20250331
```

不得直接使用 UTC 日期。

必须覆盖测试：

```text
单日
跨月
跨年
首日周末
末日周末
时区转换
半开转包含式边界
```

---

# 十七、日线时间语义

Tushare 日线返回：

```text
trade_date
```

它表示市场交易日，不是 UTC Timestamp。

标准映射：

```text
trading_day = trade_date
```

`ts_event` 应使用该交易日市场 Session Close。

优先调用：

```text
OnlyTradingCalendar
```

获取：

```text
session_open
session_close
```

推荐：

```text
bar_start = session_open
bar_end = session_close
ts_event = session_close
```

全部转换为 UTC aware datetime。

禁止：

```python
trading_day = event_time_utc.date()
```

禁止：

```python
trade_date.replace(tzinfo=UTC)
```

必须先按 Asia/Shanghai 市场交易日解释，再转换 UTC。

---

# 十八、Coverage 语义

必须严格处理：

```text
请求范围
供应商成功查询范围
实际有 Bar 的范围
```

不能把：

```text
[first_bar, last_bar]
```

直接当成请求已完整覆盖范围。

建议核心接口明确区分：

```python
@dataclass(frozen=True)
class OnlyHistoricalFetchResult:
    records: tuple[OnlyBar, ...]
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, JsonValue]
```

语义：

```text
resolved_ranges：
供应商请求成功且已确定的数据查询范围，
可包含周末、节假日和合法无数据日。

observed_ranges：
实际存在 Bar 的观测区间。
```

Tushare 请求成功并返回合法响应时：

```text
resolved_ranges = requested range
```

即使请求范围包含：

```text
周末
法定节假日
非交易日
```

但以下情况不得标记为 resolved：

```text
网络失败
鉴权失败
积分不足
权限不足
限流
响应格式异常
SDK 异常
无法确认空结果合法
```

必须优先修复当前 MiniQMT 暴露的：

```text
cache remains incomplete after fetch
```

根因，确保 Tushare 不重复该问题。

---

# 十九、Raw Response Validation

Tushare 返回对象进入 Domain 转换前必须严格验证。

必需列：

```text
ts_code
trade_date
open
high
low
close
vol
```

可选列：

```text
amount
pre_close
change
pct_chg
```

验证内容：

```text
返回不是 None
返回类型正确
必需列存在
ts_code 与请求一致
trade_date 格式正确
OHLC 非空
OHLC 非 NaN
OHLC 非 Inf
OHLC > 0
high >= open
high >= close
low <= open
low <= close
volume >= 0
amount >= 0
无冲突重复交易日
```

禁止参考实现中的：

```python
df.fillna(0)
```

对价格字段不能自动补零。

允许对可选 `amount` 缺失：

```text
设为 0 或 None
记录 Warning
```

但必须有明确规则。

错误码：

```text
TUSHARE_EMPTY_RESPONSE
TUSHARE_RESPONSE_TYPE_INVALID
TUSHARE_REQUIRED_COLUMN_MISSING
TUSHARE_SYMBOL_MISMATCH
TUSHARE_TRADE_DATE_INVALID
TUSHARE_PRICE_INVALID
TUSHARE_VOLUME_INVALID
TUSHARE_AMOUNT_INVALID
TUSHARE_DUPLICATE_BAR
```

---

# 二十、数值和单位

必须根据 Tushare 官方文档确认：

```text
price
vol
amount
```

的单位。

不得只凭 `vnpy_tushare` 推断最终 Domain 单位。

必须实现显式单位转换。

要求：

```text
价格使用 Decimal 或 Domain raw integer
禁止直接把 Numpy float 二进制值传入 Domain
volume 明确是否需要乘以 100
amount 明确是否需要单位换算
转换公式有测试
```

使用：

```python
Decimal(str(value))
```

或当前 Domain 标准转换工具。

不得使用：

```python
Decimal(float_value)
```

---

# 二十一、排序和去重

Tushare 返回顺序不得被假定。

处理顺序：

```text
验证
→ 按 trade_date 升序
→ 构造 OnlyBar
→ 按 ts_event 升序
```

重复规则：

```text
相同日期、内容完全相同：
    可去重并记录 Warning

相同日期、内容不同：
    结构化失败
```

不得通过字典后写覆盖静默处理冲突数据。

---

# 二十二、Provider

实现：

```python
class OnlyTushareHistoricalDataProvider:
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

Provider 只负责：

```text
Instrument Mapping
Asset Mapping
Adjustment Mapping
Range Conversion
SDK Request
Raw Validation
Time Normalization
OnlyBar Conversion
resolved/observed ranges
Quality Report
Source Metadata
```

Provider 不负责：

```text
Parquet
Manifest
Fingerprint
Cache Lock
Quarantine
Missing Range Algorithm
Atomic Write
```

Source Metadata 可包含：

```text
vendor=tushare
sdk_version
request_api=pro_bar
frequency=D
asset
adjustment
source_timezone=Asia/Shanghai
```

不得包含：

```text
token
token hash
用户名
环境变量值
绝对配置文件路径
```

---

# 二十三、DataSource

实现：

```python
class OnlyTushareHistoricalDataSource:
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

必须复用核心 Cache Service。

如果 `CACHE_ONLY`：

```text
不得创建 Client
不得读取 Token
不得调用 Provider.fetch
```

如果当前结构无法做到，应调整插件资源延迟初始化设计。

---

# 二十四、Cache 要求

必须严格复用 OnlyAlpha 当前 Cache 定义：

```text
OnlyHistoricalCacheService
OnlyHistoricalCacheStore
OnlyParquetHistoricalCacheStore
OnlyHistoricalCacheKey
OnlyCacheManifest
OnlyCachePolicy
OnlyCacheInspection
OnlyCacheStatistics
OnlyDataQualityReport
```

不得在插件中复制类似类。

Cache 命中条件必须包括：

```text
Key 一致
Schema Version 一致
Time Semantics Version 一致
Adjustment 一致
Adjustment Anchor 一致
Manifest 有效
Parquet 可读
Hash 一致
Resolved Coverage 完整
```

首次运行：

```text
Fetch
→ Validate
→ Write Parquet
→ Write Manifest
→ Re-inspect
→ Read Parquet
→ Replay
```

不得直接用 Fetch 内存对象进入 Replay。

第二次运行：

```text
Inspect
→ Cache Hit
→ Read Parquet
→ 不访问 Tushare
```

---

# 二十五、Doctor

增加命令：

```powershell
uv run onlyalpha-tushare doctor
```

支持：

```powershell
uv run onlyalpha-tushare doctor `
  --token-env ONLYALPHA_TUSHARE_TOKEN `
  --symbol 600000.SH
```

Doctor 只读。

至少检查：

```text
SDK 可导入
Token 存在
Client 创建成功
最小只读查询成功
响应字段正确
```

不得：

```text
打印 Token
写 Cache
运行大区间查询
下单
```

---

# 二十六、Examples

新增：

```text
OnlyAlpha-examples/
└── examples/
    └── tushare_daily_backtest/
        ├── README.md
        ├── config.yaml
        └── config_cache_only.yaml
```

默认：

```text
600000.XSHG
EQUITY
1d
2025-01-01
2025-04-01
adjustment=none
MACD
Virtual Broker
```

必须使用正式：

```text
onlyalpha run
```

禁止示例直接实例化：

```text
DataSource
Runtime
Cache Service
Provider
```

---

# 二十七、README 运行说明

设置 Token：

```powershell
$env:ONLYALPHA_TUSHARE_TOKEN = "你的 Token"
```

Doctor：

```powershell
uv run onlyalpha-tushare doctor `
  --token-env ONLYALPHA_TUSHARE_TOKEN `
  --symbol 600000.SH
```

第一次运行：

```powershell
uv run onlyalpha run `
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml `
  --user-data OnlyAlpha-examples/user_data
```

第一次预期：

```text
Tushare 查询
→ 数据验证
→ Parquet Cache
→ 从 Cache 重读
→ 日线回测
```

第二次：

```powershell
Remove-Item Env:ONLYALPHA_TUSHARE_TOKEN

uv run onlyalpha run `
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config_cache_only.yaml `
  --user-data OnlyAlpha-examples/user_data
```

第二次必须：

```text
无 Token
无网络依赖
不访问 SDK
回测成功
Fingerprint 一致
```

---

# 二十八、测试

## Token

```text
环境变量读取
直接配置读取
环境变量优先
缺失失败
Token 不出现在 repr
Token 不出现在异常
Token 不进入 Metadata
Token 不进入 Manifest
Token 不进入 Fingerprint
```

## Mapping

```text
600000.XSHG → 600000.SH
000001.XSHE → 000001.SZ
北交所映射（如支持）
Equity → E
ETF → FD
未知 Venue 失败
未知资产类型失败
```

## API Parameters

Fake Client 必须断言：

```text
ts_code
start_date
end_date
asset
freq
adj
```

与预期完全一致。

这部分必须严格参考 `vnpy_tushare` 的 `pro_bar` 调用方式。

## Time

```text
trade_date → TradingDay
Session Close → UTC ts_event
半开范围 → 包含式日期
首日非交易日
末日非交易日
跨年
单个交易日
```

## Validation

```text
None
空 DataFrame
缺列
NaN
Inf
负 volume
负 amount
Symbol 不匹配
重复相同记录
重复冲突记录
倒序数据
```

## Adjustment

```text
none
qfq
hfq
不同 adjustment 不共用 Cache
不同 qfq anchor 不错误共用 Cache
```

## Coverage

```text
包含周末的请求可完整
包含节假日的请求可完整
合法空交易区间可 resolved
请求失败不能 resolved
首次 Fetch 后 final inspect 为 valid
```

## Cache Vertical Slice

第一次：

```text
Fake Client 调用一次
Cache 写入
返回数据来自 Parquet
```

第二次：

```text
CACHE_ONLY
删除 Token
Client 不创建
SDK 调用次数不增加
Bar 一致
Fingerprint 一致
```

## Entry Point

通过已安装 Entry Point 发现：

```text
onlyalpha.data_sources:tushare
```

禁止测试手工注册。

## Real Integration

仅存在：

```text
ONLYALPHA_TUSHARE_TOKEN
```

时执行。

标记：

```text
integration
requires_tushare
```

测试：

```text
600000.SH
短区间
日线
```

验证：

```text
查询成功
排序升序
OHLC 合法
首次写 Cache
第二次 CACHE_ONLY
SDK 零调用
Fingerprint 一致
```

没有 Token 时明确 skip。

---

# 二十九、真实验收

必须实际执行：

```powershell
$env:ONLYALPHA_TUSHARE_TOKEN = "<真实 Token>"

uv run onlyalpha run `
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml `
  --user-data OnlyAlpha-examples/user_data
```

记录：

```text
status
run_id
cluster_count
rows_fetched
rows_read
cache_hit
requested_range
resolved_ranges
observed_ranges
content_fingerprint
determinism_fingerprint
manifest_path
```

随后：

```powershell
Remove-Item Env:ONLYALPHA_TUSHARE_TOKEN
```

再执行：

```powershell
uv run onlyalpha run `
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config_cache_only.yaml `
  --user-data OnlyAlpha-examples/user_data
```

必须证明：

```text
不要求 Token
不创建 Client
不访问网络
不调用 Tushare
Bar 序列一致
Content Fingerprint 一致
Determinism Fingerprint 一致
回测结果一致
```

---

# 三十、质量门禁

执行：

```powershell
uv run --directory OnlyAlpha pytest -q
uv run --directory OnlyAlpha ruff check .
uv run --directory OnlyAlpha ruff format --check .
uv run --directory OnlyAlpha mypy

uv run --directory OnlyAlpha-plugins pytest -q
uv run --directory OnlyAlpha-plugins ruff check .
uv run --directory OnlyAlpha-plugins ruff format --check .
uv run --directory OnlyAlpha-plugins mypy

uv run --directory OnlyAlpha-examples ruff check .
uv run --directory OnlyAlpha-examples ruff format --check .
```

验证：

```text
Python 3.12
Python 3.13
Windows
Linux
macOS
```

普通 CI 不使用真实 Token。

---

# 三十一、禁止事项

禁止：

```text
复制 VeighNa 框架模型
核心 import tushare
插件自己实现 Parquet
插件自己实现 Manifest
插件自己实现 Missing Range
把 Token 写入配置示例
把 Token 写入日志
把 Token 写入 Fingerprint
把 Token 写入 Cache Metadata
使用 UTC date 推导 trading_day
把周末判断为缓存缺口
df.fillna(0) 修复价格
静默覆盖重复冲突记录
普通股票声明为 ETF
第一阶段实现分钟线
第一阶段实现 Broker
绕过 Entry Point
绕过 OnlyEngine
使用 Path.cwd() 猜 user_data
Fetch 后直接用内存数据回测
```

---

# 三十二、最终报告

完成后输出中文实现报告：

## 1. 修改前分析

* Historical Cache 接口；
* MiniQMT Provider 结构；
* Coverage 当前问题；
* Equity/ETF 配置状态。

## 2. API 调用

明确：

```text
set_token
pro_api
pro_bar
参数
返回字段
```

说明哪些行为参考 `vnpy_tushare`。

## 3. 插件实现

* 包结构；
* Entry Point；
* Config；
* Loader；
* Adapter；
* Provider；
* DataSource；
* Doctor。

## 4. 时间语义

明确：

```text
trade_date
trading_day
session_open
session_close
ts_event
UTC
start/end
```

## 5. 数值单位

明确：

```text
price
vol
amount
转换公式
精度
```

## 6. 复权

明确：

```text
none
qfq
hfq
anchor
Cache Key
```

## 7. Cache

明确：

```text
resolved_ranges
observed_ranges
first run
cache-only
fingerprint
```

## 8. 测试

列出真实执行结果，不得虚构。

## 9. 真实回测

记录两次运行结果和 Fingerprint。

## 10. 未完成项

只列本任务范围内未完成内容。

---

# 三十三、完成标准

以下全部满足才算完成：

```text
独立 Tushare 插件包
正式 Entry Point
Token 环境变量支持
Token 无泄露
严格使用 pro_bar 日线接口
API 参数与 vnpy_tushare 稳定用法一致
Equity 和 ETF 资产映射正确
日线 trade_date 时间语义正确
支持 none/qfq/hfq
复权进入 Cache Identity
严格 Raw Validation
使用核心 Cache Service
resolved 和 observed Coverage 分离
请求包含周末时 Cache 可完整
首次下载后从 Parquet 重读
CACHE_ONLY 无 Token可运行
第二次不访问 SDK
真实日线回测成功
两次 Fingerprint 一致
普通 CI 无 Token时 skip
三个仓库质量门禁通过
```

最终目标是：

> 在不破坏 OnlyAlpha 核心边界的前提下，以 `vnpy_tushare` 已验证的 Tushare API 调用方式实现一个稳定、严格、可缓存、可离线重放的日线 Historical DataSource，并证明 OnlyAlpha Historical Cache 能被第二个真实供应商复用。
