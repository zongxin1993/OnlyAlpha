# Fee 组件

正式链路为 `Fee Config → versioned Schedule → OnlyFeeResolver → OnlyFeeInstruction → Order Fee Accrual Reducer → FeeManager`。
Resolver 计算规则目标；独立的 Runtime-owned Order Fee Accrual Authority 把目标转换为当前 Fill 增量；FeeManager 只追加已确定
Instruction 的不可变 Fee Fact，不查询 Order、不解析 Schedule，也不计算最低佣金。

每条 `OnlyFeeRateRule` 显式声明作用域：

- `FILL`：当前 Fill 的百分比、逐单位或固定最低费用就是本次增量；
- `ORDER_CUMULATIVE`：使用订单累计数量与名义金额计算 target，本次只收 target 减去此前累计已收费用。

`minimum`/`maximum` 不用于推断作用域。累计差额为负时 fail closed，不能借当前 Fill 静默冲销；未来由 Fee Adjustment
Transaction 表达 `ADJUSTED`/`REVERSED`。Broker 明确报告 current-Fill fee 时按 `FILL` 处理；无法明确表达的累计订单报告
不得猜测为本次费用。

`ORDER_FEE_ACCRUAL` 与单笔 `FEE` 是不同 Projection Component：前者 entity scope 是 Order，保存每个 component 的累计
raw/target/charged 以及 Fill count/version；后者 entity scope 是 Fee Instruction。两者都支持 codec、Projection replay 和
checkpoint。详细决策见 ADR 0050。
