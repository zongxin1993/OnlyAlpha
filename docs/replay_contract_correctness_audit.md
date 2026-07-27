# Replay Contract Correctness Audit

修改前审计基于 HEAD `7b536471b0f27e5afc52c08175c5fea489bd1139`。

1. Account Manager 的真实 Available Margin 是 cash balance 扣除 frozen cash、unsettled cash、reserved margin 和 occupied margin；旧 Execution State 错写为 reserved margin 减 occupied margin。
2. Account Cash Reservation 的 RELEASED 守恒允许释放差额，其余状态要求 consumed 加 remaining 等于 reserved；旧 Execution State 对所有状态只检查小于等于。Strategy Cash release 会改写原始 reserved authority；Risk 整笔 consume 只改状态而未写 consumed authority。
3. 当前 Order/Risk 主链对成功接受的 Generic T0 Cash BUY OPEN 建立 Account Cash、Strategy Cash 和 Risk Reservation。
4. 该场景明确禁止 Position Reservation、Margin Projection 和 Margin Reservation。
5. 有 Margin instruction 时，Fact 的 reserved/occupied/released delta 必须分别等于 Account before/after delta，并与 Margin State、Margin Reservation 和 maintenance margin 一致；无指令时所有 Margin fact 字段为空且 Account Margin 不变。
6. 旧 all-projections fixture 把 BUY OPEN、Position Reservation 和 Margin Projection/Reservation 组合在同一事务，属于不可能发生的业务组合。
7. 修改前没有真实 Manager snapshot parity 模块；Order、Position、Allocation、Account、Ledger 和所有 Reservation converter 都缺少统一无损/State Hash 证明，Margin 更没有正式 Entity converter。
8. 旧 all-projections Prepared 测试已删除并改写为逐 Projection codec case；依赖旧 Account Margin 公式、缺 Risk Reservation 或允许非法 presence 的测试已迁移。
