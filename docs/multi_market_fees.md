# Multi-Market Fees

正式产品装配链为：

```text
market.fee_pack + accounts[].broker_fee_contract
→ explicit Market Pack + Broker Contract authorities
→ Order Fee Policy Binding
→ Runtime-owned OnlyFeeResolver
→ Fee Assessment
→ Order Fee Accrual Authority
→ Fee Application
```

Runtime 必须显式选择已安装且与 Market Profile 兼容的 Pack，并为 Account 选择与实际 Broker/scope 兼容的 Contract；缺失或
未知 Authority 直接 Fail Closed。Registry 拒绝 family scope drift；resolution 对零个或多个适用版本 fail closed。
`ORDER_FIXED` Schedule 在订单绑定时冻结 exact identity，`FILL_EFFECTIVE` Schedule 按绑定 family/scope 与成交交易日解析。
Virtual Broker 不报告费用权威。

Fee 基于 Execution 计算，支持 notional、quantity、contracts 与 fixed。Fee Assessment 稳定保存 Formula、Basis、Scope、
Resolution、Direction、Bounds、Rounding、Schedule/Rule Fingerprint 与目标金额；Fee Application 另行保存本次增量和累计权威。

Generic Cash、Futures 与 Crypto Pack 只用于内核 Conformance，不代表正式产品费率。正式 CN A-share Fee Pack、真实 Broker
Evidence Adapter、外汇换算和账户周期费用仍不在当前产品范围。
