# OnlyAlpha 时间模型现状分析

状态：2026-07-13 基线扫描，代码修改前

## 1. 扫描范围与结论

本次扫描覆盖 `src/`、`tests/`、`examples/`、架构文档与全部 ADR，并检索了
`datetime`、`date`、`time`、`timestamp`、`timezone`、`tzinfo`、`ZoneInfo`、
`UTC`、`trading_day`、`session`、`calendar`、`bar_start`、`bar_end`、
`ts_event`、`ts_init`、`created_at`、`updated_at`、`received_at`。

当前代码已经避免在生产 Domain 中直接创建 naive datetime，也没有使用固定
UTC offset 作为市场长期时区；`OnlyLiveClock` 正确使用 `datetime.now(UTC)`。
但现有校验大多只要求 `tzinfo is not None`，因此 `+08:00`、纽约本地时间或其他
非 UTC aware datetime 仍可进入 Domain、Event 和 BacktestClock。当前模型尚未形成
“UTC 绝对时间 + IANA 市场规则 + Calendar 推导交易日”的闭环。

## 2. 当前时间类型和字段

| 模块 | 当前类型/字段 | 当前语义 | 主要问题 |
|---|---|---|---|
| `domain.instrument` | `activation_time`、`effective_from/to`、到期与最后交易时间：`datetime` | Instrument 版本和合约生命周期 | 仅验证 aware，不保证 UTC；Instrument 重复保存裸 `timezone: str`；Calendar ID 是裸字符串；无 Session Profile 引用 |
| `domain.market` | Tick `ts_event/ts_init` | 数据源事件时间、OnlyAlpha 初始化时间 | 仅 aware；未校验接收顺序或明确容许的时钟偏差 |
| `domain.market` | Bar `bar_start/end`、`ts_event/init`、`trading_day: date` | `[start, end)` Bar 和业务日期 | 绝对时间仅 aware；交易日由调用方直接传入，未由 Calendar 验证或推导 |
| `domain.market` | OrderBook `event_time` | 盘口事件时间 | 命名与 Tick/Event 不统一；没有 `ts_init` |
| `domain.execution` | Order/Request/Cancel 的 `submitted_at`、`updated_at`、`requested_at`、`expire_at` | 订单生命周期 | 仅 aware；尚无 accepted/canceled/rejected 等独立业务时间 |
| `domain.execution` | Trade `executed_at/initialized_at`，属性别名 `ts_event/ts_init` | 成交和初始化时间 | 仅 aware；旧字段名仍是内部真值 |
| `domain.account` | Position `opened/updated/closed_at`；Account `updated_at`；Portfolio `as_of` | 状态快照时间 | 仅 aware，不保证 UTC |
| `event.model` | `timestamp` | 单一事件时间 | 语义模糊；无独立 `ts_event` 与 `ts_init`；仅 aware |
| `core.clock` | Live/Backtest `datetime` | 实时时钟和确定性虚拟时间 | Live 为 UTC；Backtest 只要求 aware，可被非 UTC 时间污染 |
| `domain.calendar` | `date`、本地 `time`、IANA `timezone: str` | 周末、节假日、交易时段 | 类型弱；没有 TradingDay、Session Profile、特殊日、夜盘交易日偏移和历史版本 |
| `domain.base` | ISO 8601 encode/decode | Domain JSON/record 序列化 | 保留任意输入 offset；不强制 `Z`；没有纳秒单位协议 |
| Storage | opaque bytes/key-value | 通用持久化边界 | 尚无时间 Schema，因此无字段单位、UTC 或迁移约束 |

当前没有独立 UI/API DTO 层，也没有完整 Backtest 行情数据层。因而不存在 UI
本地时间覆盖 Domain 真值的既有代码，但也没有稳定的 UTC/MARKET/USER_LOCAL
显示转换接口。

## 3. Naive datetime 与本地时间

- 生产代码没有发现 `datetime.utcnow()` 或无时区 `datetime.now()`。
- 生产代码没有主动构造 naive datetime 作为绝对时间；Calendar 的 `time` 是有意的
  市场本地墙上时间规则，不是绝对时间。
- 所有 Domain 绝对时间构造器目前都会拒绝 `tzinfo is None`，但这不等于 UTC 校验；
  一个 `Asia/Shanghai` aware datetime 仍会原样保存。
- `OnlyTradingCalendar.is_open_at` 将输入转换到 IANA 时区，这一方向正确；随后却用
  `local.date()` 直接判交易日，夜盘和跨午夜 Session 会产生错误归属。
- 测试中有 `start.date()` 直接赋给 Bar `trading_day`，证明业务日期仍由调用方猜测。

## 4. UTC、固定 Offset 与夏令时

- `OnlyLiveClock` 是当前唯一明确承诺 UTC 的时间源。
- 没有发现市场配置使用 `timezone(timedelta(...))`、`UTC+8` 或 `-05:00` 固定 offset。
- Calendar 已用 `zoneinfo.ZoneInfo`，具备采用系统 IANA tzdata 处理夏令时的基础。
- 现有测试不覆盖纽约冬夏 offset、春季不存在时间、秋季重复时间、提前收盘。
- Calendar 缺少安全的 local-to-UTC API；若直接对 naive local datetime 使用
  `replace(tzinfo=...)`，不存在/重复时间会被静默解释。

## 5. TradingDay、Session 与 Calendar 缺口

现有 `OnlyTradingSession` 只有 `name/opens_at/closes_at`。它可以判断跨午夜范围，
但不能表达 Session 类型、是否允许订单/行情、所属交易日偏移、午休、维护时段语义。
现有 Calendar 只有固定周末、节假日和一组每日重复 Session，缺少：

- 强类型 `OnlyCalendarId`、`OnlyTradingDay`、`OnlySessionProfileId`；
- Venue 默认 Calendar/Session Profile；
- 特殊休市、提前开收盘、历史有效期和临时停市；
- 夜盘锚定日期与 `belongs_to_trading_day_offset`；
- `trading_day_at`、`session_at`、前后开收盘及 session schedule API；
- 对 DST 不存在和重复本地时间的显式处理。

因此当前 A 股午休可由两个 Session 粗略表达，但中国期货夜盘交易日、美股提前
收盘和历史 Calendar 都无法可靠表达。

## 6. Tick、Bar、Order、Trade 与 Event 缺口

- Tick 已有推荐的 `ts_event/ts_init/sequence/source`，但未强制 UTC；
  `ts_init < ts_event` 没有显式政策。乱序可由 sequence 观察，但去重没有通用业务键。
- Bar 字段较完整，区间已在 docstring 和 `contains` 中实现为 `[start, end)`；没有
  模糊单一 `timestamp` 兼容字段。日线与 Calendar/Profile 的绑定仍只存在于外部
  `OnlyBarType`/Instrument 引用，Bar 自身无法证明 trading day 的来源。
- Bar 支持 `is_closed/revision`，当前规则禁止开放 Bar 带 revision，但尚未定义关闭
  Bar 修订替换策略；没有共享实时/回测聚合器。
- Order/Trade 保留既有字段以维持兼容，需在不一次性删除的前提下统一 UTC 校验和
  `ts_event/ts_init` 语义。
- Event 的单一 `timestamp` 是本轮最明确的废弃候选；应增加兼容别名/迁移期，不能
  直接破坏现有调用方。

## 7. 序列化、Storage 与旧数据风险

Domain 当前将 datetime 编码为 `datetime.isoformat()`，所以非 UTC offset 会原样
进入 JSON/record；反序列化也不会归一到 UTC。Python datetime 只保留微秒，当前
没有可无损表达纳秒整数的值对象。Storage 接口保存 bytes，不了解时间 Schema。

旧数据的真实时区目前没有清单或元数据。迁移时不能把未知 naive 值直接附加 UTC。
需要由调用者提供来源时区和字段单位，并记录迁移来源；不确定时必须失败。对已有
aware 非 UTC 数据可按同一瞬间转换 UTC。所有新 ISO 输出应使用 `Z`，整数列必须在
字段名中写明 `_ns/_us/_ms`。

## 8. 迁移边界与实施顺序

本轮采用兼容优先的增量迁移：

1. 新增纳秒整数语义的 `OnlyTimestamp`、IANA `OnlyTimeZone`、`OnlyTradingDay` 和
   Calendar/Session/Venue 强类型；所有现有绝对 datetime 字段立即强化为 UTC 校验。
2. 保留 Order/Trade/Event 的旧字段名；增加统一语义属性或兼容字段，并在文档中
   标为 deprecated。新代码使用 `ts_event/ts_init`。
3. Instrument 继续暂时保留 `timezone`，但新增/强化 Venue、Calendar 和 Session
   Profile 引用；`timezone` 只作为迁移兼容信息，不再作为市场时区真值。
4. Calendar 成为 TradingDay 唯一推导者；Bar 构造仍接受 trading day 以保持兼容，
   新增 Calendar 校验/构造入口，禁止新聚合代码用 UTC 或本地 `.date()` 猜测。
5. Domain 序列化强制 UTC `Z`；提供显式旧数据迁移函数，未知 naive 来源拒绝处理。
6. 显示转换放在 Domain 之外，只依赖稳定的 Domain TimeZone/Venue 查询对象。

## 9. ADR 编号冲突

任务指定的 `0004-utc-time-and-market-calendar.md` 与现有已接受的
`0004-event-and-concurrency.md` 冲突。为避免两个 ADR 使用同一编号，本决策使用下一个
连续编号 `0007-utc-time-and-market-calendar.md`，并在 ADR 内记录该兼容偏差。
