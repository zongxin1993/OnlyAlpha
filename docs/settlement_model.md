# Settlement Model

`OnlySettlementModel` 分别配置 asset settlement、cash settlement、asset availability、cash availability。
Execution 生成不可变 instruction，生产调用方必须使用版本化 Trading Calendar 推进业务日。

- Generic T0：资产和现金成交后立即可交易并记账。
- A 股：买入资产 T+1 可卖；卖出所得现金当日可再次交易；法律清算按 T+1 表达。
- T+N：使用显式 lag，不能使用布尔 T+1。
- Futures daily mark-to-market 是独立扩展模式，不套用股票证券交收。

当前 Account 不模拟提现；withdrawable cash 是保留边界，不能与 trade-available cash 混同。

