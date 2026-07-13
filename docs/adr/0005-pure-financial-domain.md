# ADR-0005：纯金融 Domain、不可变快照与稳定序列化

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：domain
- Supersedes：ADR-0002 中的初始化占位实现细节（保留其强类型方向）

## 背景

初始化骨架将 Instrument ID 表达为裸字符串组合，Price/Quantity 绑定 increment，Domain 错误依赖 core。该设计不足以长期支持多市场，也违反 Domain 不依赖外层模块的目标。

## 决策

1. Domain 只依赖标准库和自身模块。
2. 金融数值使用不可变 Decimal 值对象并拒绝 float；Price、Quantity、Money 不可互换。
3. precision 属于值，tick/step 属于版本化 Instrument。
4. 所有业务 ID 使用不同强类型；Instrument ID 由 Symbol 与 Venue ID 组合。
5. Order 使用受控状态转换并返回新快照；Trade 是不可变事实；Position、Account、Portfolio 是不可变聚合快照。
6. 多币种不隐式合计，报告币种总额必须由外层提供显式换算结果。
7. 所有 Domain dataclass 通过带 schema_version 的 JSON/record 结构序列化；Decimal 保存为字符串，时间保存为 ISO 8601。
8. Instrument 子类表达市场结构，不把 A 股 T+1、涨跌停或手续费写入通用基类。

## 备选方案

- Pydantic：验证与 JSON 能力成熟，但会让最内层绑定第三方版本和行为。
- 全局缩放整数：性能和确定性好，但当前尚无跨资产精度上限及迁移依据。
- 可变聚合根：更新便利，但线程、回放、比较和缓存语义更复杂。

## 结果

公开 Domain API 相比初始化骨架发生有意的破坏性重构；这是 Domain 稳定前允许且必要的一次修正。今后破坏性修改必须新增 ADR、schema 迁移和兼容测试。Gateway 与 Storage 负责 DTO/Schema 适配，不得把供应商字段塞回 Domain。

## 验证

pytest 覆盖值对象、币种、ID、Instrument、linear/inverse/quanto 约束、订单状态、账户多币种、行情、订单簿、日历和 JSON 往返；mypy strict、ruff 和 Domain 禁止依赖扫描必须持续通过。
