# Real Manager Projection Targets 修改前审计

基线：`12e0cdc4d316c00d4160d5fdec10b71d0229de91`。

修改前只有通用 `OnlyExecutionProjectionApplier` 与 reference in-memory target；没有真实 Manager Target、Applied Projection Ledger 或 Manager restore API。Projection Target protocol 只传 sequence/projection，无法访问 committed fact，因此不能恢复 trade fingerprints、Order dedup identity 或 Account trade index。

白盒审计确认必须额外恢复：Position/Allocation `_cycles` 与 trade fingerprints；Fee/Settlement global sequence；Order/Account/Ledger/Risk event sequence；Account/Ledger valuation version；Account performance 与 Strategy equity timeline；Ledger valuation lines；各 repository 和 scope/query index。现有最终 snapshot 对 cycle、record head、valuation line 和 timeline 不充分，因此 transaction schema 必须升级。

修改前正式 ExecutionProcessor 仍是 Manager authority 写路径。本任务保留该产品路径，只新增 committed replay 能力；未创建第二套 Engine、Runtime、Manager truth、Broker path 或 Event-driven 状态迁移。
