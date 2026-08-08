# Fee 组件

正式链路为 `Fee Policy Pack → Order Binding → OnlyFeeResolver → Fee Assessment → Order Fee Accrual Authority → Fee Application Ledger`。
Resolver 只计算规则目标；独立的 Runtime-owned Order Fee Accrual Authority 把目标转换为当前 Fill 增量；下游只消费不可变
`OnlyFeeApplicationInstruction`，不查询 Schedule，也不重新计算最低佣金。

每条 `OnlyFeeRule` 通过显式 Formula、Basis、Direction、Resolution、Rounding 和 Pipeline 声明完整语义，并声明作用域：

- `FILL`：当前 Fill 的百分比、逐单位或固定最低费用就是本次增量；
- `ORDER_CUMULATIVE`：使用订单累计数量与名义金额计算 target，本次只收 target 减去此前累计已收费用。

`minimum`/`maximum` 不用于推断作用域。累计差额为负时 fail closed，不能借当前 Fill 静默冲销；未来由 Fee Adjustment
Transaction 表达 Supplemental Charge 或 Refund。Broker 返回的是独立 `OnlyExternalFeeEvidence`，不得进入本地 Fee Engine 或
覆盖历史 Application；累计订单报告只能经 `FEE_RECONCILIATION` 与当前有效累计费用比较。

`ORDER_FEE_ACCRUAL` 与单笔 `FEE` 是不同 Projection Component：前者 entity scope 是 Order，保存每个 component 的累计
raw/target/applied 以及 Fill count/version；后者 entity scope 是 Fee Application。两者都支持 codec、Projection replay 和
checkpoint。详细决策见 ADR 0059。
