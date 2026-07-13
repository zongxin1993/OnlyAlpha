# ADR-0007：UTC 绝对时间与市场交易日历

- 状态：Accepted
- 日期：2026-07-13
- 说明：任务建议编号 0004，但该编号已被已接受的事件与并发 ADR 使用，因此顺延为 0007。

## 背景

OnlyAlpha 面向 A 股、港股、美股、期货、外汇和数字资产。不同市场存在 IANA
时区、夏令时、午休、夜盘、提前收盘、临时休市和交易日归属差异。同一 UTC
时刻的本地自然日期可能不同；期货夜盘的业务交易日也可能晚于本地自然日期。
如果事件排序、市场规则和 UI 展示共用一种“本地时间”，回测与实盘将无法保持
确定性，跨市场数据也无法可靠比较。

## 决策

1. Domain、Event、Storage 和 Runtime 中的绝对时间统一为 UTC；naive datetime
   和非 UTC 内部真值均被拒绝。
2. `OnlyTimestamp` 以 Unix 纳秒整数表达绝对时刻；Python datetime 互操作保留其
   可表达的微秒精度。已有 datetime 字段在兼容期保留，但执行同一 UTC 约束。
3. 市场规则只使用 IANA 时区，由 `zoneinfo.ZoneInfo` 提供 DST 规则；禁止固定 UTC
   offset 充当长期市场时区。
4. `OnlyTradingDay` 只能由 `OnlyTradingCalendar` 根据本地 Session 锚点、假期和
   交易日偏移推导，不能由 UTC date 或本地自然 date 直接替代。
5. Instrument 引用 Venue、Calendar ID 与 Session Profile ID。Venue 保存默认
   Calendar/Profile 和 IANA 时区；Instrument 可按需覆盖引用，但不复制完整 Calendar。
6. Bar 的绝对边界使用 UTC，区间固定为 `[start, end)`；日线绑定 TradingDay、
   Calendar 和 Session Profile 语义，不默认按 UTC 00:00 切分。
7. UI/API 显示转换位于 Domain 外，支持 UTC、MARKET、USER_LOCAL；转换结果不修改
   原始 UTC 值。
8. 未知时区的历史 naive datetime 不自动附加 UTC。迁移必须提供来源 IANA 时区，
   对 DST 歧义显式选择 fold，并记录来源。

## 备选方案

- 全部保存市场本地时间：跨市场排序不稳定，DST 重复/不存在时间无法单独消歧。
- 只保存固定 UTC offset：不能表达历史和未来 DST 规则变化。
- 每个资产自行处理时区：复制规则并导致同 Venue 资产行为分裂。
- 只保存 Unix timestamp、不保存业务日期：可表达时刻，但不能表达交易所确认的
  TradingDay、Session 与历史 Calendar 版本。

## 结果

- 跨市场事件可以按统一绝对时间排序，回测虚拟时钟与实时时钟共享 UTC 语义。
- Calendar 成为 TradingDay 和 Session 的唯一规则来源，支持午休、夜盘和 DST。
- UI 可自由选择显示时区，不污染 Domain 真值。
- 系统需要维护历史 Calendar、特殊 Session 和 tzdata 运行依赖。
- 旧字段进入兼容迁移期，Storage Schema 需要显式 UTC/单位，相关边界必须完整测试。
