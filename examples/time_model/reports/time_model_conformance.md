# OnlyAlpha Time Model Conformance Report

生成时间：2026-07-13

## 结论

评分：**91/100**。UTC 绝对时间、IANA 市场时区、Calendar 推导 TradingDay、分段
Session、夜盘、纽约 DST、历史 Calendar、无损纳秒值对象、事件/Domain 序列化和三种
显示模式已经形成可测试闭环。当前实现适合作为 Runtime 的时间基础，但在进入完整
Backtest 前仍需共享 Bar 聚合器、交易所历史 Calendar 数据提供器和迟到 Tick/Bar 修订策略。

| 项目 | 得分 | 结果 |
|---|---:|---|
| UTC 与 OnlyTimestamp | 10/10 | naive 拒绝；非 UTC aware 可显式归一；Unix ns 真值 |
| IANA TimeZone 与 DST | 10/10 | 禁固定 offset；不存在/重复时间显式失败或 fold |
| Venue/Calendar/TradingDay | 17/20 | 默认引用、特殊日、夜盘、历史版本完成；无外部官方 Calendar 数据源 |
| Tick/Bar 时间语义 | 13/15 | UTC、`[start,end)`、TradingDay/Session 完成；共享聚合器未实现 |
| Order/Trade/Account/Event | 9/10 | UTC 与统一事件别名完成；订单细分生命周期时间仍未扩展 |
| 序列化与迁移 | 9/10 | UTC `Z`、ns、IANA、显式 naive 迁移完成；尚无真实旧库迁移批次 |
| UI/API 转换边界 | 10/10 | UTC/MARKET/USER_LOCAL DTO 完成 |
| 多市场与确定性 | 8/10 | 五市场 Demo、午休/夜盘/DST/TZ 确定性；完整港股特殊日和 Crypto 维护数据待补 |
| 文档、ADR 与质量门 | 5/5 | ADR、分析、模型文档、pytest/ruff/mypy 完成 |

## 文件与迁移

新增核心文件：

- `src/onlyalpha/domain/time.py`
- `src/onlyalpha/domain/venue.py`
- `src/onlyalpha/utils/time_conversion.py`
- `docs/time_model.md`
- `docs/time_model_analysis.md`
- `docs/adr/0007-utc-time-and-market-calendar.md`
- `tests/time_model/`
- `examples/time_model/`

废弃但未删除：

- `OnlyEvent.timestamp`：兼容映射到 `ts_event`。
- `OnlyInstrument.timezone`：兼容元数据；市场真值迁移到 Venue/Calendar TimeZone。

迁移字段：Instrument 增加强类型 Calendar/Profile 引用；Event 增加 `ts_init` 与
`ts_event` 语义；Calendar ID/TimeZone/TradingDay/Session/历史版本强类型化。既有绝对
datetime 字段保留名称，但约束由“aware”提升为“UTC”。

## 测试结果

- 测试总数：55
- 通过：55
- 失败：0
- 跳过：0
- ruff：通过
- mypy strict：通过（38 个 source files）
- 多市场 Demo：通过

支持场景：A 股分段交易与午休、港股上午/下午、美股盘前/常规/盘后和 DST/提前收盘、
中国期货跨午夜夜盘 TradingDay、Crypto UTC 24x7、历史 Calendar 版本和显示时区切换。

未支持场景：官方节假日数据下载/更新、交易所临时公告自动接入、完整共享 Bar 聚合器、
迟到 Tick 修订事件流、完整 Backtest/撮合、UI 页面和 Web API。

## 风险与阶段建议

历史数据迁移风险为中高：OnlyAlpha 尚无旧库存量清单，naive 字段的真实来源时区和
整数 timestamp 单位必须逐表确认。迁移工具不会猜测 UTC；DST 重复时间需人工或来源
元数据选择 fold。数据库迁移必须保存原值、来源、批次和回滚映射。

- 是否存在 naive datetime：生产绝对时间模型中未发现；Calendar 本地 `time` 和显式
  local-to-UTC 输入是市场规则/解析边界，不是内部绝对真值。
- 是否存在固定 offset：未发现市场长期固定 offset 定义；`+00:00` 仅用于 ISO 解析/`Z`
  转换，不是市场时区配置。
- 是否建议进入 Runtime：**建议有条件进入**，仅集成 UTC Clock、Calendar 查询和显示
  边界，不启动实盘。
- 是否建议进入 Backtest：**暂不建议进入完整 Backtest**；先实现共享 Bar 聚合器、
  历史 Calendar Provider 和 Bar 修订/迟到 Tick 政策。
