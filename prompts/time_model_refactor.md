# OnlyAlpha UTC 时间体系、交易日历与 Bar 时间语义重构任务

## 1. 任务目标

现在对 OnlyAlpha 当前工程中的时间体系进行全面检查和优化。

OnlyAlpha 是一个面向多市场、多资产的量化交易平台。第一阶段主要支持中国 A 股，后续需要支持：

* 中国期货；
* 港股；
* 美股；
* 外汇；
* 期权；
* 数字货币现货；
* 数字货币交割合约；
* 数字货币永续合约；
* 其他具有独立交易日历和交易时段的市场。

本次任务需要建立统一、明确、可测试的时间设计：

```text
系统内部的绝对时间点统一使用 UTC
市场交易规则使用交易所本地时区
交易日由 Trading Calendar 推导
UI 和外部交互层按市场时区或用户时区显示
```

核心原则：

> UTC 用于表示“某件事情在什么瞬间发生”。

> 市场本地时区用于解释“这个瞬间属于哪个交易日、哪个交易时段以及如何生成 Bar”。

不得将所有交易规则简单转换成固定 UTC 时间后永久保存，也不得只把时区当作 UI 展示信息。

---

# 2. 执行前必须阅读

开始修改前，先阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/runtime.md
docs/event.md
docs/coding_style.md
docs/testing.md
docs/adr/
```

然后扫描当前工程中所有涉及时间的实现，重点查找：

```text
datetime.now
datetime.utcnow
time.time
date.today
datetime.fromtimestamp
datetime.timestamp
tzinfo
timezone
ZoneInfo
pytz
timestamp
ts_event
ts_init
created_at
updated_at
trading_day
session
calendar
bar_start
bar_end
```

同时检查：

* Domain；
* Instrument；
* MarketRule；
* TradingCalendar；
* Tick；
* Bar；
* Order；
* Trade；
* Position；
* Account；
* Event；
* Runtime；
* Backtest；
* Gateway；
* Storage；
* Serialization；
* Web API；
* UI DTO。

先输出当前时间模型差距分析，不要直接大规模修改。

---

# 3. 先创建差距分析文档

创建：

```text
docs/time_model_analysis.md
```

至少记录：

## 3.1 当前时间类型

列出当前工程中所有时间字段：

| 类型 | 字段 | 当前类型 | 当前时区语义 | 是否存在风险 | 建议修改 |
| -- | -- | ---- | ------ | ------ | ---- |

## 3.2 风险检查

重点检查：

* 是否存在 naive datetime；
* 是否存在未标记时区的字符串；
* 是否混用 UTC 和本地时间；
* 是否使用 `datetime.utcnow()`；
* 是否使用系统本地时区；
* 是否从 UTC 日期直接推导交易日；
* 是否将美股交易时段写成固定 UTC 偏移；
* 是否忽略夏令时；
* 是否将期货夜盘归入错误日期；
* 是否将日线定义成 UTC 自然日；
* 是否无法区分事件时间和接收时间；
* Bar 是否只有一个模糊 timestamp；
* 序列化是否丢失时区；
* 数据库存储是否混用秒、毫秒、微秒或纳秒；
* UI 是否显示时间但不显示时区；
* Gateway 是否直接传递本地时间对象；
* 回测是否依赖系统当前时间。

## 3.3 当前行为基线

如果 MyQuant 中已有相关时间处理，分析：

```text
/home/zongxin/workspace/MyQuant
```

只记录其行为和可复用经验，不直接复制旧实现。

---

# 4. 时间模型强制规则

## 4.1 内部时间点统一使用 UTC

以下时间必须统一表示为 UTC 绝对时间点：

* 行情事件时间；
* 行情接收时间；
* Event 创建时间；
* 订单创建时间；
* 订单更新时间；
* 成交时间；
* Gateway 接收时间；
* Bar 开始时间；
* Bar 结束时间；
* Runtime 时间；
* 存储时间；
* 日志时间；
* 审计时间。

禁止在 Domain 中使用 naive datetime。

禁止：

```python
datetime(2026, 7, 13, 9, 30)
datetime.now()
datetime.utcnow()
```

其中 `datetime.utcnow()` 虽然语义是 UTC，但返回 naive datetime，也禁止在核心代码使用。

允许：

```python
datetime.now(timezone.utc)
```

或统一通过：

```text
OnlyClock
OnlyTimestamp
```

获取。

## 4.2 所有时间点必须 timezone-aware

任何进入 Domain 的 datetime 必须：

```python
value.tzinfo is not None
```

并且转换为 UTC 后保存。

如果收到 naive datetime，应默认拒绝，而不是猜测其时区。

只有明确的边界适配器可以根据已知配置补充时区。

## 4.3 市场时区使用 IANA 名称

必须使用：

```text
Asia/Shanghai
Asia/Hong_Kong
America/New_York
Europe/London
Asia/Tokyo
UTC
```

禁止仅使用固定偏移：

```text
UTC+8
UTC-5
+08:00
-05:00
```

固定偏移不能正确处理夏令时和历史规则变化。

Python 优先使用：

```python
zoneinfo.ZoneInfo
```

避免新增不必要的第三方时区依赖。

---

# 5. 建议新增或完善的 Domain 类型

根据当前工程实际情况，新增或完善：

```text
OnlyTimestamp
OnlyTimeZone
OnlyTradingDay
OnlyVenue
OnlyTradingCalendar
OnlyTradingSession
OnlySessionSchedule
OnlySessionType
OnlySessionId
OnlyCalendarId
OnlySessionProfileId
```

所有自定义类型必须以 `Only` 开头。

## 5.1 OnlyTimestamp

`OnlyTimestamp` 表示一个 UTC 绝对时间点。

要求：

* 内部必须标准化为 UTC；
* 不接受 naive datetime；
* 不保存本地时区；
* 可比较；
* 可排序；
* 可 hash；
* 可无损序列化；
* 支持秒、毫秒、微秒或纳秒中的一种统一精度；
* 工程必须明确唯一精度标准；
* 不允许不同模块各自采用不同 timestamp 单位。

建议接口：

```python
OnlyTimestamp.now(clock)
OnlyTimestamp.from_datetime(...)
OnlyTimestamp.from_unix_ns(...)
OnlyTimestamp.to_datetime_utc()
OnlyTimestamp.to_unix_ns()
OnlyTimestamp.to_timezone(...)
```

禁止 `OnlyTimestamp.now()` 内部直接调用系统时间而绕过 `OnlyClock`，除非它明确属于基础设施边界。

## 5.2 OnlyTimeZone

用于封装 IANA 时区名称。

要求：

* 构造时验证名称；
* 支持创建 `ZoneInfo`；
* 不接受含义模糊的缩写作为唯一标识，例如 `CST`；
* 可序列化为 IANA 名称。

## 5.3 OnlyTradingDay

`OnlyTradingDay` 表示交易所业务日期，不等同于 UTC 日期，也不一定等于事件本地自然日期。

要求：

* 绑定 Calendar 或 Venue 上下文；
* 不允许简单使用 `timestamp_utc.date()` 推导；
* 支持期货夜盘归属；
* 支持交易所特殊规则；
* 支持日线和结算使用。

---

# 6. Venue、Instrument 与 Calendar 的关系

不要在每个 Instrument 中复制完整交易时间表。

推荐关系：

```text
OnlyInstrument
    venue_id
    trading_calendar_id
    session_profile_id
```

```text
OnlyVenue
    venue_id
    timezone
    default_calendar_id
```

```text
OnlyTradingCalendar
    calendar_id
    timezone
    sessions
    holidays
    special_sessions
```

Instrument 可以通过引用复用 Venue 的默认日历，也可以覆盖：

* 特殊交易时段；
* 特殊夜盘；
* 特殊停牌；
* 特殊日线切分；
* 特殊数字货币切日规则。

Instrument 不应直接承担全部节假日和 Session 计算职责。

---

# 7. Trading Calendar 设计

`OnlyTradingCalendar` 至少负责：

* 市场本地时区；
* 正常交易日；
* 周末；
* 节假日；
* 临时休市；
* 提前收盘；
* 延迟开盘；
* 午休；
* 多个日内 Session；
* 夜盘；
* 交易日归属；
* Session 查询；
* 本地时间与 UTC 转换。

建议接口：

```python
is_trading_day(local_date)
is_trading_time(timestamp_utc)
trading_day_at(timestamp_utc)
session_at(timestamp_utc)
sessions_for_trading_day(trading_day)
next_open(timestamp_utc)
next_close(timestamp_utc)
previous_open(timestamp_utc)
previous_close(timestamp_utc)
to_market_time(timestamp_utc)
to_utc(local_datetime)
```

其中：

```python
to_utc(local_datetime)
```

必须处理夏令时导致的：

* 不存在的本地时间；
* 重复的本地时间；
* `fold` 语义。

不允许静默选择错误时间。

---

# 8. Trading Session 设计

建议定义：

```text
OnlyTradingSession
OnlySessionType
```

Session 类型至少考虑：

```text
PRE_OPEN
OPENING_AUCTION
CONTINUOUS
BREAK
CLOSING_AUCTION
POST_MARKET
NIGHT
MAINTENANCE
CLOSED
```

一个交易日可包含多个 Session。

例如 A 股：

```text
OPENING_AUCTION
CONTINUOUS 09:30-11:30
BREAK 11:30-13:00
CONTINUOUS 13:00-14:57
CLOSING_AUCTION
```

中国期货可能包括：

```text
NIGHT
DAY_MORNING
BREAK
DAY_AFTERNOON
```

数字货币可以使用 24x7 日历，但仍要明确维护窗口和日线切分策略。

---

# 9. 中国期货夜盘与 Trading Day

必须显式测试和实现：

```text
本地时间：2026-07-13 21:00 Asia/Shanghai
UTC 时间：2026-07-13 13:00 UTC
交易日：可能是 2026-07-14
```

禁止：

```python
trading_day = timestamp_utc.date()
```

也禁止：

```python
trading_day = market_local_datetime.date()
```

夜盘交易日必须由 `OnlyTradingCalendar` 或 `OnlyTradingDayResolver` 决定。

---

# 10. Tick 时间语义

检查并完善 `OnlyTick`。

至少区分：

```text
ts_event
ts_init
```

建议语义：

```text
ts_event
    交易所或数据源认为事件实际发生的 UTC 时间

ts_init
    OnlyAlpha 接收、创建或初始化该对象的 UTC 时间
```

如需进一步区分，可增加：

```text
ts_received
ts_processed
```

但不得增加多个语义不清的 timestamp。

`OnlyTick` 至少应包含：

```text
instrument_id
price
quantity
ts_event
ts_init
sequence
source
```

Quote Tick 与 Trade Tick 应保持语义清晰。

---

# 11. Event 时间语义

所有 `OnlyEvent` 至少需要：

```text
ts_event
ts_init
```

或有明确等价字段。

不得只使用一个模糊的：

```text
timestamp
```

必须明确：

* 业务事件发生时间；
* 系统创建时间；
* 接收时间；
* 处理时间。

不是所有事件都必须具有交易所时间，但字段语义必须稳定。

例如：

* Market Event：有外部 `ts_event`；
* Timer Event：`ts_event` 来源于 Runtime Clock；
* System Event：`ts_event` 可以等于产生时间；
* Order Update：`ts_event` 优先使用券商或交易所回报时间；
* 缺少外部时间时必须明确使用回退策略并记录来源。

---

# 12. Bar 模型重构要求

全面检查当前 `OnlyBar` 和 Bar 聚合逻辑。

Bar 不得仅有：

```text
timestamp
open
high
low
close
volume
```

至少应表达：

```text
instrument_id
bar_specification
open
high
low
close
volume
quote_volume
turnover
trade_count
open_interest
bar_start
bar_end
ts_event
ts_init
trading_day
session_type
is_closed
revision
adjustment_type
```

其中部分字段可选，但必须有明确语义。

## 12.1 UTC 时间字段

以下字段统一使用 UTC：

```text
bar_start
bar_end
ts_event
ts_init
```

## 12.2 Trading Day

Bar 必须能够明确归属：

```text
trading_day
```

日线、夜盘和跨 Session Bar 不能通过 UTC date 推导。

## 12.3 Bar 区间边界

必须在文档和测试中明确采用哪种区间语义。

推荐：

```text
[start, end)
```

例如一分钟 Bar：

```text
09:30:00.000 <= event < 09:31:00.000
```

测试：

* 09:30:00；
* 09:30:59.999999；
* 09:31:00。

## 12.4 Bar Specification

建议定义或完善：

```text
OnlyBarSpecification
OnlyBarType
OnlyAggregationUnit
OnlyAggregationSource
OnlyPriceType
OnlySessionFilter
OnlyAdjustmentType
```

至少能表达：

```text
1 分钟 Last Price Bar
5 分钟 Bid Price Bar
交易时段日线
1000 Tick Bar
成交量 Bar
成交额 Bar
```

## 12.5 日线 Bar

日线不能固定定义为：

```text
UTC 00:00 - UTC 24:00
```

日线应基于：

* Trading Calendar；
* Trading Day；
* Session Profile；
* 市场时区；
* 是否包含盘前盘后；
* 是否包含夜盘；
* 数字货币切日策略。

## 12.6 Volume 语义

不得只使用一个含义不明的 volume。

至少明确：

```text
volume
quote_volume
turnover
trade_count
open_interest
```

各字段单位和含义必须写入文档。

## 12.7 Bar 修订

明确支持或拒绝：

* 实时更新中的 Bar；
* 已关闭 Bar；
* 迟到 Tick；
* 历史数据修订；
* revision；
* 已发布 Bar 是否允许修改。

如果支持修订，必须让下游可以识别 revision。

---

# 13. Clock 设计

所有当前时间获取必须通过 Clock 抽象。

至少需要：

```text
OnlyClock
OnlyLiveClock
OnlyBacktestClock
OnlyVirtualClock
```

要求：

* `OnlyLiveClock` 提供 UTC 当前时间；
* `OnlyBacktestClock` 由历史事件推进；
* `OnlyVirtualClock` 用于测试；
* Domain 和策略不直接读取系统时间；
* 测试必须可注入固定时间；
* 定时器逻辑必须能在回测中复现。

搜索并替换不受控的：

```python
datetime.now()
datetime.utcnow()
time.time()
date.today()
```

基础设施边界可以读取系统时间，但必须通过 Clock 封装。

---

# 14. Storage 与序列化

持久化时必须统一时间格式。

推荐内部标准：

```text
UTC Unix timestamp，统一精度
```

建议优先使用：

```text
Unix nanoseconds
```

如果当前技术栈不适合纳秒，可选择微秒，但整个工程必须统一。

JSON 输出可以使用：

```text
ISO 8601 UTC
```

例如：

```text
2026-07-13T13:30:00.123456Z
```

要求：

* 必须包含 UTC 标识；
* 禁止输出无时区字符串；
* 反序列化必须恢复 UTC-aware datetime；
* 不允许不同表使用不同 timestamp 单位；
* 数据库字段名应能体现 UTC 或明确在 Schema 文档中说明；
* 旧数据迁移必须考虑时区来源不明的问题。

序列化回环必须满足：

```python
deserialize(serialize(value)) == value
```

并保持：

* 时间点；
* 精度；
* 时区语义；
* Trading Day；
* Session Type；
* Bar Specification。

---

# 15. Gateway 边界

外部 Gateway 返回的时间可能是：

* UTC；
* 交易所本地时间；
* 系统本地时间；
* Unix 秒；
* Unix 毫秒；
* Unix 微秒；
* Unix 纳秒；
* 无时区字符串。

每个 Gateway Adapter 必须明确声明其输入时间语义。

转换流程：

```text
外部原始时间
    ↓
Gateway Adapter 解析
    ↓
补充明确时区
    ↓
转换为 UTC
    ↓
创建 OnlyAlpha Domain 对象
```

未经标准化的本地时间不得进入 Event Bus。

如果外部时间语义不明确：

* 不要猜测；
* 抛出明确错误或配置要求；
* 记录原始值和来源；
* 允许 Adapter 通过配置指定源时区。

---

# 16. UI 与 API 展示

Domain 和 Storage 保存 UTC。

UI/API 可以支持三种展示方式：

```text
UTC
资产或 Venue 所在市场时区
操作人员本地时区
```

推荐默认：

* 行情、K 线、交易日：市场时区；
* 系统日志、跨市场风控、审计：UTC 或用户时区；
* 页面必须明确显示当前时区；
* 用户可以切换展示时区；
* 转换只发生在 DTO、API Presenter 或 UI 层；
* UI 转换不得修改原始 UTC 数据。

API 建议同时返回：

```json
{
  "timestamp": "2026-07-13T13:30:00Z",
  "display_timestamp": "2026-07-13T09:30:00-04:00",
  "display_timezone": "America/New_York"
}
```

或者只返回 UTC，由前端根据明确的 Venue 时区转换。

不要返回：

```text
2026-07-13 09:30:00
```

这种没有时区的信息。

---

# 17. 必须增加的测试

建议创建：

```text
tests/time_model/
├── test_timestamp.py
├── test_timezone.py
├── test_calendar.py
├── test_sessions.py
├── test_trading_day.py
├── test_tick_time.py
├── test_event_time.py
├── test_bar_time.py
├── test_bar_boundaries.py
├── test_daily_bar.py
├── test_futures_night_session.py
├── test_dst.py
├── test_serialization.py
├── test_gateway_time_normalization.py
├── test_ui_time_conversion.py
└── test_forbidden_naive_datetime.py
```

## 17.1 UTC 基础测试

验证：

* 所有时间点都是 timezone-aware；
* 所有内部时间标准化为 UTC；
* naive datetime 被拒绝；
* UTC 序列化无损；
* timestamp 精度一致。

## 17.2 A 股 Session

验证：

```text
09:30-11:30
13:00-15:00
Asia/Shanghai
```

验证午休期间不是连续交易时间。

## 17.3 港股 Session

验证多个 Session 和市场本地时区。

## 17.4 美股 DST

至少选择冬季和夏季日期：

```text
America/New_York 09:30
```

验证对应 UTC 不同。

验证：

* DST 开始时不存在时间；
* DST 结束时重复时间；
* 不使用固定 UTC-5。

## 17.5 中国期货夜盘

验证：

```text
2026-07-13 21:00 Asia/Shanghai
```

可归属到正确 Trading Day。

## 17.6 数字货币 24x7

验证：

* 全天交易；
* 日线切分策略明确；
* UTC 切日或交易所切日可配置；
* 维护窗口可表示。

## 17.7 Bar 边界

验证：

```text
09:30:00
09:30:59.999999
09:31:00
```

以及：

* 午休；
* 夜盘；
* 跨日；
* DST；
* 提前收盘；
* 特殊 Session。

## 17.8 实时和历史 Bar 一致

使用同一组 Tick：

* 在线聚合；
* 离线聚合。

最终 Bar 的：

```text
OHLC
Volume
bar_start
bar_end
trading_day
```

必须一致。

## 17.9 UI 转换

同一个 UTC 时间点转换到：

```text
UTC
Asia/Shanghai
America/New_York
Asia/Tokyo
```

必须表示同一瞬间。

---

# 18. 静态检查与代码扫描

增加测试或脚本检查：

* Domain 中的 naive datetime 构造；
* `datetime.utcnow()`；
* 无参数 `datetime.now()`；
* `date.today()` 用于交易日；
* 固定 UTC 偏移用于市场时区；
* 使用字符串手工加减时差；
* Bar 只有单个 timestamp；
* 未标记单位的整数 timestamp。

允许基础设施层在明确封装中读取系统时间，但需要列入白名单并说明原因。

---

# 19. 文档输出

完成后新增或更新：

```text
docs/time_model.md
docs/domain_model.md
docs/instrument_model.md
docs/runtime.md
docs/event.md
docs/web_api.md
docs/testing.md
```

`docs/time_model.md` 至少包括：

1. 时间设计原则；
2. UTC 绝对时间；
3. 市场本地时区；
4. Trading Day；
5. Trading Calendar；
6. Trading Session；
7. Tick 时间语义；
8. Event 时间语义；
9. Bar 时间语义；
10. 日线切分；
11. 夜盘；
12. DST；
13. Gateway 标准化；
14. Storage；
15. UI/API 展示；
16. 测试规范；
17. 示例。

---

# 20. ADR

创建 ADR：

```text
docs/adr/0004-utc-time-and-trading-calendar.md
```

至少记录：

## 背景

多市场系统无法依赖系统本地时间或固定 UTC 偏移。

## 决策

* 内部绝对时间统一 UTC；
* 市场规则使用 IANA 本地时区；
* Trading Day 由 Calendar 推导；
* Clock 负责提供时间；
* UI 层负责展示转换；
* Bar 同时表达 UTC 区间和 Trading Day。

## 备选方案

* 全部保存市场本地时间；
* 全部将交易规则转换为固定 UTC；
* 只保存 Unix timestamp，不保存业务日期。

说明拒绝原因。

## 影响

* Domain 类型变化；
* 序列化变化；
* 数据迁移；
* Gateway 适配；
* UI 调整；
* 新增测试。

---

# 21. 执行顺序

严格按以下顺序：

1. 扫描所有时间相关代码；
2. 创建 `docs/time_model_analysis.md`；
3. 列出风险和迁移计划；
4. 定义或修正 `OnlyTimestamp`；
5. 定义或修正 `OnlyTimeZone`；
6. 定义 Trading Day；
7. 完善 Venue 和 Calendar；
8. 完善 Session；
9. 修正 Tick 和 Event；
10. 修正 Bar；
11. 修正 Clock；
12. 修正 Gateway 时间标准化；
13. 修正序列化与 Storage；
14. 增加 UI/API 转换 DTO；
15. 增加测试；
16. 创建 ADR；
17. 更新文档；
18. 运行全部相关测试；
19. 输出迁移风险和未完成项。

不要一次性无测试地修改全部模块。

每完成一个层次，立即运行对应测试。

---

# 22. 兼容与迁移要求

如果当前代码大量使用 naive datetime，不要简单全局替换。

必须逐字段判断原始语义：

* 原值是 UTC；
* 原值是交易所本地时间；
* 原值是系统本地时间；
* 原值语义未知。

对于语义未知的历史数据：

* 不允许直接假定为 UTC；
* 在迁移报告中列出；
* 必要时增加源时区配置；
* 无法确定时应拒绝自动迁移。

如修改公共序列化格式：

* 明确版本；
* 提供兼容读取；
* 增加迁移脚本或迁移说明；
* 不静默破坏现有数据。

---

# 23. 验收标准

完成后必须满足：

* Domain 不存在未说明的 naive datetime；
* 核心绝对时间统一 UTC；
* 市场时区使用 IANA 名称；
* 不使用固定偏移描述美股市场；
* Trading Day 不从 UTC date 直接推导；
* 中国期货夜盘归属正确；
* A 股午休处理正确；
* 美股 DST 测试通过；
* Bar 开始和结束时间明确；
* Bar 区间边界明确；
* Bar 有 Trading Day；
* 日线基于交易日历，而不是 UTC 自然日；
* Tick 和 Event 区分事件时间与系统时间；
* Gateway 在边界完成 UTC 标准化；
* Storage 时间格式和精度统一；
* UI/API 能按市场时区和用户时区展示；
* 序列化回环无损；
* 实时和离线 Bar 聚合结果一致；
* 所有时间逻辑可通过 Virtual Clock 测试。

---

# 24. 一票否决项

存在以下任一项，任务不得标记为完成：

* Domain 继续接受 naive datetime；
* 核心代码继续使用 `datetime.utcnow()`；
* 美股交易时间使用固定 UTC-5；
* Trading Day 使用 `timestamp_utc.date()` 推导；
* 期货夜盘没有明确交易日归属；
* Bar 仍只有一个模糊 timestamp；
* 日线固定使用 UTC 00:00 切分且不可配置；
* Gateway 未标准化时间就创建 Domain 对象；
* 序列化丢失时区或时间精度；
* UI 显示无时区时间；
* 测试依赖系统当前时间；
* 回测 Clock 与实盘 Clock 使用不同时间语义。

---

# 25. 最终交付报告

完成后必须输出：

```text
修改文件列表
新增文件列表
发现的时间模型问题
修复的问题
未修复的问题
兼容性风险
数据迁移风险
测试通过数
测试失败数
测试跳过数
是否存在一票否决项
是否建议继续开发 Runtime
是否建议继续开发 Backtest
```

同时给出当前时间模型结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务仅优化时间体系、交易日历、Session、Tick、Event、Bar、存储和展示边界。

不要在本任务中实现：

* 完整 Engine；
* 完整 Gateway；
* 完整回测撮合；
* 真实交易；
* Web 页面；
* 无关的策略功能。
