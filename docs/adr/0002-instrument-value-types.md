# ADR-0002：金融值对象与 Instrument 统一模型

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：domain、instrument、execution

## 背景

项目第一阶段面向 A 股，后续需要支持期货、美股、港股、外汇、期权和数字资产。

普通 float、字符串和字典难以稳定表达精度、币种、合约和市场约束。

## 决策

采用强类型值对象：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyInstrumentId
```

采用统一 `OnlyInstrument` 抽象和资产类别扩展。

借鉴 NautilusTrader 的约束思想，但不复制其 API 和源码。

## 结果

- 降低精度错误；
- 提高多市场一致性；
- 增加初始实现成本；
- 必须建立大量边界测试；
- 持久化和 Web DTO 需支持强类型序列化。
