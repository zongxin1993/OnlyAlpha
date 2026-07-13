# OnlyAlpha 时间模型

## 1. 核心原则

OnlyAlpha 用 UTC 表达“何时发生”，用交易所 IANA 本地时区解释“属于哪个交易日、
哪个 Session 和哪根 Bar”。Domain、Event、Storage 与 Runtime 的绝对时间必须满足
`tzinfo is not None` 且 `utcoffset() == timedelta(0)`。显示转换不改变 UTC 原值。

禁止 naive datetime、`datetime.utcnow()`、隐式本机时区、固定 `UTC+8/-05:00` 市场
定义以及用 `timestamp_utc.date()` 推导交易日。实时当前时间使用
`datetime.now(UTC)`；Unix 值的字段或 Schema 必须显式标注 ns/us/ms/s 单位。

## 2. 值对象

- `OnlyTimestamp`：有符号 Unix 纳秒整数。`from_datetime` 接受任意 aware datetime
  并归一为同一 UTC 瞬间；naive 输入失败。Python datetime 互操作只能表达微秒，
  `to_datetime()` 明确截断亚微秒余数。
- `OnlyTimeZone`：验证 IANA 名称并提供 `ZoneInfo`；`UTC` 可用，任意固定 offset 禁止。
- `OnlyTradingDay`：交易所业务日期，不是 UTC date，也不保证等于本地自然日。
- `OnlyCalendarId`、`OnlySessionProfileId`：避免 Calendar/Profile 裸字符串混用。

## 3. Venue、Instrument 与 Calendar

`OnlyVenue` 保存 Venue ID、名称、IANA TimeZone、默认 Calendar ID 和默认 Session
Profile ID。Instrument 的 Venue 由 `instrument_id.venue` 给出，并引用
`trading_calendar_id/session_profile_id`；Calendar 规则不会复制进每个 Instrument。
Instrument 的旧 `timezone` 字段暂留为兼容元数据，新代码以 Venue/Calendar 为真值。

`OnlyTradingCalendar` 保存时区、Session、周末、假期、特殊 Schedule、版本和有效日期。
`OnlyTradingCalendarCatalog` 按业务日期解析历史版本。特殊 Schedule 可表达休市或提前
开收盘；临时停市可建模为 closed schedule。

## 4. Session 与 TradingDay

Session 用本地无时区墙上 `time` 定义，因为时区属于 Calendar。它包含 SessionType、
是否允许订单/行情和 `belongs_to_trading_day_offset`。跨午夜 Session 先计算锚定日期，
再加交易日偏移。例如上海周一 21:00 到周二 02:30 的夜盘锚定周一、offset 为 1，
两段时刻都归属周二 TradingDay。

`session_at`、`trading_day_at`、`is_trading_time`、`sessions_for_trading_day`、
`next/previous_open/close` 和 `session_intervals_for_trading_day` 都由同一 Calendar 提供。
A 股午休由两个连续 Session 的空隙表达；空隙内不是交易时间，也不会被日内聚合器
视为连续区间。

Local-to-UTC 转换通过 `ZoneInfo` 往返验证：DST 春季不存在时间失败；秋季重复时间
必须显式给 `fold=0/1`。不维护自定义 DST offset 表。

## 5. Tick、Bar 与订单成交

Trade/Quote Tick 的 `ts_event` 是交易所或数据源事件时间，`ts_init` 是 OnlyAlpha
初始化时间，均为 UTC，默认要求 init 不早于 event。sequence/source 用于识别乱序和
来源；业务去重仍由数据源 trade ID 或外层 feed contract 决定。

Bar 保留 `bar_start/bar_end/ts_event/ts_init` 四个 UTC 时刻，区间固定为 `[start,end)`：
边界 end 上的 Tick 属于下一根 Bar。Bar 同时保存 TradingDay、SessionType、关闭状态、
revision 与 adjustment type。日线必须使用 `session_intervals_for_trading_day`，不能无条件
用 UTC 00:00—24:00。当前 Domain 表达开放/关闭 Bar 和关闭 Bar revision；实际迟到 Tick
替换策略与共享实时/回测聚合器尚未实现，调用方不得静默覆盖历史版本。

Order/Cancel/Trade、Position、Account、Portfolio 和 Instrument 生命周期 datetime
全部强制 UTC。Trade 暴露统一的 `ts_event/ts_init`；Event 的 `timestamp` 暂作兼容字段，
新接口使用 `ts_event`，并独立保存 `ts_init`。

## 6. 序列化与 Storage

Domain datetime JSON/record 只输出 UTC ISO 8601 `Z`，naive 或非 UTC 值无法序列化。
`OnlyTimestamp` 的 JSON 真值是 `unix_nanos`，因此纳秒整数可无损 round-trip；TimeZone
保留 IANA 名称，TradingDay/CalendarId/Session/Bar 字段使用强类型递归序列化。

Storage 可选择 UTC ISO 8601 或明确单位的整数列（如 `ts_event_ns`），禁止无单位的
`timestamp`。旧 naive 数据必须通过 `migrate_legacy_datetime` 提供来源 IANA 时区；
未知来源、DST 不存在时间或未消歧的重复时间均失败。迁移应另存来源、批次和回滚映射。

## 7. UI/API 显示

`OnlyTimeConversionService` 是 Domain 外的稳定转换边界，支持 UTC、MARKET、USER_LOCAL。
MARKET 由 Instrument → Venue → TimeZone 的查询结果驱动；USER_LOCAL 必须显式提供用户
IANA 时区。DTO 同时返回 `timestamp_utc`、带 offset 的 `display_time` 和
`display_timezone`，绝不覆盖原始 UTC。

## 8. Backtest 与示例

BacktestClock 只接受 UTC 并保持单调；Backtest 应复用 Calendar 推导 TradingDay/Session，
并按历史 Calendar 与 Instrument 版本解析。当前尚无完整聚合器或撮合器。五市场确定性
示例位于 `examples/time_model`，覆盖 A 股午休、港股分段、美股盘前/常规/盘后与 DST、
中国期货夜盘、Crypto UTC 24x7。相同输入在不同进程 `TZ` 下产生相同结果。

Clock 的权威时间戳单位是 Unix nanoseconds，与 `OnlyTimestamp.unix_nanos` 一致。Python
datetime 只是微秒精度兼容视图；sub-microsecond 真值保留在整数中。Wall Clock 用于业务时刻，
Monotonic 只用于等待与耗时。Timer、Virtual/Backtest 推进和 Cluster 权限见 `docs/clock.md`。
